from datetime import datetime, timezone, timedelta
import framebuf
from time import sleep
import time
import logging


class DisplayPlugin:
    display = None
    display_width = 128  # default
    font_size = 8     # fontsize fix 8 + 2 pixel
    symbol_size = 10  # symbols fix 10x10 pixel
    last_ip = None

    # symbols 10x10 created with https://www.piskelapp.com/ converted png with gimp to 1 bit b/w pbm files
    symbols = {'sum': bytearray(b'\x00\x00\x7f\x80`\x800\x00\x18\x00\x0c\x00\x18\x000\x00`\x80\x7f\x80'),
               'cal': bytearray(b'\x7f\x80\x7f\x80@\x80D\x80L\x80T\x80D\x80D\x80@\x80\x7f\x80'),
               'wifi': bytearray(b'\xf8\x00\x0e\x00\xe3\x009\x80\x0c\x80\xe6\xc02@\x1b@\xc9@\xc9@'),
               'level': bytearray(b'\x00\x00\x01\x80\x01\x80\x01\x80\r\x80\r\x80\r\x80m\x80m\x80m\x80'),
               'moon': bytearray(b'\x0f\x00\x1e\x00<\x00|\x00|\x00|\x00|\x00<\x00\x1e\x00\x0f\x00'),
               'blank': bytearray([0x00] * 20)}

    def __init__(self, config, **params):
        def _text_scaled(screen, text, x, y, scale, character_width=8, character_height=8):
            # temporary buffer for the text
            width = character_width * len(text)
            height = character_height
            temp_buf = bytearray(width * height)
            temp_fb = framebuf.FrameBuffer(temp_buf, width, height, framebuf.MONO_VLSB)

            # write text to the temporary framebuffer
            temp_fb.text(text, 0, 0, 1)

            # scale and write to the display
            for i in range(width):
                for j in range(height):
                    pixel = temp_fb.pixel(i, j)
                    if pixel:  # If the pixel is set, draw a larger rectangle
                        screen.fill_rect(x + i * scale, y + j * scale, scale, scale, 1)

        from machine import Pin, I2C, SPI, SoftSPI

        try:
            self.display_width = config.get('display_width', 128)
            self.display_height = config.get('display_height', 64)

            # type i2c-oled or spi-lcd
            display_type = config.get('display_type', 'i2c-oled')
            if display_type == 'i2c-oled':
                try:
                    from ssd1306 import SSD1306_I2C

                except ImportError as ex:
                    print('Install module with command: mpremote mip install ssd1306')
                    raise ex

                i2c_num = config.get('i2c_num', 0)
                scl_pin = config.get('scl_pin')  # no default
                sda_pin = config.get('sda_pin')  # no default
                if scl_pin is not None and sda_pin is not None:
                    i2c = I2C(i2c_num, scl=Pin(scl_pin), sda=Pin(sda_pin))
                else:
                    i2c = I2C(i2c_num)
                print("Display i2c", i2c)

                # extend display class
                SSD1306_I2C.text_scaled = _text_scaled
                self.display = SSD1306_I2C(self.display_width, self.display_height, i2c)
            else:
                try:
                    import ST7567 as lcd

                except ImportError as ex:
                    print('Install module ST7567.py')
                    raise ex

                spi_num = config.get('spi_num', -1)  # -1 use SoftSPI
                sck_pin = config.get('sck_pin')
                mosi_pin = config.get('mosi_pin')
                miso_pin = config.get('miso_pin')
                rst_pin = config.get('rst_pin')
                dc_pin = config.get('dc_pin')
                cs_pin = config.get('cs_pin')
                # bl_pin = config.get('bl_pin')# backlight optional
                # use is not None because otherwise pin 0 will not be true
                if sck_pin is not None and mosi_pin is not None and cs_pin is not None and dc_pin is not None:
                    if spi_num == -1:
                        spi = SoftSPI(baudrate=100000, sck=Pin(sck_pin), mosi=Pin(mosi_pin), miso=Pin(miso_pin))
                    else:
                        spi = SPI(spi_num, baudrate=4000000, sck=Pin(sck_pin), mosi=Pin(mosi_pin))
                    lcd.ST7567.text_scaled = _text_scaled
                    self.display = lcd.ST7567(spi, cs=Pin(cs_pin), a0=Pin(dc_pin), rst=Pin(rst_pin), invX=True)

            self.display.fill(0)
            fscale = 2
            try:
                import hoymiles.ulogo as ulogo
                self.display.invert(display_type == 'i2c-oled')
                ulogo.show_logo(self.display)
                self.display.text_scaled("MPY", 60, 14 - self.font_size, fscale)
                self.display.text_scaled("DTU", 60, 34 - self.font_size, fscale)
                import sys
                import gc
                del sys.modules['hoymiles.ulogo']
                del ulogo
                gc.collect()
            except ImportError:
                splash = "mpDTU"  # "Ahoy!"
                self.display.text_scaled(splash, ((self.display_width - len(splash)*self.font_size*fscale) // 2), (self.display_height // 2) - self.font_size, fscale)
            self.display.show()

        except Exception as e:
            print("display not initialized", e)

    def store_status(self, response, **params):
        data = response.to_dict() if callable(getattr(response, 'to_dict', None)) else None

        if data is None or data.get('FW_HW_ID'):  # no valid data or HardwareResponse
            print("Invalid response!")
            return

        if self.display:
            self.display.fill(0)
            self.display.invert(0)
            self.display.show()

        phase_sum_power = 0
        if data.get('phases'):
            for phase in data['phases']:
                if phase['power']:
                    phase_sum_power += phase['power']
        # self.show_value(0, f"     {phase_sum_power} W")
        self.show_value(0, f"{phase_sum_power:0.0f}W", center=True, large=True)
        self.show_symbol(0, 'level')
        self.show_symbol(0, 'wifi', x=self.display_width-self.symbol_size)
        if data.get('yield_today') is not None:
            yield_today = data['yield_today']
            self.show_value(1, f"{yield_today} Wh", x=40)  # 16+3*8
            self.show_symbol(1, "cal", x=16)
        if data.get('yield_total'):
            yield_total = round(data['yield_total'] / 1000)
            self.show_value(2, f"     {yield_total:01d} kWh")
            self.show_symbol(2, "sum", x=16)
        if data.get('time'):
            timestamp = data['time']  # datetime.isoformat()
            Y, M, D, h, m, s, us, tz, fold = timestamp.tuple()
            self.show_value(3, f' {D:02d}.{M:02d} {h:02d}:{m:02d}:{s:02d}')
        if self.last_ip:
            self.show_value(4, self.last_ip, center=True)

    def show_value(self, slot, value, x=None, y=None, center=False, large=False):
        if self.display is None:
            print(value)
            return
        x, y = self._slot_pos(slot, x, y, length=len(value) if center else None)
        if large:
            _scale = 2
            self.display.text_scaled(value, x - _scale*self.font_size, y, _scale)
        else:
            self.display.fill_rect(x, y, self.display_width, self.font_size, 0)  # clear data on display
            self.display.text(value, x, y, 1)
        self.display.show()

    def show_symbol(self, slot, sym, x=None, y=None):
        if self.display is None:
            return
        data = self.symbols.get(sym)
        if data:
            x, y = self._slot_pos(slot, x, y)
            self.display.blit(framebuf.FrameBuffer(data, self.symbol_size, self.symbol_size, framebuf.MONO_HLSB), x, y)
            self.display.show()

    def _slot_pos(self, slot, x=None, y=None, length=None):
        x = x if x else ((self.display_width - length*self.font_size) // 2) if length else 0
        y = y if y else slot * (self.display_height // 5) + 8 if slot else 0
        return x, y

    def on_event(self, event):
        evtp = event.get('event_type', "")
        if evtp == 'suntimes.sleeping':
            if self.display:
                self.display.invert(0)
            self.show_symbol(slot=1, sym='moon')
        elif evtp == "suntimes.wakeup":
            self.show_symbol(slot=1, sym='blank')
        elif evtp == "wifi.up":
            self.show_symbol(slot=0, sym='wifi', x=self.display_width-self.symbol_size)
            self.show_value(4, event.get('ip', ""), center=True)
            self.last_ip = event.get('ip', "")


class MqttPlugin:
    def __init__(self, config, **params):
        print("mqtt plugin", config)
        self.start_time = time.time()

        self.topic_root = params.get('topic', params.get('topic', 'mpy-dtu'))
        self.dry_run = config.get('dry_run', False)
        self.client = None

        try:
            from umqtt.robust import MQTTClient
        except ImportError:
            print('Install module with command: \nmpremote mip install umqtt.simple\nmpremote mip install umqtt.robust')
            return
        try:
            from machine import unique_id
            from ubinascii import hexlify
            mqtt_broker = config.get('host', '127.0.0.1')
            mqtt_client = MQTTClient(hexlify(unique_id()), mqtt_broker)
            mqtt_client.connect()
            print("connected to ", mqtt_broker)
            self.client = mqtt_client
        except OSError as e:
            print("MQTT disabled. network error?:", e)
            logging.exception(e)

    def store_status(self, response, **params):
        data = response.to_dict() if callable(getattr(response, 'to_dict', None)) else None

        if data is None:
            return

        topic = params.get('topic', None)
        if not topic:
            topic = f'{self.topic_root}/{data.get("inverter_name", "hoymiles")}'

        if data.get('FW_HW_ID'):  # HardwareInfoResponse
            self._publish(f'{topic}/hardware', f'{data["FW_HW_ID"]}')
            self._publish(f'{topic}/firmware',
                          f'v{data.get("FW_ver_maj","")}.{data.get("FW_ver_min","")}.{data.get("FW_ver_pat", "")}' +
                          f'@{data.get("FW_build_yy","")}.{data.get("FW_build_mm", "")}.{data.get("FW_build_dd", "")}T{data.get("FW_build_HH","")}:{data.get("FW_build_MM","")}')
        else:  # StatusResponse
            # Global Head
            if data.get('time'):
                self._publish(f'{topic}/time', data['time'].isoformat())

            # AC Data
            phase_id = 0
            phase_sum_power = 0
            phases_ac = data.get('phases')
            if phases_ac:
                for phase in phases_ac:
                    phase_name = f'ac/{phase_id}' if len(phases_ac) > 1 else 'ch0'
                    self._publish(f'{topic}/{phase_name}/U_AC', phase['voltage'])
                    self._publish(f'{topic}/{phase_name}/I_AC', phase['current'])
                    self._publish(f'{topic}/{phase_name}/P_AC', phase['power'])
                    self._publish(f'{topic}/{phase_name}/Q_AC', phase['reactive_power'])
                    self._publish(f'{topic}/{phase_name}/F_AC', phase['frequency'])
                    phase_id = phase_id + 1
                    phase_sum_power += phase['power']

            # DC Data
            string_id = 1
            string_sum_power = 0
            if data.get('strings'):
                for string in data['strings']:
                    string_name = f'ch{string_id}'
                    if 'name' in string:
                        s_name = string['name'].replace(" ", "_")
                        self._publish(f'{topic}/{string_name}/name', s_name)
                    self._publish(f'{topic}/{string_name}/U_DC', string['voltage'])
                    self._publish(f'{topic}/{string_name}/I_DC', string['current'])
                    self._publish(f'{topic}/{string_name}/P_DC', string['power'], )
                    self._publish(f'{topic}/{string_name}/YieldDay', string['energy_daily'])
                    self._publish(f'{topic}/{string_name}/YieldTotal', string['energy_total'] / 1000)
                    self._publish(f'{topic}/{string_name}/Irradiation', string['irradiation'])
                    string_id = string_id + 1
                    string_sum_power += string['power']

            # Global
            if data.get('temperature'):
                self._publish(f'{topic}/Temp', data['temperature'])

            # Total
            self._publish(f'{topic}/total/P_DC', string_sum_power)
            self._publish(f'{topic}/total/P_AC', phase_sum_power)
            if data.get('event_count'):
                self._publish(f'{topic}/total/total_events', data['event_count'])
            if data.get('powerfactor'):
                self._publish(f'{topic}/total/PF_AC', data['powerfactor'])
            if data.get('yield_total'):
                self._publish(f'{topic}/total/YieldTotal', data['yield_total'] / 1000)
            if data.get('yield_today'):
                self._publish(f'{topic}/total/YieldToday', data['yield_today'] / 1000)
            if data.get('efficiency'):
                self._publish(f'{topic}/total/Efficiency', data['efficiency'])

    def on_event(self, event, topic=None):
        if not event:
            return
        if not topic:
            topic = self.topic_root
        evtp = event.get('event_type', "")
        if "suntimes." in evtp:
            self._publish(f'{topic}/sunset', event.get('sunset', ""))
            self._publish(f'{topic}/sunrise', event.get('sunrise', ""))
            if evtp == 'suntimes.sleeping':
                self._publish(f'{topic}/status', 'sleeping')
            elif evtp == "suntimes.wakeup":
                self._publish(f'{topic}/status', 'awake')
        elif evtp == "wifi.up":
            self._publish(f'{topic}/ip_addr', event.get('ip', ""))
        else:
            uptime = str(timedelta(seconds=int(time.time() - self.start_time))).replace(' ', '')
            self._publish(f'{topic}/uptime', uptime)

    def _publish(self, topic, value):
        if self.dry_run or self.client is None:
            print(topic, str(value))
        else:
            self.client.publish(topic.encode(), str(value))


class BlinkPlugin:
    def __init__(self, config, **params):
        led_pin = config.get('led_pin')
        self.high_on = not config.get('inverted', False)
        self.np = None
        self.led = None
        if led_pin is None:
            print("blink disabled no led configured.")
        else:
            from machine import Pin
            self.led = Pin(led_pin, Pin.OUT)
            if config.get('neopixel', False):
                from neopixel import NeoPixel
                self.np = NeoPixel(self.led, 1)

    def store_status(self, response, **params):
        if self.led is not None:
            if self.np is not None:
                self.np[0] = (255, 0, 0)
                self.np.write()
                sleep(0.05)
                self.np[0] = (0, 0, 0)
                self.np.write()
            else:
                self.led.value(self.high_on)
                sleep(0.05)  # keep it short because it is blocking
                self.led.value(not self.high_on)  # self.led.toggle() not always supported

    def on_event(self, event):
        if self.np and 'inverter.polling' in event.get('event_type', ""):
            self.np[0] = (0, 16, 0)
            self.np.write()
            sleep(0.05)
            self.np[0] = (0, 0, 0)
            self.np.write()


class WebPlugin:
    last_response = {'time': datetime.now(timezone.utc), 'inverter_name': 'unkown', 'phases': [{}], 'strings': [{}]}
    last_event = {}

    def __init__(self, config={}, **params):
        if config:
            self.last_response['inverter_name'] = config.get('name', 'unkown')
            self.last_response['strings'] = [{'name': e.get('s_name', "panel")} for e in config.get('strings', [])]

    def store_status(self, response, **params):
        data = response.to_dict() if callable(getattr(response, 'to_dict', None)) else None
        if data and not data.get('FW_HW_ID'):  # no valid data or HardwareResponse
            self.last_response = data

    def get_data(self):
        _last = self.last_response
        _last['event'] = self.last_event
        _timestamp = _last['time']
        if isinstance(_timestamp, datetime):
            _new_ts = _timestamp.isoformat().split('.')[0]
            _last['time'] = _new_ts
        return f"{_last}".replace('\'', '\"')

    def on_event(self, event):
        if 'suntimes' in event.get('event_type', ""):
            self.last_event = event
