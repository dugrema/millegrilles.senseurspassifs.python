import argparse
import logging

from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs.SenseursModule import SenseurModuleHandler
from senseurspassifs_relai_web.ServeurWeb import ModuleSenseurWebServer
from millegrilles_messages.messages.MessagesModule import MessageWrapper


class RelaiWebModuleHandler(SenseurModuleHandler):

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        super().__init__(etat_senseurspassifs)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__serveur = None

    async def preparer_modules(self, args: argparse.Namespace):
        await super().preparer_modules(args)

        serveur_relai_web = ModuleSenseurWebServer(self._etat_senseurspassifs)
        serveur_relai_web.setup()
        self.__serveur = serveur_relai_web
        self._modules_consumer.append(serveur_relai_web)

    async def recevoir_confirmation_lecture(self, message: MessageWrapper):
        """
        Recoit tous les evenements de confirmation de lectures
        :param message:
        :return:
        """
        self.__logger.debug("recevoir_message Traiter dans chaque consumer %s" % message)
        await self.__serveur.recevoir_message_mq(message)
