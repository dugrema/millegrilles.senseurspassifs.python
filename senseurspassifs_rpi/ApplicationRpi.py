import argparse

from millegrilles_senseurspassifs.Application import ApplicationInstance
from senseurspassifs_rpi.ModulesRpi import RpiModuleHandler


class ApplicationRpi(ApplicationInstance):

    def init_module_handler(self):
        # return SenseurModuleHandler(self.__etat_senseurspassifs)
        return RpiModuleHandler(self._etat_senseurspassifs)

    def _add_arguments(self, parser: argparse.ArgumentParser):
        super()._add_arguments(parser)
        parser.add_argument(
            '--lcd2lines', action="store_true", required=False,
            help="Initialise l'affichage LCD 2 lignes via TWI (I2C)"
        )
        parser.add_argument(
            '--rf24master', action="store_true", required=False,
            help="Active le hub nRF24L01"
        )
        parser.add_argument(
            '--dht', type=int,
            required=False, help="Active le senseur DHT (AM2302) sur pin N"
        )
