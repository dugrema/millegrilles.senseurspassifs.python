import argparse
import logging

from millegrilles_messages.messages.MessagesModule import MessageProducerFormatteur


class SenseurModuleHandler:

    def __init__(self, etat_senseurspassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__etat_senseurspassifs = etat_senseurspassifs

    async def preparer_modules(self, args: argparse.Namespace):
        if args.dummysenseurs is True:
            self.__logger.info("Activer dummy senseurs")

        if args.dummylcd is True:
            self.__logger.info("Activer dummy LCD")


class SenseurModuleProducerAbstract:
    """
    Module de production de lectures
    """

    def __init__(self, producer: MessageProducerFormatteur):
        self.__producer = producer


class SenseurModuleConsumerAbstract:
    """
    Module de reception de lectures (e.g. affichage LCD)
    """

    def __init__(self):
        pass

