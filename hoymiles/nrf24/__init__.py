import logging
import time
from datetime import datetime
from os import environ

from hoymiles import HOYMILES_DEBUG_LOGGING, hexify_payload

try:
    # OSI Layer 2 driver for nRF24L01 on Arduino & Raspberry Pi/Linux Devices
    # https://github.com/nRF24/RF24.git
    from RF24 import RF24, RF24_PA_MIN, RF24_PA_LOW, RF24_PA_HIGH, RF24_PA_MAX, RF24_250KBPS, RF24_CRC_DISABLED, RF24_CRC_8, RF24_CRC_16
    if environ.get('TERM') is not None:
        print('Using python Module: RF24')
except ModuleNotFoundError as e:
    if environ.get('TERM') is not None:
        print(f'{e} - try to use module: RF24')
    try:
        # Repo for pyRF24 package
        # https://github.com/nRF24/pyRF24.git
        from pyrf24 import RF24, RF24_PA_MIN, RF24_PA_LOW, RF24_PA_HIGH, RF24_PA_MAX, RF24_250KBPS, RF24_CRC_DISABLED, RF24_CRC_8, RF24_CRC_16
        if environ.get('TERM') is not None:
            print(f'{e} - Using python Module: pyrf24')
    except ModuleNotFoundError as e:
        if environ.get('TERM') is not None:
            print(f'{e} - exit')
        exit()


class HoymilesNRF:
    """Hoymiles NRF24 Interface"""
    tx_channel_id = 2
    tx_channel_list = [3, 23, 40, 61, 75]
    rx_channel_id = 0
    rx_channel_list = [3, 23, 40, 61, 75]
    rx_channel_ack = False
    rx_error = 0
    txpower = 'max'

    def __init__(self, **radio_config):
        """
        Claim radio device

        :param NRF24 device: instance of NRF24
        """
        radio = RF24(
                radio_config.get('ce_pin', 22),
                radio_config.get('cs_pin', 0),
                radio_config.get('spispeed', 1000000))

        if not radio.begin():
            raise RuntimeError('Can\'t open radio')

        if not radio.isChipConnected():
            logging.warning("could not connect to NRF24 radio")

        self.txpower = radio_config.get('txpower', 'max')

        self.radio = radio

    def transmit(self, packet, txpower=None):
        """
        Transmit Packet

        :param bytes packet: buffer to send
        :return: if ACK received of ACK disabled
        :rtype: bool
        """

        self.next_tx_channel()

        if HOYMILES_DEBUG_LOGGING:
            c_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            logging.debug(f'{c_datetime} Transmit {len(packet)} bytes channel {self.tx_channel}: {hexify_payload(packet)}')

        if not txpower:
            txpower = self.txpower

        inv_esb_addr = b'\01' + packet[1:5]
        dtu_esb_addr = b'\01' + packet[5:9]

        self.radio.stopListening()  # put radio in TX mode
        self.radio.setDataRate(RF24_250KBPS)
        self.radio.openReadingPipe(1,dtu_esb_addr)
        self.radio.openWritingPipe(inv_esb_addr)
        self.radio.setChannel(self.tx_channel)
        self.radio.setAutoAck(True)
        self.radio.setRetries(3, 15)
        self.radio.setCRCLength(RF24_CRC_16)
        self.radio.enableDynamicPayloads()

        if txpower == 'min':
            self.radio.setPALevel(RF24_PA_MIN)
        elif txpower == 'low':
            self.radio.setPALevel(RF24_PA_LOW)
        elif txpower == 'high':
            self.radio.setPALevel(RF24_PA_HIGH)
        else:
            self.radio.setPALevel(RF24_PA_MAX)

        return self.radio.write(packet)

    def receive(self, timeout=None):
        """
        Receive Packets

        :param timeout: receive timeout in nanoseconds (default: 5e8)
        :type timeout: int
        :yields: fragment
        """

        if not timeout:
            timeout=5e8

        self.radio.setChannel(self.rx_channel)
        self.radio.setAutoAck(False)
        self.radio.setRetries(0, 0)
        self.radio.enableDynamicPayloads()
        self.radio.setCRCLength(RF24_CRC_16)
        self.radio.startListening()

        fragments = []
        received_sth=False
        # Receive: Loop
        t_end = time.monotonic_ns()+timeout
        while time.monotonic_ns() < t_end:

            has_payload, pipe_number = self.radio.available_pipe()
            if has_payload:

                # Data in nRF24 buffer, read it
                self.rx_error = 0
                self.rx_channel_ack = True
                t_end = time.monotonic_ns()+5e8

                size = self.radio.getDynamicPayloadSize()
                payload = self.radio.read(size)
                #fragment = InverterPacketFragment(
                #        payload=payload,
                #        ch_rx=self.rx_channel, ch_tx=self.tx_channel,
                #        time_rx=datetime.now()
                #        )
                fragment = (payload, self.rx_channel, self.tx_channel)
                received_sth=True
                yield fragment

            else:

                # No data in nRF rx buffer, search and wait
                # Channel lock in (not currently used)
                self.rx_error = self.rx_error + 1
                if self.rx_error > 1:
                    self.rx_channel_ack = False
                # Channel hopping
                if self.next_rx_channel():
                    self.radio.stopListening()
                    self.radio.setChannel(self.rx_channel)
                    self.radio.startListening()

            time.sleep(0.005)

        if not received_sth:
            raise TimeoutError

    def next_rx_channel(self):
        """
        Select next channel from hop list
        - if hopping enabled
        - if channel has no ack

        :return: if new channel selected
        :rtype: bool
        """
        if not self.rx_channel_ack:
            self.rx_channel_id = self.rx_channel_id + 1
            if self.rx_channel_id >= len(self.rx_channel_list):
                self.rx_channel_id = 0
            return True
        return False

    def next_tx_channel(self):
        """
        Select next channel from hop list

        """
        self.tx_channel_id = self.tx_channel_id + 1
        if self.tx_channel_id >= len(self.tx_channel_list):
            self.tx_channel_id = 0

    @property
    def tx_channel(self):
        """
        Get current tx channel

        :return: tx_channel
        :rtype: int
        """
        return self.tx_channel_list[self.tx_channel_id]

    @property
    def rx_channel(self):
        """
        Get current rx channel

        :return: rx_channel
        :rtype: int
        """
        return self.rx_channel_list[self.rx_channel_id]

    def __del__(self):
        self.radio.powerDown()
