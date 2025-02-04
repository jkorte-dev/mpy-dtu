import time
from errno import ETIMEDOUT

from machine import Pin, SPI

try:
    from nrf24 import RF24
except ImportError:
    from .nrf24_mp import RF24

from hoymiles import HOYMILES_DEBUG_LOGGING, hexify_payload

# https://github.com/nRF24/RF24/blob/3bbcce8d18b32be0b350978472b53830e3ad1285/nRF24L01.h


class HoymilesNRF:
    """Hoymiles NRF24 Interface"""
    tx_channel_id = 2
    tx_channel_list = [3, 23, 40, 61, 75]
    rx_channel_id = 0
    rx_channel_list = [3, 23, 40, 61, 75]
    rx_channel_ack = False
    rx_error = 0

    def __init__(self, **radio_config):

        # esp32s2 config:  {'spi_num', 1, 'sck': 7, 'miso': 9, 'mosi': 11}
        spi_num = radio_config.get('spi_num', 1)

        cfg_ = {'sck': radio_config.get('sck'),
                'mosi': radio_config.get('mosi'),
                'miso': radio_config.get('miso')}

        spi_cfg = {k: Pin(v) for k, v in cfg_.items() if v is not None}
        spi = SPI(spi_num, **spi_cfg) if spi_cfg else SPI(spi_num)
        csn = Pin(radio_config.get('cs', 12))
        ce = Pin(radio_config.get('ce', 16))

        print("NRF spi config", spi, csn, ce)
        self.radio = RF24(spi, csn, ce)

    def transmit(self, packet, txpower=None):
        self.next_tx_channel()

        if HOYMILES_DEBUG_LOGGING:
            print(f'Transmit {len(packet)} bytes channel {self.tx_channel}: {hexify_payload(packet)}')

        inv_esb_addr = b'\01' + packet[1:5]
        dtu_esb_addr = b'\01' + packet[5:9]

        self.radio.listen = False   # self.radio.stopListening()  # put radio in TX mode
        self.radio.data_rate = 250  # self.radio.setDataRate(RF24_250KBPS)
        self.radio.open_rx_pipe(1, dtu_esb_addr)  # self.radio.openReadingPipe(1,dtu_esb_addr)  #  open_rx_pipe(self, pipe_id, address):
        self.radio.open_tx_pipe(inv_esb_addr)     # self.radio.openWritingPipe(inv_esb_addr)  # open_tx_pipe(self, address):
        self.radio.channel = self.tx_channel      # self.radio.setChannel(self.tx_channel)
        self.radio.auto_ack = True                # self.radio.setAutoAck(True)

        #* @param delay How long to wait between each retry, in multiples of
        #* 250 us. The minimum of 0 means 250 us, and the maximum of 15 means
        #* 4000 us. The default value of 5 means 1500us (5 * 250 + 250).
        #* @param count How many retries before giving up. The default/maximum is 15.
        self.radio.ard = 1000                # retry delay 3 * 250 + 250 = 1000 µs
        self.radio.arc = 15                  # retry count 15
        # self.radio.set_auto_retries(3, 15) # self.radio.setRetries(3, 15)
        self.radio.crc = 2                   # self.radio.setCRCLength(RF24_CRC_16)  # length in bytes: 0, 1 or 2
        self.radio.dynamic_payloads = True   # self.radio.enableDynamicPayloads()

        if isinstance(txpower, int):
            self.radio.pa_level = txpower
        else:
            self.radio.pa_level = 0              # 0 db = max power

        return self.radio.write(packet)

    def receive(self, timeout=None):
        #  µs statt ns (monotonic_ns) daher 5e5 statt 5e8
        if not timeout:
            timeout = 5e5

        self.radio.channel = self.rx_channel
        self.radio.auto_ack = False         # self.radio.setAutoAck(False)
        self.radio.ard = 0                  # self.radio.setRetries(0, 0)
        self.radio.arc = 0                  # self.radio.setRetries(0, 0)
        self.radio.dynamic_payloads = True  # self.radio.enableDynamicPayloads()
        self.radio.crc = 2                  # self.radio.setCRCLength(RF24_CRC_16)
        self.radio.listen = True            # self.radio.startListening()

        received_sth = False
        # Receive: Loop
        t_end = time.ticks_us() + timeout
        while time.ticks_us() < t_end:

            #has_payload, pipe_number = self.radio.available_pipe()
            has_payload = self.radio.available()  # radio.any() returns size maybe better
            if has_payload:

                # Data in nRF24 buffer, read it
                self.rx_error = 0
                self.rx_channel_ack = True
                t_end = time.ticks_us() + timeout  # todo was fix value 5e8

                # radio.any() returns dynamicPayloadSize if dyn payload is enabled
                # size = self.radio.getDynamicPayloadSize()   # => read_register(R_RX_PL_WID)
                # we do not need to pass size. the driver determines length by calling any() see above
                payload = self.radio.read()  # payload = self.radio.read(size)
                fragment = (payload, self.rx_channel, self.tx_channel)
                # fragment = InverterPacketFragment(payload=payload,ch_rx=self.rx_channel, ch_tx=self.tx_channel)
                received_sth = True
                yield fragment

            else:

                # No data in nRF rx buffer, search and wait
                # Channel lock in (not currently used)
                self.rx_error = self.rx_error + 1
                if self.rx_error > 1:
                    self.rx_channel_ack = False
                # Channel hopping
                if self.next_rx_channel():
                    self.radio.listen = False              # self.radio.stopListening()
                    self.radio.channel = self.rx_channel   # self.radio.setChannel(self.rx_channel)
                    self.radio.listen = True               # self.radio.startListening()

            time.sleep(0.005)  # todo use async

        if not received_sth:
            raise OSError(ETIMEDOUT)  # was TimeoutError

    def next_rx_channel(self):
        if not self.rx_channel_ack:
            self.rx_channel_id = self.rx_channel_id + 1
            if self.rx_channel_id >= len(self.rx_channel_list):
                self.rx_channel_id = 0
            return True
        return False

    def next_tx_channel(self):
        self.tx_channel_id = self.tx_channel_id + 1
        if self.tx_channel_id >= len(self.tx_channel_list):
            self.tx_channel_id = 0

    @property
    def tx_channel(self):
        return self.tx_channel_list[self.tx_channel_id]

    @property
    def rx_channel(self):
        return self.rx_channel_list[self.rx_channel_id]

    def __del__(self):
        self.radio.power = False  # self.radio.powerDown()
