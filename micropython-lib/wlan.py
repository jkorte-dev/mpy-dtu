from secrets import *

def do_connect(ssid=secrets['ssid'],psk=secrets['password']):
    import network, ubinascii, time, os
    
    sta_if = network.WLAN(network.STA_IF)
    
    sta_if.active(False)
    sta_if.active(True)

    if not sta_if.isconnected():
        print('connecting to network...')
        #sta_if.scan()
        sta_if.active(True)
        if "LOLIN_C3_MINI" in os.uname().machine:
            sta_if.config(txpower=8.5) # wemos esp32c3 v1.0.0
        print(ubinascii.hexlify(sta_if.config('mac')).decode())
        sta_if.connect(ssid, psk)
        while not sta_if.isconnected():
            time.sleep_ms(1)
    print('network config:', sta_if.ifconfig())

def start_ap(ssid='MPY-DTU'):
    import network, os
    
    ap = network.WLAN(network.AP_IF)
    if not ap.isconnected():
        ap.active(True)
        if "LOLIN_C3_MINI" in os.uname().machine:
            ap.config(txpower=8.5) # wemos esp32c3 v1.0.0
        ap.config(ssid=ssid)
        ap.config(key='12341234123412341234')
        ap.config(security=4)
        print('started ap', ap.ifconfig())
    
#do_connect()
#import network; sta_if = network.WLAN(network.STA_IF); sta_if.active(True) 
