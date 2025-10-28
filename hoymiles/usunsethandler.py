import time
import asyncio


class SunsetHandler:

    def __init__(self, sunset_config, event_handler=None):
        self.suntimes = None
        self.event_handler = event_handler
        if sunset_config and not sunset_config.get('disabled', False):
            # (49.453872, 11.077298)
            latitude = sunset_config.get('latitude')
            longitude = sunset_config.get('longitude')
            try:
                from .sun_moon import RiSet
            except ImportError as e:
                print('Sunset disabled.', e)
                return
            self.suntimes = RiSet(lat=latitude, long=longitude)
            t = time.gmtime()
            print(f"gmtime: {t[2]:02}/{t[1]:02}/{t[0]:4} {t[3]:02}:{t[4]:02}:{t[5]:02} UTC, lat={latitude}, lon={longitude}")
            print(f'Todays sunset is at {self.suntimes.sunset(3)} UTC, sunrise is at {self.suntimes.sunrise(3)} UTC')
        else:
            print('Sunset disabled. See config')

    async def checkWaitForSunrise(self):
        if not self.suntimes:
            return
        time_to_sleep = 0
        hour, minutes = time.gmtime()[3:5]
        now = (hour * 60 + minutes) * 60 # unit is secs
        if self.suntimes.sunset() < now:  # after sunset
            # wait until the sun rises again. if it's already after midnight, this will be today
            self.suntimes.set_day(1)
            time_to_sleep = int(self.suntimes.sunrise() + (24*60*60 - now))
        elif self.suntimes.sunrise() > now:  # before sunrise
            time_to_sleep = int(self.suntimes.sunrise() - now)

        if time_to_sleep > 0:
            sunrise_time = self.suntimes.sunrise(3)
            sunset_time = self.suntimes.sunset(3)
            print(f'Next sunrise is at {sunrise_time} UTC, next sunset at {sunset_time} UTC')
            h, m = divmod(time_to_sleep//60, 60)
            print(f'Wake up in {h:02d} hours {m:02d} min.')
            self._send_suntimes_event('sleeping', time_to_sleep, sunrise_time, sunset_time)
            await asyncio.sleep(time_to_sleep)
            print(f'Woke up...')
            self._send_suntimes_event('wakeup', time_to_sleep, sunrise_time, sunset_time)

    def _send_suntimes_event(self, msg, st, srt, sst):
        if self.event_handler:
            self.event_handler({'event_type': f'suntimes.{msg}', 'sleeping_time': st, 'sunrise': srt, 'sunset': sst})


