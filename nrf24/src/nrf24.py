# https://circuitpython-nrf24l01.readthedocs.io/en/latest/examples.html

# The MIT License (MIT)
#
# Copyright (c) 2017 Damien P. George
# Copyright (c) 2019 Brendan Doherty
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""rf24 module containing the base class RF24"""

import time
from micropython import const

_CONFIGURE = const(0x00)   # IRQ masking, CRC scheme, PWR control, & RX/TX roles
_AUTO_ACK = const(0x01)    # auto-ACK status for all pipes
_OPEN_PIPES = const(0x02)  # open/close RX status for all pipes
_EN_RXADDR = const(0x02)   # open/close RX status for all pipes
_SETUP_AW = const(0x03)    # setup address width
_SETUP_RETR = const(0x04)  # auto-retry count & delay values
_RF_CH = const(0x05)       # set radio frequency channel
_RF_PA_RATE = const(0x06)  # RF Power Amplifier & Data Rate values
_STATUS = const(0x07)      # status register
_OBSERVE_TX = const(0x08)  # transmit observe register
_RX_ADDR_P0 = const(0x0A)  # RX pipe addresses; pipes 0-5 = 0x0A-0x0F
_TX_ADDRESS = const(0x10)  # Address used for TX transmissions
_RX_PL_LENG = const(0x11)  # RX payload widths; pipes 0-5 = 0x11-0x16
_FIFO_STATUS = const(0x17)  # fifo status
_DYN_PL_LEN = const(0x1C)  # dynamic payloads status for all pipes
_TX_FEATURE = const(0x1D)  # dynamic TX-payloads, TX-ACK payloads, TX-NO_ACK

# SPI commands
_R_RX_PAYLOAD = const(0x61)  # read RX payload
_R_RX_PL_WID = const(0x60)   # read RX payload width
_W_TX_PAYLOAD = const(0xA0)  # write TX payload
_FLUSH_TX = const(0xE1)      # flush TX FIFO
_FLUSH_RX = const(0xE2)      # flush RX FIFO

# config constants
EN_CRC = const(0x08)  # enable CRC
CRCO = const(0x04)    # CRC encoding scheme; 0=1 byte, 1=2 bytes


def address_repr(buf, reverse, delimit=""):
    """Convert a buffer into a hexlified string."""
    order = range(len(buf) - 1, -1, -1) if reverse else range(len(buf))
    return delimit.join(["%02X" % buf[byte] for byte in order])


class RF24:
    """A driver class for the nRF24L01(+) transceiver radios."""

    def __init__(self, spi, cs, ce, baudrate=4000000):
        self._buf = bytearray(1)

        self._spi = spi
        self._ce = ce
        self._cs = cs

        # init the SPI bus and pins
        self._init_spi(baudrate)

        # reset everything
        self._ce.init(ce.OUT, value=0)
        self._cs.init(cs.OUT, value=1)

        self._status = 0

        # init shadow copy of RX addresses for all pipes for context manager
        self._pipes = [bytearray(5)] * 2 + [0] * 4
        # pre-configure the _CONFIGURE register:
        #   0x0E = all IRQs enabled, CRC is 2 bytes, and power up in TX mode
        self._config = 0x0E
        self._reg_write(_CONFIGURE, self._config)
        if self._reg_read(_CONFIGURE) != self._config:
            raise RuntimeError("nRF24L01 Hardware not responding")
        for i in range(6):  # capture RX addresses from registers
            if i < 2:
                self._pipes[i] = self._reg_read_bytes(_RX_ADDR_P0 + i)
            else:
                self._pipes[i] = self._reg_read(_RX_ADDR_P0 + i)
        # test is nRF24L01 is a plus variant using a command specific to
        # non-plus variants
        self._open_pipes, self._is_plus_variant = (0, False)  # close all RX pipes
        self._features = self._reg_read(_TX_FEATURE)
        self._reg_write(0x50, 0x73)  # derelict command toggles _TX_FEATURE register
        after_toggle = self._reg_read(_TX_FEATURE)
        if self._features == after_toggle:
            self._is_plus_variant = True
        elif not after_toggle:  # if features are disabled
            self._reg_write(0x50, 0x73)  # ensure they're enabled
        # pre-configure features for TX operations:
        #   5 = enable dynamic_payloads, disable custom ack payloads, &
        #       allow ask_no_ack command
        self._features = 5
        # init shadow copy of last _RX_ADDR_P0 written to pipe 0 needed as
        # open_tx_pipe() appropriates pipe 0 for ACK packet
        self._pipe0_read_addr = None
        # shadow copy of the _TX_ADDRESS
        self._tx_address = self._reg_read_bytes(_TX_ADDRESS)
        # pre-configure the _SETUP_RETR register
        self._retry_setup = (5 << 4 | 15)  # 0X5F ard=1500 (delay in (n+1)*250 µs, n=5) ; arc=15 (retry count)
        # pre-configure the RF_SETUP register
        self._rf_setup = 0x07  # 1 Mbps data_rate, and 0 dbm pa_level
        # pre-configure dynamic_payloads & auto_ack
        self._dyn_pl = 0x3F  # 0x3F = enable dyn payload on all pipes
        self._aa = 0x3F     # 0x3F = enable auto ack on all pipes
        self._channel = 76  # 2.476 GHz
        self._addr_len = 5  # 5-byte long addresses
        self._pl_len = [32] * 6  # 32-byte static payloads for all pipes

        with self:  # dumps internal attributes to all registers
            self.flush_rx()
            self.flush_tx()
            self.clear_status_flags()

    def _init_spi(self, baudrate):
        try:
            master = self._spi.MASTER
        except AttributeError:
            self._spi.init(baudrate=baudrate, polarity=0, phase=0)
        else:
            self._spi.init(master, baudrate=baudrate, polarity=0, phase=0)

    def __enter__(self):
        self._ce(0)
        self._config |= 2
        self._reg_write(_CONFIGURE, self._config)
        # time.sleep(0.00015)  # let the rest of this function be the delay
        self._reg_write(_RF_PA_RATE, self._rf_setup)
        self._reg_write(_OPEN_PIPES, self._open_pipes)
        self._reg_write(_DYN_PL_LEN, self._dyn_pl)
        self._reg_write(_AUTO_ACK, self._aa)
        self._reg_write(_TX_FEATURE, self._features)
        self._reg_write(_SETUP_RETR, self._retry_setup)
        for i, addr in enumerate(self._pipes):
            if i < 2:
                self._reg_write_bytes(_RX_ADDR_P0 + i, addr)
            else:
                self._reg_write(_RX_ADDR_P0 + i, addr)
            self.set_payload_length(self._pl_len[i], i)
        self._reg_write_bytes(_TX_ADDRESS, self._tx_address)
        self._reg_write(0x05, self._channel)
        self._reg_write(0x03, self._addr_len - 2)
        return self

    def __exit__(self, *exc):
        self._ce(0)
        self._config &= 0x7D  # power off radio
        self._reg_write(_CONFIGURE, self._config)
        time.sleep(0.00015)
        return False

    @property
    def ce_pin(self):
        """Control the radio's CE pin (for advanced usage)"""
        return self._ce.value()

    @ce_pin.setter
    def ce_pin(self, val):
        self._ce.value(val)

    def _reg_read(self, reg):
        self._cs(0)
        self._spi.readinto(self._buf, reg)
        self._status = self._buf[0]
        self._spi.readinto(self._buf)
        self._cs(1)
        # print("SPI read 1 byte from", ("%02X" % reg), ("%02X" % self._buf[0]))
        return self._buf[0]

    def _reg_read_bytes(self, reg, buf_len=5):
        self._cs(0)
        self._spi.readinto(self._buf, reg)
        self._status = self._buf[0]
        buf = self._spi.read(buf_len)
        self._cs(1)
        return buf

    def _reg_write_bytes(self, reg, buf):
        self._cs(0)
        self._spi.readinto(self._buf, 0x20 | reg)
        self._status = self._buf[0]
        self._spi.write(buf)
        self._cs(1)

    def _reg_write(self, reg, value=None):
        self._cs(0)
        if value is not None:
            self._spi.readinto(self._buf, (0x20 if reg != 0x50 else 0) | reg)
            self._status = self._buf[0]
            self._spi.readinto(self._buf, value)
        else:
            self._spi.readinto(self._buf, reg)
            self._status = self._buf[0]
        self._cs(1)

    @property
    def address_length(self):
        """This `int` is the length (in bytes) used of RX/TX addresses."""
        self._addr_len = self._reg_read(_SETUP_AW) + 2
        return self._addr_len

    @address_length.setter
    def address_length(self, length):
        self._addr_len = int(length) if 3 <= length <= 5 else 2
        self._reg_write(_SETUP_AW, self._addr_len - 2)

    def open_tx_pipe(self, address):
        """Open a data pipe for TX transmissions."""
        if self._pipe0_read_addr != address and self._aa & 1:
            self._pipes[0] = address
            self._reg_write_bytes(_RX_ADDR_P0, address)
        self._tx_address = address
        self._reg_write_bytes(_TX_ADDRESS, address)

    def close_rx_pipe(self, pipe_num):
        """Close a specific data pipe from RX transmissions."""
        if pipe_num < 0 or pipe_num > 5:
            raise ValueError("pipe number must be in range [0, 5]")
        self._open_pipes = self._reg_read(_EN_RXADDR) & ~(1 << pipe_num)
        if not pipe_num:
            self._pipe0_read_addr = None
        self._reg_write(_EN_RXADDR, self._open_pipes)

    def open_rx_pipe(self, pipe_num, address):
        """Open a specific data pipe for RX transmissions."""
        if not 0 <= pipe_num <= 5:
            raise ValueError("pipe number must be in range [0, 5]")
        if not address:
            raise ValueError("address length cannot be 0")
        if pipe_num < 2:
            if not pipe_num:
                self._pipe0_read_addr = address
            self._pipes[pipe_num] = address
            self._reg_write_bytes(_RX_ADDR_P0 + pipe_num, address)
        else:
            self._pipes[pipe_num] = address[0]  # todo was soll das. bei pipes > 2 is bei der address etwas anders
            self._reg_write(_RX_ADDR_P0 + pipe_num, address[0])
        self._open_pipes = self._reg_read(_EN_RXADDR) | (1 << pipe_num)
        self._reg_write(_EN_RXADDR, self._open_pipes)

    @property
    def listen(self):
        """This attribute is the primary role as a radio."""
        return self.power and bool(self._config & 1)

    @listen.setter
    def listen(self, is_rx):
        self._ce(0)
        self._config = self._config & 0xFC | (2 + bool(is_rx))
        self._reg_write(_CONFIGURE, self._config)
        # start_timer = time.monotonic_ns()
        start_timer = time.ticks_us()
        if is_rx:
            self._ce(1)
            if (
                    self._pipe0_read_addr is not None
                    and self._pipe0_read_addr != self.address(0)
            ):
                for i, val in enumerate(self._pipe0_read_addr):
                    self._pipes[0][i] = val
                self._reg_write_bytes(_RX_ADDR_P0, self._pipe0_read_addr)
            elif self._pipe0_read_addr is None and self._open_pipes & 1:
                self._open_pipes &= 0x3E  # close_rx_pipe(0) is slower
                self._reg_write(_OPEN_PIPES, self._open_pipes)
        else:
            if self._features & 6 == 6 and ((self._aa & self._dyn_pl) & 1):
                self.flush_tx()
            if self._aa & 1 and not self._open_pipes & 1:
                self._open_pipes |= 1
                self._reg_write(_OPEN_PIPES, self._open_pipes)
        # mandatory wait time is 130 µs
        # delta_time = time.monotonic_ns() - start_timer
        delta_time = time.ticks_us() - start_timer
        if delta_time < 150:
            time.sleep((150 - delta_time) / 1000000)
            # time.sleep(0.0001)

    def available(self):
        """A `bool` describing if there is a payload in the RX FIFO."""
        return self.update() and self._status >> 1 & 7 < 6

    def any(self):
        """This function reports the next available payload's length (in bytes)."""
        last_dyn_size = self._reg_read(_R_RX_PL_WID)
        if self._status >> 1 & 7 < 6:
            if self._features & 4:
                return last_dyn_size
            return self._pl_len[(self._status >> 1) & 7] # _RX_PL_LENG
        return 0

    def read(self, length=None):
        """This function is used to retrieve data from the RX FIFO."""
        ret_size = length if length is not None else self.any()
        if not ret_size:
            return None
        result = self._reg_read_bytes(_R_RX_PAYLOAD, ret_size)
        self.clear_status_flags(True, False, False)
        return result

    def send(self, buf, ask_no_ack=False, force_retry=0, send_only=False):
        """This blocking function is used to transmit payload(s)."""
        self.ce_pin = 0
        if isinstance(buf, (list, tuple)):
            result = []
            for byte in buf:
                result.append(self.send(byte, ask_no_ack, force_retry, send_only))
            return result
        if self._status & 0x10 or self._status & 1:
            self.flush_tx()
        if not send_only and self._status >> 1 & 7 < 6:
            self.flush_rx()
        self.write(buf, ask_no_ack)
        while not self._status & 0x30:
            self.update()
        result = bool(self._status & 0x20)
        while force_retry and not result:
            result = self.resend(send_only)
            force_retry -= 1
        if self._status & 0x60 == 0x60 and not send_only:
            result = self.read()
        return result

    @property
    def tx_full(self):
        """An `bool` to represent if the TX FIFO is full. (read-only)"""
        return bool(self._status & 1)

    @property
    def pipe(self):
        """The number of the data pipe that received the next available
        payload in the RX FIFO. (read only)"""
        result = self._status >> 1 & 7
        if result < 6:
            return result
        return None

    @property
    def irq_dr(self):
        """A `bool` that represents the "Data Ready" interrupted flag. (read-only)"""
        return bool(self._status & 0x40)

    @property
    def irq_ds(self):
        """A `bool` that represents the "Data Sent" interrupted flag. (read-only)"""
        return bool(self._status & 0x20)

    @property
    def irq_df(self):
        """A `bool` that represents the "Data Failed" interrupted flag. (read-only)"""
        return bool(self._status & 0x10)

    def update(self):
        """This function gets an updated status byte over SPI."""
        self._reg_write(0xFF)
        return True

    def clear_status_flags(self, data_recv=True, data_sent=True, data_fail=True):
        """This clears the interrupt flags in the status register."""
        config = bool(data_recv) << 6 | bool(data_sent) << 5 | bool(data_fail) << 4
        self._reg_write(_STATUS, config)

    def interrupt_config(self, data_recv=True, data_sent=True, data_fail=True):
        """Sets the configuration of the nRF24L01's IRQ pin. (write-only)"""
        self._config = (self._reg_read(_CONFIGURE) & 0x0F) | (not data_recv) << 6
        self._config |= (not data_fail) << 4 | (not data_sent) << 5
        self._reg_write(_CONFIGURE, self._config)

    @property
    def is_plus_variant(self):
        """A `bool` describing if the nRF24L01 is a plus variant or not (read-only)."""
        return self._is_plus_variant

    @property
    def dynamic_payloads(self):
        """This `int` attribute is the dynamic payload length feature for
        any/all pipes."""
        self._dyn_pl = self._reg_read(_DYN_PL_LEN)
        return self._dyn_pl

    @dynamic_payloads.setter
    def dynamic_payloads(self, enable):
        self._features = self._reg_read(_TX_FEATURE)
        if isinstance(enable, bool):
            self._dyn_pl = 0x3F if enable else 0
        elif isinstance(enable, int):
            self._dyn_pl = 0x3F & enable
        elif isinstance(enable, (list, tuple)):
            self._dyn_pl = self._reg_read(_DYN_PL_LEN)
            for i, val in enumerate(enable):
                if i < 6 and val >= 0:  # skip pipe if val is negative
                    self._dyn_pl = (self._dyn_pl & ~(1 << i)) | (bool(val) << i)
        else:
            raise ValueError("dynamic_payloads: {} is an invalid input".format(enable))
        self._features = (self._features & 3) | (bool(self._dyn_pl) << 2)
        self._reg_write(_TX_FEATURE, self._features)
        self._reg_write(_DYN_PL_LEN, self._dyn_pl)

    def set_dynamic_payloads(self, enable, pipe_number=None):
        """Control the dynamic payload feature for a specific data pipe."""
        if pipe_number is None:
            self.dynamic_payloads = bool(enable)
        elif 0 <= pipe_number <= 5:
            self._dyn_pl = self._reg_read(_DYN_PL_LEN) & ~(1 << pipe_number)
            self.dynamic_payloads = self._dyn_pl | (bool(enable) << pipe_number)
        else:
            raise IndexError("pipe_number must be in range [0, 5]")

    def get_dynamic_payloads(self, pipe_number=0):
        """Returns a `bool` describing the dynamic payload feature about a pipe."""
        if 0 <= pipe_number <= 5:
            return bool(self.dynamic_payloads & (1 << pipe_number))
        raise IndexError("pipe_number must be in range [0, 5]")

    @property
    def payload_length(self):
        """This `int` attribute is the length of static payloads for any/all pipes."""
        return self._pl_len[0]  # self._reg_read(_RX_PL_LENG)

    @payload_length.setter
    def payload_length(self, length):
        if isinstance(length, int):
            length = [max(1, length)] * 6
        elif not isinstance(length, (list, tuple)):
            raise ValueError("length {} is not a valid input".format(length))
        for i, val in enumerate(length):
            if i < 6 and val > 0:  # don't throw exception, just skip pipe
                self._pl_len[i] = min(32, val)
                self._reg_write(_RX_PL_LENG + i, self._pl_len[i])

    def set_payload_length(self, length, pipe_number=None):
        """Sets the static payload length feature for each/all data pipes."""
        if pipe_number is None:
            self.payload_length = length
        else:
            self._pl_len[pipe_number] = max(1, min(32, length))
            self._reg_write(_RX_PL_LENG + pipe_number, length)

    def get_payload_length(self, pipe_number=0):
        """Returns an `int` describing the specified data pipe's static
        payload length."""
        self._pl_len[pipe_number] = self._reg_read(_RX_PL_LENG + pipe_number)
        return self._pl_len[pipe_number]

    @property
    def arc(self):
        """This `int` attribute specifies the number of attempts to
        re-transmit TX payload when ACK packet is not received."""
        self._retry_setup = self._reg_read(_SETUP_RETR)
        return self._retry_setup & 0x0F

    @arc.setter
    def arc(self, count):
        count = max(0, min(int(count), 15))
        self._retry_setup = (self._retry_setup & 0xF0) | count
        self._reg_write(_SETUP_RETR, self._retry_setup)

    @property
    def ard(self):
        """This `int` attribute specifies the delay (in microseconds) between attempts
        to automatically re-transmit the TX payload when no ACK packet is received."""
        self._retry_setup = self._reg_read(_SETUP_RETR)
        return ((self._retry_setup & 0xF0) >> 4) * 250 + 250

    @ard.setter
    def ard(self, delta):
        delta = max(250, min(delta, 4000))
        self._retry_setup = (self._retry_setup & 15) | int((delta - 250) / 250) << 4
        self._reg_write(_SETUP_RETR, self._retry_setup)

    def set_auto_retries(self, delay, count):
        """set the `ard` & `arc` attributes with 1 function."""
        delay = int((max(250, min(delay, 4000)) - 250) / 250) << 4
        self._retry_setup = delay | max(0, min(int(count), 15))
        self._reg_write(_SETUP_RETR, self._retry_setup)

    def get_auto_retries(self):
        """get the `ard` & `arc` attributes with 1 function."""
        return self.ard, self._retry_setup & 0x0F

    @property
    def last_tx_arc(self):
        """Return the number of attempts made for last transmission (read-only)."""
        return self._reg_read(8) & 0x0F

    @property
    def auto_ack(self):
        """This `int` attribute is the automatic acknowledgment feature for
        any/all pipes."""
        self._aa = self._reg_read(_AUTO_ACK)
        return self._aa

    @auto_ack.setter
    def auto_ack(self, enable):
        if isinstance(enable, bool):
            self._aa = 0x3F if enable else 0
        elif isinstance(enable, int):
            self._aa = 0x3F & enable
        elif isinstance(enable, (list, tuple)):
            self._aa = self._reg_read(_AUTO_ACK)
            for i, val in enumerate(enable):
                if i < 6 and val >= 0:  # skip pipe if val is negative
                    self._aa = (self._aa & ~(1 << i)) | (bool(val) << i)
        else:
            raise ValueError("auto_ack: {} is not a valid input".format(enable))
        self._reg_write(_AUTO_ACK, self._aa)

    def set_auto_ack(self, enable, pipe_number):
        """Control the `auto_ack` feature for a specific data pipe."""
        if pipe_number is None:
            self.auto_ack = bool(enable)
        elif 0 <= pipe_number <= 5:
            self._aa = self._reg_read(_AUTO_ACK) & ~(1 << pipe_number)
            self.auto_ack = self._aa | (bool(enable) << pipe_number)
        else:
            raise IndexError("pipe_number must be in range [0, 5]")

    def get_auto_ack(self, pipe_number):
        """Returns a `bool` describing the `auto_ack` feature about a data pipe."""
        if 0 <= pipe_number <= 5:
            self._aa = self._reg_read(_AUTO_ACK)
            return bool(self._aa & (1 << pipe_number))
        raise IndexError("pipe_number must be in range [0, 5]")

    @property
    def ack(self):
        """Represents use of custom payloads as part of the ACK packet."""
        self._aa = self._reg_read(_AUTO_ACK)
        self._dyn_pl = self._reg_read(_DYN_PL_LEN)
        self._features = self._reg_read(_TX_FEATURE)
        return bool((self._features & 6) == 6 and ((self._aa & self._dyn_pl) & 1))

    @ack.setter
    def ack(self, enable):
        if enable:
            self.set_auto_ack(True, 0)
            self._dyn_pl = self._dyn_pl & 0x3E | 1
            self._reg_write(_DYN_PL_LEN, self._dyn_pl)
            self._features = self._features | 4
        self._features = self._features & 5 | bool(enable) << 1
        self._reg_write(_TX_FEATURE, self._features)

    def load_ack(self, buf, pipe_number):
        """Load a payload into the TX FIFO for use on a specific data pipe."""
        if pipe_number < 0 or pipe_number > 5:
            raise IndexError("pipe_number must be in range [0, 5]")
        if not buf or len(buf) > 32:
            raise ValueError("payload must have a byte length in range [1, 32]")
        if not bool((self._features & 6) == 6 and ((self._aa & self._dyn_pl) & 1)):
            self.ack = True
        if not self.tx_full:
            self._reg_write_bytes(0xA8 | pipe_number, buf)
            return True
        return False

    @property
    def allow_ask_no_ack(self):
        """Allow or disable ``ask_no_ack`` parameter to `send()` & `write()`."""
        self._features = self._reg_read(_TX_FEATURE)
        return bool(self._features & 1)

    @allow_ask_no_ack.setter
    def allow_ask_no_ack(self, enable):
        self._features = self._reg_read(_TX_FEATURE) & 6 | bool(enable)
        self._reg_write(_TX_FEATURE, self._features)

    @property
    def data_rate(self):
        """This `int` attribute specifies the RF data rate."""
        self._rf_setup = self._reg_read(_RF_PA_RATE)
        rf_setup = self._rf_setup & 0x28
        return (2 if rf_setup == 8 else 250) if rf_setup else 1

    @data_rate.setter
    def data_rate(self, speed):
        if speed not in (1, 2, 250):
            raise ValueError("data_rate must be 1 (Mbps), 2 (Mbps), or 250 (kbps)")
        speed = 0 if speed == 1 else (0x20 if speed != 2 else 8)
        self._rf_setup = self._reg_read(_RF_PA_RATE) & 0xD7 | speed
        self._reg_write(_RF_PA_RATE, self._rf_setup)

    @property
    def channel(self):
        """This `int` attribute specifies the nRF24L01's frequency."""
        return self._reg_read(_RF_CH)

    @channel.setter
    def channel(self, channel):
        if not 0 <= int(channel) <= 125:
            raise ValueError("channel must be in range [0, 125]")
        self._channel = int(channel)
        self._reg_write(_RF_CH, self._channel)

    @property
    def crc(self):
        """This `int` attribute specifies the CRC checksum length in bytes."""
        self._config = self._reg_read(_CONFIGURE)
        self._aa = self._reg_read(_AUTO_ACK)
        if self._aa:
            return 2 if self._config & 4 else 1
        return max(0, ((self._config & 0x0C) >> 2) - 1)

    @crc.setter
    def crc(self, length):
        length = min(2, abs(int(length)))
        length = (length + 1) << 2 if length else 0
        self._config = self._config & 0x73 | length
        self._reg_write(_CONFIGURE, self._config)

    @property
    def power(self):
        """This `bool` attribute controls the power state of the nRF24L01."""
        self._config = self._reg_read(_CONFIGURE)
        return bool(self._config & 2)

    @power.setter
    def power(self, is_on):
        self._config = self._reg_read(_CONFIGURE) & 0x7D | bool(is_on) << 1
        self._reg_write(_CONFIGURE, self._config)
        time.sleep(0.00015)

    @property
    def pa_level(self):
        """This `int` is the power amplifier level (in dBm)."""
        self._rf_setup = self._reg_read(_RF_PA_RATE)
        return (3 - ((self._rf_setup & 6) >> 1)) * -6

    @pa_level.setter
    def pa_level(self, power):
        lna_bit = True
        if isinstance(power, (list, tuple)) and len(power) > 1:
            lna_bit, power = bool(power[1]), int(power[0])
        if not isinstance(power, int) or power not in (-18, -12, -6, 0):
            raise ValueError("pa_level must be -18, -12, -6, or 0")  # dBm 0x00, 0x02, 0x04, 0x06
        pwr = (3 - int(power / -6)) * 2
        self._rf_setup = (self._rf_setup & 0xF8) | pwr | lna_bit
        self._reg_write(_RF_PA_RATE, self._rf_setup)

    @property
    def is_lna_enabled(self):
        """A read-only `bool` attribute about the LNA gain feature."""
        self._rf_setup = self._reg_read(_RF_PA_RATE)
        return bool(self._rf_setup & 1)

    def resend(self, send_only=False):
        """Manually re-send the first-out payload from TX FIFO buffers."""
        if self.fifo(True, True):
            return False
        self._ce(0)
        if not send_only and (self._status >> 1 & 7) < 6:  # todo deviation lite/full
            self.flush_rx()
        self.clear_status_flags()
        self._ce(1)
        while not self._status & 0x30:
            self.update()
        result = bool(self._status & 0x20)
        if result and self._status & 0x40 and not send_only:
            return self.read()
        return result

    def write(self, buf, ask_no_ack=False, write_only=False):
        """This non-blocking and helper function to `send()` can only handle
        one payload at a time."""
        if not self._dyn_pl & 1:
            buf_len = len(buf)
            pl_len = self._pl_len[0]
            if buf_len < pl_len:
                buf += b"\0" * (pl_len - buf_len)
            elif buf_len > pl_len:
                buf = buf[:pl_len]
        elif not buf or len(buf) > 32:
            raise ValueError("buffer must have a length in range [1, 32]")
        self.clear_status_flags()
        if self._status & 1:
            return False
        self._reg_write_bytes(_W_TX_PAYLOAD | (bool(ask_no_ack) << 4), buf)
        if not write_only:
            self._ce(1)
        return True

    def flush_rx(self):
        """Flush all 3 levels of the RX FIFO."""
        self._reg_write(_FLUSH_RX)

    def flush_tx(self):
        """Flush all 3 levels of the TX FIFO."""
        self._reg_write(_FLUSH_TX)

    def fifo(self, about_tx=False, check_empty=None):
        """This provides the status of the TX/RX FIFO buffers. (read-only)"""
        _fifo, about_tx = (self._reg_read(_FIFO_STATUS), bool(about_tx))
        if check_empty is None:
            return (_fifo & (0x30 if about_tx else 0x03)) >> (4 * about_tx)
        return bool(_fifo & ((2 - bool(check_empty)) << (4 * about_tx)))

    def address(self, index=1):
        """Returns the current TX address or optionally RX address. (read-only)"""
        if index > 5:
            raise IndexError("index {} is out of bounds [0,5]".format(index))
        if index < 0:
            return self._tx_address
        if index <= 1:
            return self._pipes[index]
        return bytes([self._pipes[index]]) + self._pipes[1][1:]

    @property
    def rpd(self):
        """Returns `True` if signal was detected or `False` if not. (read-only)"""
        return bool(self._reg_read(0x09))  # received power detector
