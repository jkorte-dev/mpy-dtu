import logging
import time
import requests
import asyncio


class SunsetHandler:

    def __init__(self, sunset_config, mqtt_client=None):
        self.suntimes_sunset = None
        self.suntimes_sunrise = None

        if sunset_config and not sunset_config.get('disabled', True):
            # (49.453872, 11.077298)
            self.latitude = sunset_config.get('latitude')
            self.longitude = sunset_config.get('longitude')
            self.altitude = sunset_config.get('altitude')
            self._calc_sunrise_sunset()

            print(f'gmtime()={time.gmtime()[0:5]} UTC, localtime(){time.localtime()[3:5]} lat={self.latitude}, lon={self.longitude}')
            if self.suntimes_sunset is None or self.suntimes_sunrise is None:
                print("Failed to retrieve sunset / sunrise from https://api.sunrisesunset.io")
            else:
                hour, minutes = divmod(self.suntimes_sunset,  60)  # sunset in minutes
                print(f'Todays sunset is at {hour:02d}:{minutes:02d} UTC, sunrise is at {self.suntimes_sunrise//60}:{self.suntimes_sunrise%60:02d} UTC')
        else:
            logging.info('Sunset disabled.')

    async def checkWaitForSunrise(self):
        if not self.suntimes_sunset or not self.suntimes_sunrise:
            return
        # if the sunset already happened for today
        time_to_sleep = 0
        hour, minutes = time.gmtime()[3:5]
        now = hour * 60 + minutes
        if self.suntimes_sunset < now:  # after sunset
            # wait until the sun rises again. if it's already after midnight, this will be today
            self._calc_sunrise_sunset(tomorrow=True)
            time_to_sleep = int(self.suntimes_sunrise + (24*60 - now)) * 60
        elif self.suntimes_sunrise > now:  # before sunrise
            time_to_sleep = int(self.suntimes_sunrise - now) * 60

        if time_to_sleep > 0:
            print(f'Next sunrise is at {self.suntimes_sunrise//60:02d}:{self.suntimes_sunrise%60:02d} UTC, next sunset is at {self.suntimes_sunset//60:02d}:{self.suntimes_sunset%60:02d} UTC, sleeping for {time_to_sleep} seconds.')
            print(f'Wake up in {time_to_sleep//3600:02d} hours {(time_to_sleep//60)%60:02d} min.')
            await asyncio.sleep(time_to_sleep)
            logging.info(f'Woke up...')

    def _calc_sunrise_sunset(self, tomorrow=False):
        # resp = requests.get('https://api.sunrisesunset.io/json?lat=49.453872&lng=11.077298&timezone=UTC')
        # https://api.sunrisesunset.io/json?lat=49.453872&lng=11.077298&timezone=UTC&date=tomorrow
        # {"results":{"date":"2024-12-02","sunrise":"6:53:12 AM","sunset":"3:20:11 PM","first_light":"4:57:26 AM","last_light":"5:15:57 PM","dawn":"6:16:15 AM","dusk":"3:57:08 PM","solar_noon":"11:06:41 AM","golden_hour":"2:25:49 PM","day_length":"8:26:59","timezone":"UTC","utc_offset":0},"status":"OK"}
        try:
            url = f'https://api.sunrisesunset.io/json?lat={self.latitude}&lng={self.longitude}&timezone=UTC&time_format=24'
            if tomorrow:
                url += '&date=tomorrow'
            resp = requests.get(url)
            data = resp.json().get('results')
            sr_h, sr_m = data.get('sunrise').split(':')[:2]
            self.suntimes_sunrise = int(sr_h)*60 + int(sr_m)
            ss_h, ss_m = data.get('sunset').split(':')[:2]
            self.suntimes_sunset = int(ss_h)*60 + int(ss_m)
        except Exception as e:
            logging.exception(e)





