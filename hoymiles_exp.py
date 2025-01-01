from ahoy_cfg import ahoy_config
from hoymiles import HoymilesDTU
import hoymiles.uoutputs
import asyncio
from hoymiles.uwebserver import WebServer


#ahoy_config['nrf'] = [{'spi_num': 1, 'sck': 2, 'mosi': 4, 'miso': 3, 'cs': 5, 'ce': 6}] # esp32c3
#ahoy_config['inverters'] = []
ahoy_config['sunset'] = {'disabled': True}


def init_network_time():
    import wlan
    wlan.do_connect()
    try:
        import ntptime
        ntptime.settime()
    except OSError:
        print('failed to set ntp time')


def result_handler(result, inverter):
    print(result.to_dict())
    display.store_status(result)
    webdata.store_status(result)
    # mqtt.store_status(result)
    # blink.store_status(result)


init_network_time()

display = hoymiles.uoutputs.DisplayPlugin({'i2c_num': 0})
webdata = hoymiles.uoutputs.WebPlugin({})
# mqtt = hoymiles.uoutputs.MqttPlugin(ahoy_config.get('mqtt', {'host': 'homematic-ccu2'}))
# blink = hoymiles.uoutputs.BlinkPlugin({'led_pin': 7, 'led_high_on': True})


async def hoymiles_dtu():
    print("starting dtu loop ...")
    dtu = HoymilesDTU(ahoy_cfg=ahoy_config,
                      status_handler=result_handler,
                      info_handler=lambda result, inverter: print("hw_info", result, result.to_dict()))
    await dtu.start()


async def webserver():
    print("starting webserver ...")
    ws = WebServer(data_provider=webdata)
    await ws.webserver()


async def main():
    import gc
    gc.collect()
    asyncio.create_task(webserver())
    asyncio.create_task(hoymiles_dtu())
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
