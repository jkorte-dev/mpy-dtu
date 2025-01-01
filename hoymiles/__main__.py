#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Hoymiles micro-inverters main application
"""

import sys
import time
import hoymiles
import logging
from logging.handlers import RotatingFileHandler

################################################################################
""" Signal Handler """  #
################################################################################
if sys.platform == 'linux':
    from signal import signal, Signals, SIGINT, SIGTERM, SIGHUP

    def signal_handler(sig_num, frame):
        signame = Signals(sig_num).name
        logging.info(f'Stop by Signal {signame} ({sig_num})')
        print(f'Stop by Signal <{signame}> ({sig_num}) at: {time.strftime("%d.%m.%Y %H:%M:%S")}')

        if mqtt_client:
            mqtt_client.disco()

        if influx_client:
            influx_client.disco()

        if volkszaehler_client:
            volkszaehler_client.disco()

        sys.exit(0)


    signal(SIGINT, signal_handler)  # Interrupt from keyboard (CTRL + C)
    signal(SIGTERM, signal_handler)  # Signal Handler from terminating processes
    signal(SIGHUP, signal_handler)  # Hangup detected on controlling terminal or death of controlling process
    # signal(SIGKILL, signal_handler)   # Signal Handler SIGKILL and SIGSTOP cannot be caught, blocked, or ignored!!


def init_logging(ahoy_config):
    log_config = ahoy_config.get('logging')
    fn = 'hoymiles.log'
    lvl = logging.ERROR
    max_log_filesize = 1000000
    max_log_files = 1
    if log_config:
        fn = log_config.get('filename', fn)
        level = log_config.get('level', 'ERROR')
        if level == 'DEBUG':
            lvl = logging.DEBUG
        elif level == 'INFO':
            lvl = logging.INFO
        elif level == 'WARNING':
            lvl = logging.WARNING
        elif level == 'ERROR':
            lvl = logging.ERROR
        elif level == 'FATAL':
            lvl = logging.FATAL
        max_log_filesize = log_config.get('max_log_filesize', max_log_filesize)
        max_log_files = log_config.get('max_log_files', max_log_files)
    if hoymiles.HOYMILES_TRANSACTION_LOGGING:
        lvl = logging.DEBUG
    logging.basicConfig(handlers=[RotatingFileHandler(fn, maxBytes=max_log_filesize, backupCount=max_log_files)],
                        format='%(asctime)s %(levelname)s: %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S.%s', level=lvl)
    dtu_name = ahoy_config.get('dtu', {}).get('name', 'hoymiles-dtu')
    logging.info(f'start logging for {dtu_name} with level: {logging.getLevelName(logging.root.level)}')


# global variables

mqtt_client = None
influx_client = None
volkszaehler_client = None

event_message_index = {}
command_queue = {}

mqtt_command_topic_subs = []  # todo used by mqtt_on_command


def status_callback(result, inverter):
    if mqtt_client:
        mqtt_client.store_status(result, topic=inverter.get('mqtt', {}).get('topic', None))

    if influx_client:
        influx_client.store_status(result)

    if volkszaehler_client:
        volkszaehler_client.store_status(result)


def info_callback(result, inverter):
    if mqtt_client:
        mqtt_client.store_status(result, topic=inverter.get('mqtt', {}).get('topic', None))


if __name__ == '__main__':
    import argparse
    import yaml
    from yaml.loader import SafeLoader

    parser = argparse.ArgumentParser(description='Ahoy - Hoymiles solar inverter gateway', prog="hoymiles")
    parser.add_argument("-c", "--config-file", nargs="?", required=True,
                        help="configuration file")
    parser.add_argument("--log-transactions", action="store_true", default=False,
                        help="Enable transaction logging output (loglevel must be DEBUG)")
    parser.add_argument("--verbose", action="store_true", default=False,
                        help="Enable detailed debug output (loglevel must be DEBUG)")
    global_config = parser.parse_args()

    # Load ahoy.yml config file
    try:
        if isinstance(global_config.config_file, str):
            with open(global_config.config_file, 'r') as fh_yaml:
                cfg = yaml.load(fh_yaml, Loader=SafeLoader)
        else:
            with open('ahoy.yml', 'r') as fh_yaml:
                cfg = yaml.load(fh_yaml, Loader=SafeLoader)
    except FileNotFoundError:
        logging.error("Could not load config file. Try --help")
        sys.exit(2)
    except yaml.YAMLError as e_yaml:
        logging.error(f'Failed to load config file {global_config.config_file}: {e_yaml}')
        sys.exit(1)

    if global_config.log_transactions:
        hoymiles.HOYMILES_TRANSACTION_LOGGING = True
    if global_config.verbose:
        hoymiles.HOYMILES_DEBUG_LOGGING = True

    # read AHOY configuration file and prepare logging
    ahoy_config = dict(cfg.get('ahoy', {}))
    init_logging(ahoy_config)

    # create MQTT - client object
    mqtt_config = ahoy_config.get('mqtt', None)
    if mqtt_config and not mqtt_config.get('disabled', False):
        from .outputs import MqttOutputPlugin

        mqtt_client = MqttOutputPlugin(mqtt_config)

    # create INFLUX - client object
    influx_config = ahoy_config.get('influxdb', None)
    if influx_config and not influx_config.get('disabled', False):
        from .outputs import InfluxOutputPlugin

        influx_client = InfluxOutputPlugin(
            influx_config.get('url'),
            influx_config.get('token'),
            org=influx_config.get('org', ''),
            bucket=influx_config.get('bucket', None),
            measurement=influx_config.get('measurement', 'hoymiles'))

    # create VOLKSZAEHLER - client object
    volkszaehler_config = ahoy_config.get('volkszaehler', {})
    if volkszaehler_config and not volkszaehler_config.get('disabled', False):
        from .outputs import VolkszaehlerOutputPlugin

        volkszaehler_client = VolkszaehlerOutputPlugin(volkszaehler_config)

    for g_inverter in ahoy_config.get('inverters', []):
        g_inverter_ser = g_inverter.get('serial')

        # Enables and subscribe inverter to mqtt /command-Topic
        if mqtt_client and g_inverter.get('mqtt', {}).get('send_raw_enabled', False):
            topic_item = (
                str(g_inverter_ser),
                g_inverter.get('mqtt', {}).get('topic', f'hoymiles/{g_inverter_ser}') + '/command'
            )
            mqtt_client.client.subscribe(topic_item[1])
            mqtt_command_topic_subs.append(topic_item)

    # start main-loop
    dtu = hoymiles.HoymilesDTU(ahoy_config,
                               mqtt_client,          # optional if no sunset support
                               event_message_index,  # pass only if need in global context
                               command_queue,        # pass only if need in global context
                               status_handler=status_callback,
                               info_handler=info_callback)
    import asyncio
    asyncio.run(dtu.start())
    # main_loop(ahoy_config)  # mqtt_client, influx_client, volkszaehler_client, event_message_index, command_queue
