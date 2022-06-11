import argparse

from millegrilles_senseurspassifs.Application import ApplicationInstance
from senseurspassifs_rpi.ModulesRpi import RpiModuleHandler


class ApplicationRpi(ApplicationInstance):

    def init_module_handler(self):
        # return SenseurModuleHandler(self.__etat_senseurspassifs)
        return RpiModuleHandler(self._etat_senseurspassifs)

    def _add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            '--lcd2lines', action="store_true", required=False,
            help="Initialise l'affichage LCD 2 lignes via TWI (I2C)"
        )

