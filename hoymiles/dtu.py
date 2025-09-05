#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Hoymiles micro-inverters python shared code
"""
import sys
import time
import asyncio
import struct
import logging
from datetime import datetime, timezone

from hoymiles import HOYMILES_DEBUG_LOGGING, HOYMILES_TRANSACTION_LOGGING, hexify_payload

import decoders
from hoymiles.decoders import ResponseDecoder, f_crc8, f_crc_m  # todo move f_crc_m , f_crc8 to global

if sys.implementation.name != "micropython":
    def const(x): return x


def ser_to_hm_addr(inverter_ser):
    """
    Calculate the 4 bytes that the HM devices use in their internal messages to
    address each other.

    :param str inverter_ser: inverter serial
    :return: inverter address
    :rtype: bytes
    """
    bcd = int(str(inverter_ser)[-8:], 16)  # jk base keyword not support in micropython
    return struct.pack('>L', bcd)


def ser_to_esb_addr(inverter_ser):
    """
    Convert a Hoymiles inverter/DTU serial number into its
    corresponding NRF24 'enhanced shockburst' address byte sequence (5 bytes).

    The NRF library expects these in LSB to MSB order, even though the transceiver
    itself will then output them in MSB-to-LSB order over the air.

    The inverters use a BCD representation of the last 8
    digits of their serial number, in reverse byte order,
    followed by \x01.

    :param str inverter_ser: inverter serial
    :return: ESB inverter address
    :rtype: bytes
    """
    air_order = ser_to_hm_addr(inverter_ser)[::-1] + b'\x01'
    return air_order[::-1]


class HMBufferError(Exception):
    """A specific buffer exceptions for exception handling."""


class InverterPacketFragment:
    """ESB Frame"""
    def __init__(self, time_rx=None, payload=None, ch_rx=None, ch_tx=None):
        """
        Callback: get's invoked whenever a Nordic ESB packet has been received.

        :param time_rx: datetime when frame was received
        :type time_rx: datetime
        :param payload: payload bytes
        :type payload: bytes
        :param ch_rx: channel where packet was received
        :type ch_rx: int
        :param ch_tx: channel where request was sent
        :type ch_tx: int

        :raises BufferError: when data gets lost on SPI bus
        """

        if not time_rx:
            time_rx = datetime.now(timezone.utc)
        self.time_rx = time_rx

        self.frame = payload

        # check crc8
        if f_crc8(payload[:-1]) != payload[-1]:
            raise HMBufferError('Frame corrupted - crc8 check failed')  # jk BufferError not supported in micropython

        self.ch_rx = ch_rx
        self.ch_tx = ch_tx

    @property
    def mid(self):
        """Transaction counter"""
        return self.frame[0]

    @property
    def src(self):
        """
        Sender adddress

        :return: sender address
        :rtype: int
        """
        src = struct.unpack('>L', self.frame[1:5])
        return src[0]
    @property
    def dst(self):
        """
        Receiver adddress

        :return: receiver address
        :rtype: int
        """
        dst = struct.unpack('>L', self.frame[5:8])
        return dst[0]
    @property
    def seq(self):
        """
        Framne sequence number

        :return: sequence number
        :rtype: int
        """
        result = struct.unpack('>B', self.frame[9:10])
        return result[0]
    @property
    def data(self):
        """
        Data without protocol framing

        :return: payload chunk
        :rtype: bytes
        """
        return self.frame[10:-1]

    def __str__(self):
        """
        Represent received ESB frame

        :return: log line received frame
        :rtype: str
        """
        size = len(self.frame)
        channel = f' channel {self.ch_rx}' if self.ch_rx else ''
        return f"Received {size} bytes{channel}: {hexify_payload(self.frame)}"


def compose_esb_fragment(fragment, seq=b'\x80', src=99999999, dst=1):
    """
    Build standart ESB request fragment

    :param bytes fragment: up to 16 bytes payload chunk
    :param seq: frame sequence byte
    :type seq: bytes
    :param src: dtu address
    :type src: int
    :param dst: inverter address
    :type dst: int
    :return: esb frame fragment
    :rtype: bytes
    :raises ValueError: if fragment size larger 16 byte
    """
    if len(fragment) > 17:
        raise ValueError(f'ESB fragment exceeds mtu: Fragment size {len(fragment)} bytes')

    packet = b'\x15'
    packet = packet + ser_to_hm_addr(dst)
    packet = packet + ser_to_hm_addr(src)
    packet = packet + seq

    packet = packet + fragment

    crc8 = f_crc8(packet)
    packet = packet + struct.pack('B', crc8)

    return packet


def compose_esb_packet(packet, seq, src, dst, mtu=17):  #
    """
    Build ESB packet, chunk packet

    :param bytes packet: payload data
    :param seq: frame sequence byte
    :type seq: bytes
    :param src: dtu address
    :type src: int
    :param dst: inverter address
    :type dst: int
    :param mtu: maximum transmission unit per frame (default: 17)
    :type mtu: int
    :yields: fragment
    """
    for i in range(0, len(packet), mtu):
        fragment = compose_esb_fragment(packet[i:i+mtu], seq, src, dst)
        yield fragment


def compose_send_time_payload(cmd_id, alarm_id=0):
    """
    Build set time request packet

    :param alarm_id:
    :param cmd_id to request
    :type cmd_id: uint8
    :return: payload
    :rtype: bytes
    """
    timestamp = int(time.time())

    # indices from esp8266 hmRadio.h / sendTimePacket()
    payload = struct.pack('>B', cmd_id)                # 10
    payload = payload + b'\x00'                       # 11
    payload = payload + struct.pack('>L', timestamp)  # 12..15 big-endian: msb at low address
    payload = payload + b'\x00\x00'                   # 16..17
    payload = payload + struct.pack('>H', alarm_id)   # 18..19
    payload = payload + b'\x00\x00\x00\x00'           # 20..23

    # append Modbus CRC16
    payload = payload + struct.pack('>H', f_crc_m(payload))
    return payload


class InverterTransaction:
    """
    Inverter transaction buffer, implements transport-layer functions while
    communicating with Hoymiles inverters
    """
    tx_queue = []
    scratch = []
    inverter_ser = None
    inverter_addr = None
    dtu_ser = None
    req_type = None
    time_rx = None

    radio = None
    txpower = None

    def __init__(self,
            request_time=None,
            inverter_ser=None,
            dtu_ser=None,
            radio=None,
            **params):
        """
        :param request: Transmit ESB packet
        :type request: bytes
        :param request_time: datetime of transmission
        :type request_time: datetime
        :param inverter_ser: inverter serial
        :type inverter_ser: str
        :param dtu_ser: DTU serial
        :type dtu_ser: str
        :param radio: HoymilesNRF instance to use
        :type radio: hoymiles.radio.HoymilesNRF or hoymiles.uradio.HoymilesNRF or None
        """

        if radio:
            self.radio = radio

            if 'txpower' in params:
                self.txpower = params['txpower']

        if not request_time:
            request_time = datetime.now(timezone.utc)

        self.scratch = []
        if 'scratch' in params:
            self.scratch = params['scratch']

        self.inverter_ser = inverter_ser
        if inverter_ser:
            self.inverter_addr = ser_to_hm_addr(inverter_ser)

        self.dtu_ser = dtu_ser
        if dtu_ser:
            self.dtu_addr = ser_to_hm_addr(dtu_ser)

        self.request = None
        if 'request' in params:
            self.request = params['request']
            self.queue_tx(self.request)
            self.inverter_addr, self.dtu_addr, seq, self.req_type = struct.unpack('>LLBB', params['request'][1:11])
        self.request_time = request_time

    def rxtx(self):
        """
        Transmit next packet from tx_queue if available
        and wait for responses

        :return: if we got contact
        :rtype: bool
        """
        if not self.radio:
            return False

        if len(self.tx_queue) == 0:
            return False

        packet = self.tx_queue.pop(0)

        self.radio.transmit(packet, txpower=self.txpower)

        wait = False
        try:
            for (payload, rx_channel, tx_channel) in self.radio.receive():
                response = InverterPacketFragment(
                        payload=payload,
                        ch_rx=rx_channel, ch_tx=tx_channel,
                        time_rx=datetime.now(timezone.utc)
                        )
                if HOYMILES_TRANSACTION_LOGGING:
                    logging.debug(response)

                self.frame_append(response)
                wait = True
        except OSError:  # jk was TimeoutError now OSError(ETIMEDOUT) thrown from module
            pass
        except HMBufferError as e:  # jk BufferError not supported
            logging.warning(f'Buffer error {e}')
            pass
        except Exception as e:  # jk new block
            logging.warning(f'Exception {e}')
            pass

        return wait

    def frame_append(self, frame):
        """
        Append received raw frame to local scratch buffer

        :param bytes frame: Received ESB frame
        :return None
        """
        self.scratch.append(frame)

    def queue_tx(self, frame):
        """
        Enqueue packet for transmission if radio is available

        :param bytes frame: ESB frame for transmit
        :return: if radio is available and frame scheduled
        :rtype: bool
        """
        if not self.radio:
            return False

        self.tx_queue.append(frame)

        return True

    def get_payload(self, src=None):
        """
        Reconstruct Hoymiles payload from scratch buffer

        :param src: filter frames by inverter hm_address (default self.inverter_address)
        :type src: bytes
        :return: payload
        :rtype: bytes
        :raises BufferError: if one or more frames are missing
        :raises ValueError: if assembled payload fails CRC check
        """

        if not src:
            src = self.inverter_addr

        # Collect all frames from source_address src
        frames = [frame for frame in self.scratch if frame.src == src]

        tr_len = 0
        # Find end frame and extract message frame count
        try:
            end_frame = next(frame for frame in frames if frame.seq > 0x80)
            self.time_rx = end_frame.time_rx
            tr_len = end_frame.seq - 0x80
        except StopIteration:
            seq_last = max(frames, key=lambda frame:frame.seq).seq if len(frames) else 0
            self.__retransmit_frame(seq_last + 1)
            raise HMBufferError(f'Missing packet: Last packet {seq_last + 1}')   # jk BufferError not supported

        # Rebuild payload from unordered frames
        payload = b''
        for frame_id in range(1, tr_len):
            try:
                data_frame = next(item for item in frames if item.seq == frame_id)
                payload = payload + data_frame.data
            except StopIteration:
                self.__retransmit_frame(frame_id)
                raise HMBufferError(f'Frame {frame_id} missing: Request Retransmit')  # jk BufferError not supported

        payload = payload + end_frame.data

        # check crc
        pcrc = struct.unpack('>H', payload[-2:])[0]
        if f_crc_m(payload[:-2]) != pcrc:
            raise ValueError('Payload failed CRC check.')

        return payload

    def __retransmit_frame(self, frame_id):
        """
        Build and queue retransmit request

        :param int frame_id: frame id to re-schedule
        :return: if successful scheduled
        :rtype: bool
        """

        if not self.radio:
            return

        packet = compose_esb_fragment(b'',
                                      seq=int(0x80 + frame_id).to_bytes(1, 'big'),
                                      src=self.dtu_ser,
                                      dst=self.inverter_ser)

        return self.queue_tx(packet)

    def __str__(self):
        """
        Represent transmit payload

        :return: log line of payload for transmission
        :rtype: str
        """
        return f'Transmit | {hexify_payload(self.request)}'


InverterDevInform_Simple = const(0)  # 0x00
InverterDevInform_All = const(1)  # 0x01
# GridOnProFilePara = 2  # 0x02
# HardWareConfig = 3  # 0x03
# SimpleCalibrationPara = 4  # 0x04
SystemConfigPara = const(5)  # 0x05
RealTimeRunData_Debug = const(11)  # 0x0b
# RealTimeRunData_Reality = 12  # 0x0c
# RealTimeRunData_A_Phase = 13  # 0x0d
# RealTimeRunData_B_Phase = 14  # 0x0e
# RealTimeRunData_C_Phase = 15  # 0x0f
AlarmData = const(17)  # 0x11, Alarm data - all unsent alarms
# AlarmUpdate = 18  # 0x12, Alarm data - all pending alarms
# RecordData = 19  # 0x13
# InternalData = 20  # 0x14
# GetLossRate = 21  # 0x15
# GetSelfCheckState = 30  # 0x1e
# InitDataState = 0xff


class HoymilesDTU:
    def __init__(self, ahoy_cfg, mqtt_clt=None, event_msg_idx=None, cmd_queue=None, status_handler=None, info_handler=None, event_handler=None):
        if cmd_queue is None:
            cmd_queue = {}
        if event_msg_idx is None:
            event_msg_idx = {}
        self.ahoy_config = ahoy_cfg
        self.mqtt_client = mqtt_clt
        self.event_message_index = event_msg_idx
        self.command_queue = cmd_queue
        self.status_handler = status_handler
        self.info_handler = info_handler
        self.event_handler = event_handler
        if not event_handler:
            self.event_handler = lambda event: None
        self.hmradio = None
        if ahoy_cfg.get('nrf') is not None:
            if sys.platform == 'linux':
                from .radio import HoymilesNRF
            else:
                from .uradio import HoymilesNRF
                print("importing HoymilesNRF micropython version")
            for radio_config in ahoy_cfg.get('nrf', [{}]):
                self.hmradio = HoymilesNRF(**radio_config)  # hmm wird jedesmal ueberschrieben

        self.inverters = [
            inverter for inverter in ahoy_cfg.get('inverters', [])
            if not inverter.get('disabled', False)]

        self.dtu_ser = ahoy_cfg.get('dtu', {}).get('serial', None)
        self.dtu_name = ahoy_cfg.get('dtu', {}).get('name', 'hoymiles-dtu')

        self.sunset = None
        sunset_cfg = ahoy_cfg.get('sunset')
        if sunset_cfg and self.mqtt_client and sys.platform == 'linux':
            from hoymiles.sunsethandler import SunsetHandler
            self.sunset = SunsetHandler(sunset_cfg, self.mqtt_client)
            self.sunset.sun_status2mqtt(self.dtu_ser, self.dtu_name)
        elif sunset_cfg and not sys.platform == 'linux':
            # float precision is not sufficient to cal sunset/sunrise we use web api instead
            from hoymiles.websunsethandler import SunsetHandler
            self.sunset = SunsetHandler(sunset_cfg, self.event_handler)

        self.loop_interval = ahoy_cfg.get('interval', 2)
        self.transmit_retries = ahoy_cfg.get('transmit_retries', 5)
        if self.transmit_retries <= 0:
            logging.critical('Parameter "transmit_retries" must be >0 - please check ahoy.yml.')
            # print message to console too
            print('Parameter "transmit_retries" must be >0 - please check ahoy.yml - STOP(0)x')
            sys.exit(0)

    async def start(self):
        try:
            do_init = True
            while True:

                if self.sunset:
                    await self.sunset.checkWaitForSunrise()

                t_loop_start = time.time()

                for inverter in self.inverters:
                    if 'name' not in inverter:
                        inverter['name'] = 'hoymiles'
                    if 'serial' not in inverter:
                        logging.error("No inverter serial number found in ahoy.yml - exit")
                        sys.exit(999)
                    if HOYMILES_DEBUG_LOGGING:
                        logging.info(f'Poll inverter name={inverter["name"]} ser={inverter["serial"]}')
                    try:
                        self.event_handler({'event_type': 'inverter.polling'})
                        await asyncio.wait_for(self.poll_inverter(inverter, do_init), timeout=self.transmit_retries+5)
                    except asyncio.TimeoutError as e:
                        print("t", end="")
                        # self.event_handler({'event_type': 'inverter.timeout'})
                do_init = False

                if self.loop_interval > 0:
                    time_to_sleep = self.loop_interval - (time.time() - t_loop_start)
                    if time_to_sleep > 0:
                        await asyncio.sleep(time_to_sleep)
                await asyncio.sleep(0.1)  # 0.1 ok ohne inverter

        except Exception as e:
            logging.error('Exception catched: %s' % e)
            #logging.fatal(traceback.print_exc())
            raise e

    async def poll_inverter(self, inverter, do_init):
        """
        Send/Receive command_queue, initiate status poll on inverter
        """
        inverter_ser = inverter.get('serial')
        inverter_name = inverter.get('name')
        inverter_strings = inverter.get('strings')
        tx_power = inverter.get('txpower', None)

        # Queue at least status data request
        inv_str = str(inverter_ser)
        # print(f"polling inverter {inverter_name}", end="")
        print("p", end="")  # todo remove debug
        if do_init:
            if not self.command_queue.get(inv_str):
                self.command_queue[inv_str] = []       # initialize map for inverter
                self.event_message_index[inv_str] = 0  # initialize map for inverter
            self.command_queue[inv_str].append(compose_send_time_payload(InverterDevInform_All))
            # self.command_queue[inv_str].append(compose_send_time_payload(SystemConfigPara))
        self.command_queue[inv_str].append(compose_send_time_payload(RealTimeRunData_Debug))

        # Put all queued commands for current inverter on air
        while len(self.command_queue[inv_str]) > 0:
            payload = self.command_queue[inv_str].pop(0)  # Sub.Cmd
            print("q", end="")  # todo remove debug

            # Send payload {ttl}-times until we get at least one reponse
            payload_ttl = self.transmit_retries
            response = None
            while payload_ttl > 0:
                payload_ttl = payload_ttl - 1
                com = InverterTransaction(
                    radio=self.hmradio,
                    txpower=tx_power,
                    dtu_ser=self.dtu_ser,
                    inverter_ser=inverter_ser,
                    request=next(compose_esb_packet(payload, seq=b'\x80', src=self.dtu_ser, dst=inverter_ser))
                )
                while com.rxtx():
                    try:
                        response = com.get_payload()
                        payload_ttl = 0
                    except Exception as e_all:
                        if HOYMILES_TRANSACTION_LOGGING:
                            logging.error(f'Error while retrieving data: {e_all}')
                        pass
                    await asyncio.sleep(0.001)
                await asyncio.sleep(0.1)
                print(".", end="")  # todo remove debug

            # Handle the response data if any
            if response:
                print("")  # todo remove debug
                if HOYMILES_TRANSACTION_LOGGING:
                    logging.debug(f'Payload: ' + hexify_payload(response))

                # prepare decoder object
                decoder = ResponseDecoder(response,
                                          request=com.request,
                                          inverter_ser=inverter_ser,
                                          inverter_name=inverter_name,
                                          dtu_ser=self.dtu_ser,
                                          strings=inverter_strings
                                          )

                # get decoder object
                result = decoder.decode()
                if HOYMILES_DEBUG_LOGGING:
                    logging.info(f'Decoded: {result.to_dict()}')

                # check decoder object for output
                if isinstance(result, decoders.StatusResponse):

                    data = result.to_dict()
                    if data is not None and 'event_count' in data:
                        event_count = data['event_count']
                        if self.event_message_index[inv_str] < event_count:
                            self.event_message_index[inv_str] = event_count
                            self.command_queue[inv_str].append(compose_send_time_payload(AlarmData,
                                                                                         alarm_id=event_count))

                    if self.status_handler:
                        # is generator function (coroutine)?
                        if isinstance(self.status_handler, type((lambda: (yield)))):
                            try:
                                await asyncio.wait_for(self.status_handler(result, inverter), timeout=2)
                            except asyncio.TimeoutError:
                                pass
                        else:
                            self.status_handler(result, inverter)

                # check decoder object for output
                if isinstance(result, decoders.HardwareInfoResponse):
                    if self.info_handler:
                        self.info_handler(result, inverter)
