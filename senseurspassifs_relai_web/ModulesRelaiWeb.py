import argparse
import logging

from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs.SenseursModule import SenseurModuleHandler
from senseurspassifs_relai_web.ServeurWeb import ModuleSenseurWebServer


class RelaiWebModuleHandler(SenseurModuleHandler):

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        super().__init__(etat_senseurspassifs)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

    async def preparer_modules(self, args: argparse.Namespace):
        await super().preparer_modules(args)

        serveur_relai_web = ModuleSenseurWebServer(self._etat_senseurspassifs)
        serveur_relai_web.setup()
        self._modules_consumer.append(serveur_relai_web)
