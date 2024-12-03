import asyncio
import logging

from asyncio import TaskGroup
from typing import Optional

from millegrilles_messages.messages import Constantes
from millegrilles_messages.bus.BusContext import ForceTerminateExecution
from millegrilles_messages.messages.EnveloppeCertificat import EnveloppeCertificat
from millegrilles_messages.messages.MessagesModule import MessageWrapper
from senseurspassifs_relai_web.Context import SenseurspassifsRelaiWebContext
from senseurspassifs_relai_web.MessagesHandler import AppareilMessageHandler, CorrelationAppareil
from senseurspassifs_relai_web.ReadingsFormatter import ReadingsSender


class SenseurspassifsRelaiWebManager:

    def __init__(self, context: SenseurspassifsRelaiWebContext, device_message_handler: AppareilMessageHandler, readings_sender: ReadingsSender):
        self.__logger = logging.getLogger(__name__+'.'+self.__class__.__name__)
        self.__context = context
        self.__device_message_handler: AppareilMessageHandler = device_message_handler
        self.__readings_sender: ReadingsSender = readings_sender

    async def run(self):
        self.__logger.debug("SenseurspassifsRelaiWebManager thread started")
        try:
            async with TaskGroup() as group:
                group.create_task(self.__stop_thread())
                group.create_task(self.__initial_load_fiche_maintenance())
        except *Exception:  # Stop on any thread exception
            self.__logger.exception("SenseurspassifsRelaiWebManager Unhandled error, closing")

        if self.__context.stopping is False:
            self.__logger.error("SenseurspassifsRelaiWebManager stopping without stop flag set - force quitting")
            self.__context.stop()
            raise ForceTerminateExecution()

        self.__logger.debug("SenseurspassifsRelaiWebManager thread done")

    async def __stop_thread(self):
        await self.__context.wait()

    async def __initial_load_fiche_maintenance(self):
        """
        This thread attemps to load the fiche until one is received.
        :return:
        """

        while self.__context.fiche_publique is None:
            self.__logger.info("Pre-charger fiche publique")
            producer = await self.__context.get_producer()
            try:
                signing_key = self.__context.signing_key
                idmg = signing_key.enveloppe.idmg
                requete = {'idmg': idmg}
                reponse = await producer.request(
                    requete, 'CoreTopologie', exchange=Constantes.SECURITE_PRIVE, action='ficheMillegrille')

                if reponse.parsed.get('idmg') == idmg:
                    fiche = reponse.parsed
                    fiche['certificat'] = reponse.certificat.chaine_pem()
                    self.__context.fiche_publique = fiche
                    return  # Done
            except asyncio.TimeoutError:
                self.__logger.info("MQ non pret pour charger fiche")
            await self.__context.wait(20)

    @property
    def context(self) -> SenseurspassifsRelaiWebContext:
        return self.__context

    async def handle_message(self, message: MessageWrapper):
        return await self.__device_message_handler.recevoir_message_mq(message)

    async def request_device_registration(self, commande: dict):
        return await self.__device_message_handler.request_device_registration(commande)

    async def send_readings(self, lecture: dict, ):
        await self.__readings_sender.send_readings(lecture)

    async def send_readings_correlation(self, lecture: dict, correlation: Optional[CorrelationAppareil]):
        await self.__readings_sender.send_readings_correlation(lecture, correlation)

    async def enregistrer_appareil(self, enveloppe: EnveloppeCertificat, commande: Optional[dict] = None):
        raise NotImplementedError()

    async def create_device_correlation(self, certificat: EnveloppeCertificat, senseurs: Optional[list] = None,
                                        emettre_lectures=True) -> CorrelationAppareil:
        return await self.__device_message_handler.create_device_correlation(certificat, senseurs, emettre_lectures)

    def remove_device_correlation(self, fingerprint: str):
        self.__device_message_handler.remove_device(fingerprint)
