from ahoy_cfg import ahoy_config
from hoymiles import HoymilesDTU
import asyncio
import hoymiles.uoutputs
import gc

use_wdt = True
# ahoy_config['sunset'] = {'disabled': True}
# ahoy_config['interval'] = 15
mqtt = None
display = None
blink = None
webdata = None


if use_wdt:
    from machine import WDT, Timer
    watchdog_timer = WDT(timeout=60000)  # 60s
    keepalive_timer = Timer(2)


def init_network_time():
    print('init_network_time')
    import wlan
    import time
    import ntptime
    ip = wlan.do_connect()
    init = 10
    while init:
        try:
            ntptime.settime()
            init = 0
        except OSError:
            init -= 1
            if init == 0:
                print('Failed to set ntp time')
            time.sleep(1)
    gc.collect()
    return ip


def result_handler(result, inverter):
    print(result.to_dict())
    if display:
        display.store_status(result)
    if webdata:
        webdata.store_status(result)
    if mqtt:
        mqtt.store_status(result, topic=inverter.get('mqtt', {}).get('topic', None))
    if blink:
        blink.store_status(result)
    # print("mem_free:", gc.mem_free())
    if use_wdt:
        watchdog_timer.feed()
        keepalive_timer.deinit()


def event_dispatcher(event):
    if event is None or not isinstance(event, type({})):
        print("invalid event", event)
        return
    event_type = event.get('event_type', "")
    if event_type == "inverter.polling":
        if blink:
            blink.on_event(event)
        if mqtt:
            mqtt.on_event(event, topic=ahoy_config.get('dtu', {}).get('name', 'mpy-dtu'))
    else:
        if display:
            display.on_event(event)
        if mqtt:
            mqtt.on_event(event, topic=ahoy_config.get('dtu', {}).get('name', 'mpy-dtu'))
        if webdata:
            webdata.on_event(event)
    if use_wdt:
        if event_type == "suntimes.sleeping":
            keepalive_timer.init(mode=Timer.PERIODIC, period=2000, callback=lambda t: (print(',', end=""), watchdog_timer.feed()))
        elif event_type == "suntimes.wakeup":
            keepalive_timer.deinit()
        watchdog_timer.feed()


ip_addr = init_network_time()

display = hoymiles.uoutputs.DisplayPlugin(ahoy_config.get('display', {}))  # {'i2c_num': 0}
mqtt = hoymiles.uoutputs.MqttPlugin(ahoy_config.get('mqtt', {'host': 'homematic-ccu2'}))
blink = hoymiles.uoutputs.BlinkPlugin(ahoy_config.get('blink', {}))  # {'led_pin': 7, 'inverted': False, 'neopixel': False}
webdata = hoymiles.uoutputs.WebPlugin(ahoy_config.get('inverters', [{}])[0])

if ip_addr:
    event_dispatcher({'event_type': 'wifi.up', 'ip': ip_addr})

gc.collect()

dtu = HoymilesDTU(ahoy_cfg=ahoy_config,
                  status_handler=result_handler,
                  info_handler=result_handler,
                  event_handler=event_dispatcher)
# info_handler=lambda result, inverter: print("hw_info", result, result.to_dict()))


async def hoymiles_dtu():
    gc.collect()
    print("mem_free:", gc.mem_free())
    print("starting dtu loop ...")
    await dtu.start()


async def webserver():
    from hoymiles.uwebserver import WebServer
    ws = WebServer(data_provider=webdata)
    gc.collect()
    print("mem_free:", gc.mem_free())
    print("starting webserver ...")
    await ws.webserver()


async def main():
    asyncio.create_task(hoymiles_dtu())
    asyncio.create_task(webserver())
    while True:
        await asyncio.sleep(1)  # keep up server

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print('Interrupted!')
except Exception as err:
    raise
finally:
    asyncio.new_event_loop()
