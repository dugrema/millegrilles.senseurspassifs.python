import asyncio
import datetime
import json
import logging

from aiohttp import web
from asyncio import Event
from asyncio.exceptions import TimeoutError
from typing import Optional

from millegrilles_messages.messages import Constantes
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from senseurspassifs_relai_web.Configuration import ConfigurationWeb
from millegrilles_senseurspassifs.SenseursModule import SenseurModuleHandler, SenseurModuleConsumerAbstract


class WebServer:

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__etat_senseurspassifs = etat_senseurspassifs

        self.__configuration = ConfigurationWeb()
        self.__app = web.Application()
        self.__stop_event: Optional[Event] = None

    def setup(self, configuration: Optional[dict] = None):
        self._charger_configuration(configuration)
        self._preparer_routes()

    def _charger_configuration(self, configuration: Optional[dict] = None):
        self.__configuration.parse_config(configuration)

    def _preparer_routes(self):
        self.__app.add_routes([
            web.get('/appareils/test', self.handle_test),
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
        site = web.TCPSite(runner, '0.0.0.0', self.__configuration.port)
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

    async def handle_test(self, request):
        return web.Response(text="Allo")


class ModuleSenseurWebServer:
    """ Wrapper de module pour le web server """

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__web_server = WebServer(etat_senseurspassifs)

    def setup(self, configuration: Optional[dict] = None):
        self.__web_server.setup(configuration)

    def routing_keys(self) -> list:
        return [
            'evenement.senseurspassifs_hub.*.*',
            'commande.senseurspassifs_hub.*.*',
            'requete.senseurspassifs_hub.*.*',
        ]

    async def traiter(self, message):
        """ Traiter messages recus via routing keys """
        self.__logger.debug("DummyConsumer Traiter message %s" % message)

    async def entretien(self):
        await self.__web_server.entretien()

    async def run(self, stop_event: Optional[Event] = None):
        await self.__web_server.run(stop_event)
