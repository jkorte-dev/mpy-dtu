from secrets import *


def do_connect(ssid=secrets['ssid'], psk=secrets['password']):
    import network, ubinascii, time
    
    sta_if = network.WLAN(network.STA_IF)
    
    sta_if.active(False)
    sta_if.active(True)

    if not sta_if.isconnected():
        print('connecting to network...')
        sta_if.config(txpower=8.5)  # wemos esp32c3 v1.0.0 and esp32c6
        #sta_if.scan()
        print(ubinascii.hexlify(sta_if.config('mac'), ':').decode())
        sta_if.connect(ssid, psk)
        while not sta_if.isconnected():
            time.sleep_ms(1)
    print('network config:', sta_if.ifconfig())
    return sta_if.ifconfig()[0]


def start_ap(ssid='MPY-DTU'):
    import network
    
    ap = network.WLAN(network.AP_IF)
    if not ap.isconnected():
        ap.active(True)
        ap.config(txpower=8.5)  # wemos esp32c3 v1.0.0 and esp32c6
        ap.config(ssid=ssid)
        ap.config(key='12341234123412341234')
        ap.config(security=4)
        print('started ap', ap.ifconfig())
        return ap.ifconfig()[0]
    
#do_connect()
#import network; sta_if = network.WLAN(network.STA_IF); sta_if.active(True) 
