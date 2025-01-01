import logging
import time
import asyncio
from datetime import datetime, timedelta


class SunsetHandler:

    def __init__(self, sunset_config, mqtt_client):
        self.suntimes = None
        self.mqtt_client = mqtt_client
        try:
            from suntimes import SunTimes
        except ModuleNotFoundError as e:
            logging.info('Sunset disabled.')
            return
        if sunset_config and sunset_config.get('disabled', True) == False:
            latitude = sunset_config.get('latitude')
            longitude = sunset_config.get('longitude')
            altitude = sunset_config.get('altitude')
            self.suntimes = SunTimes(longitude=longitude, latitude=latitude, altitude=altitude)
            self.nextSunset = self.suntimes.setutc(datetime.utcnow())
            logging.info(f'Todays sunset is at {self.nextSunset} UTC')
        else:
            logging.info('Sunset disabled.')

    async def checkWaitForSunrise(self):
        if not self.suntimes:
            return
        # if the sunset already happened for today
        now = datetime.utcnow()
        if self.nextSunset < now:
            # wait until the sun rises again. if it's already after midnight, this will be today
            nextSunrise = self.suntimes.riseutc(now)
            if nextSunrise < now:
                tomorrow = now + timedelta(days=1)
                nextSunrise = self.suntimes.riseutc(tomorrow)
            self.nextSunset = self.suntimes.setutc(nextSunrise)
            time_to_sleep = int((nextSunrise - datetime.utcnow()).total_seconds())
            logging.info(
                f'Next sunrise is at {nextSunrise} UTC, next sunset is at {self.nextSunset} UTC, sleeping for {time_to_sleep} seconds.')
            if time_to_sleep > 0:
                await asyncio.sleep(time_to_sleep)
                logging.info(f'Woke up...')

    def sun_status2mqtt(self, dtu_ser, dtu_name):
        if not self.mqtt_client or not self.suntimes:
            return

        if self.suntimes:
            local_sunrise = self.suntimes.riselocal(datetime.now()).strftime("%d.%m.%YT%H:%M")
            local_sunset = self.suntimes.setlocal(datetime.now()).strftime("%d.%m.%YT%H:%M")
            local_zone = self.suntimes.setlocal(datetime.now()).tzinfo.key
            self.mqtt_client.info2mqtt({'topic': f'{dtu_name}/{dtu_ser}'}, \
                                  {'dis_night_comm': 'True', \
                                   'local_sunrise': local_sunrise, \
                                   'local_sunset': local_sunset,
                                   'local_zone': local_zone})
        else:
            self.mqtt_client.sun_info2mqtt({'sun_topic': f'{dtu_name}/{dtu_ser}'}, \
                                      {'dis_night_comm': 'False'})