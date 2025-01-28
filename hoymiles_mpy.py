from ahoy_cfg import ahoy_config
from hoymiles import HoymilesDTU
import asyncio
import hoymiles.uoutputs
import gc

use_wdt = False
#ahoy_config['sunset'] = {'disabled': True}


if use_wdt:
    from machine import WDT, Timer
    watchdog_timer = WDT(timeout=60000)  # 60s
    keepalive_timer = Timer(2)


def init_network_time():
    print('init_network_time')
    import wlan
    import time
    wlan.do_connect()
    init = 10
    while init:
        try:
            import ntptime
            ntptime.settime()
            init = 0
        except OSError:
            init -= 1
            if init == 0:
                print('Failed to set ntp time')
            time.sleep(1)
    gc.collect()


def result_handler(result, inverter):
    print(result.to_dict())
    display.store_status(result)
    mqtt.store_status(result, topic=inverter.get('mqtt', {}).get('topic', None))
    blink.store_status(result)
    #print("mem_free:", gc.mem_free())
    if use_wdt:
        watchdog_timer.feed()
        keepalive_timer.deinit()


def event_dispatcher(event):
    if event is None or not isinstance(event, type({})):
        print("invalid event", event)
        return
    event_type = event.get('event_type', "")
    if event_type == "inverter.polling" and blink is not None:
        blink.on_event(event)
    elif display is not None:
        display.on_event(event)
    if use_wdt:
        if event_type == "suntimes.sleeping":
            keepalive_timer.init(mode=Timer.PERIODIC, period=2000, callback=lambda t: (print('t', end=""), watchdog_timer.feed()))
        elif event_type == "suntimes.wakeup":
            keepalive_timer.deinit()
        watchdog_timer.feed()


init_network_time()

display = hoymiles.uoutputs.DisplayPlugin(ahoy_config.get('display'), {})  # {'i2c_num': 0}
mqtt = hoymiles.uoutputs.MqttPlugin(ahoy_config.get('mqtt', {'host': 'homematic-ccu2'}))
blink = hoymiles.uoutputs.BlinkPlugin(ahoy_config.get('blink', {}))  # {'led_pin': 7, 'led_high_on': True, 'neopixel': False}

dtu = HoymilesDTU(ahoy_cfg=ahoy_config,
                  status_handler=result_handler,
                  info_handler=lambda result, inverter: print("hw_info", result, result.to_dict()),
                  event_handler=event_dispatcher)

asyncio.run(dtu.start())

