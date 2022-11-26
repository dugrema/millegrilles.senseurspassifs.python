import asyncio
import datetime
import json
import logging

from aiohttp import web
from asyncio import Event
from asyncio.exceptions import TimeoutError
from typing import Optional

from senseurspassifs_relai_web import HttpCommands

from millegrilles_messages.messages import Constantes
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from senseurspassifs_relai_web.Configuration import ConfigurationWeb
from senseurspassifs_relai_web.MessagesHandler import AppareilMessageHandler
from millegrilles_senseurspassifs.SenseursModule import SenseurModuleHandler, SenseurModuleConsumerAbstract


class WebServer:

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.etat_senseurspassifs = etat_senseurspassifs
        self.message_handler = AppareilMessageHandler(self.etat_senseurspassifs)

        self.configuration = ConfigurationWeb()
        self.__app = web.Application()
        self.__stop_event: Optional[Event] = None

    def setup(self, configuration: Optional[dict] = None):
        self._charger_configuration(configuration)
        self._preparer_routes()

    def _charger_configuration(self, configuration: Optional[dict] = None):
        self.configuration.parse_config(configuration)

    def _preparer_routes(self):
        self.__app.add_routes([
            web.post('/appareils/inscrire', self.handle_post_inscrire),
            web.post('/appareils/poll', self.handle_post_poll),
            web.post('/appareils/commande', self.handle_post_commande),
        ])

    async def entretien(self):
        self.__logger.debug('Entretien')
        #try:
        #    await self.__etat_senseurspassifs.entretien()
        #except:
        #    self.__logger.exception("Erreur entretien etat_certissuer")

    async def run(self, stop_event: Optional[Event] = None):
        if stop_event is not None:
            self.__stop_event = stop_event
        else:
            self.__stop_event = Event()

        runner = web.AppRunner(self.__app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.configuration.port)
        try:
            await site.start()
            self.__logger.info("Site demarre")

            while not self.__stop_event.is_set():
                await self.entretien()
                try:
                    await asyncio.wait_for(self.__stop_event.wait(), 30)
                except TimeoutError:
                    pass
        finally:
            self.__logger.info("Site arrete")
            await runner.cleanup()

    async def handle_post_inscrire(self, request):
        return await HttpCommands.handle_post_inscrire(self, request)

    async def handle_post_poll(self, request):
        return await HttpCommands.handle_post_poll(self, request)

    async def handle_post_commande(self, request):
        return await HttpCommands.handle_post_commande(self, request)


class ModuleSenseurWebServer:
    """ Wrapper de module pour le web server """

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__web_server = WebServer(etat_senseurspassifs)

    def setup(self, configuration: Optional[dict] = None):
        self.__web_server.setup(configuration)

    def routing_keys(self) -> list:
        instance_id = self.__web_server.etat_senseurspassifs.instance_id
        return [
            #'evenement.senseurspassifs_hub.*.*',
            #'requete.senseurspassifs_hub.*.*',
            'commande.senseurspassifs_hub.%s.challengeAppareil' % instance_id,
        ]

    async def recevoir_message_mq(self, message):
        """ Traiter messages recus via routing keys """
        self.__logger.debug("ModuleSenseurWebServer Traiter message %s" % message)
        try:
            await self.__web_server.message_handler.recevoir_message_mq(message)
        except Exception as e:
            self.__logger.error("Erreur traitement message %s : %s" % (message.routing_key, e))

    async def entretien(self):
        await self.__web_server.entretien()

    async def run(self, stop_event: Optional[Event] = None):
        await self.__web_server.run(stop_event)
