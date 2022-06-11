# Module pour les classes d'appareils utilises avec un Raspberry Pi (2, 3).
import datetime
import logging
import Adafruit_DHT  # https://github.com/adafruit/Adafruit_Python_DHT.git


# Thermometre AM2302 connecte sur une pin GPIO
# Dependances:
#   - Adafruit package Adafruit_DHT
class ThermometreAdafruitGPIO:

    def __init__(self, uuid_senseur, pin=24, sensor=Adafruit_DHT.AM2302):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self._uuid_senseur = uuid_senseur
        self._pin = pin
        self._sensor = sensor

    async def lire(self):
        humidite, temperature = Adafruit_DHT.read_retry(self._sensor, self._pin)

        self.__logger.debug("Lecture senseur : temperature = %s, humidite = %s" % (temperature, humidite))

        try:
            temperature_round = round(temperature, 1)
        except:
            temperature_round = None

        try:
            humidite_round = round(humidite, 1)
        except:
            humidite_round = None

        timestamp = int(datetime.datetime.now().timestamp())

        dict_message = {
            'uuid_senseur': self._uuid_senseur,
            'senseurs': {
                'dht/%d/temperature' % self._pin: {
                    'valeur': temperature_round,
                    'timestamp': timestamp,
                    'type': 'temperature',
                },
                'dht/%d/humidite' % self._pin: {
                    'valeur': humidite_round,
                    'timestamp': timestamp,
                    'type': 'humidite',
                }
            }
        }

        # Verifier que les valeurs ne sont pas erronees
        if 0 <= humidite <= 100 and -50 < temperature < 50:
            return dict_message
        else:
            self.__logger.warning("ThermometreAdafruitGPIO: Erreur de lecture DHT erronnee, valeurs hors limites: %s" % str(dict_message))
            return None
