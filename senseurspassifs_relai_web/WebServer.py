import asyncio
import logging

from aiohttp import web
from aiohttp.web import Request
from asyncio import Event, TaskGroup
from typing import Optional
from websockets import serve, WebSocketServerProtocol

from millegrilles_messages.bus.BusContext import ForceTerminateExecution
from . import HttpCommands
from .SenseurspassifsRelaiWebManager import SenseurspassifsRelaiWebManager
from .WebSocketCommands import WebSocketClientHandler

from millegrilles_messages.messages import Constantes

from millegrilles_senseurspassifs import Constantes as SenseurspassifsWebRelayConstants
from senseurspassifs_relai_web.MessagesHandler import CorrelationAppareil


class WebServer:

    def __init__(self, manager: SenseurspassifsRelaiWebManager):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__manager = manager

        self.__app = web.Application()
        self.__stop_event: Optional[Event] = None

    async def setup(self):
        self._preparer_routes()

    def _preparer_routes(self):
        self.__app.add_routes([
            web.get('/senseurspassifs_relai/test', self.handle_test),
            web.post('/senseurspassifs_relai/inscrire', self.handle_post_inscrire),
            web.post('/senseurspassifs_relai/poll', self.handle_post_poll),
            web.post('/senseurspassifs_relai/renouveler', self.handle_post_renouveler),
            web.post('/senseurspassifs_relai/commande', self.handle_post_commande),
            web.post('/senseurspassifs_relai/requete', self.handle_post_requete),
            web.post('/senseurspassifs_relai/timeinfo',  self.handle_post_timeinfo)
        ])

    async def run(self, stop_event: Optional[Event] = None):
        if stop_event is not None:
            self.__stop_event = stop_event
        else:
            self.__stop_event = Event()

        web_port = self.__manager.context.configuration.web_port

        runner = web.AppRunner(self.__app)
        await runner.setup()
        ssl_context = self.__manager.context.ssl_context
        site = web.TCPSite(runner, '0.0.0.0', web_port, ssl_context=ssl_context)
        try:
            await site.start()
            self.__logger.info("Website started on port %d", web_port)
            await self.__manager.context.wait()
        finally:
            self.__logger.info("Website stopped")
            await runner.cleanup()

    async def handle_test(self, _request: Request):
        return web.json_response({'ok': True})

    async def handle_post_inscrire(self, request: Request):
        return await HttpCommands.handle_post_inscrire(request, self.__manager)

    async def handle_post_poll(self, request: Request):
        return await HttpCommands.handle_post_poll(request, self.__manager)

    async def handle_post_renouveler(self, request: Request):
        return await HttpCommands.handle_post_renouveler(request, self.__manager)

    async def handle_post_commande(self, request: Request):
        return await HttpCommands.handle_post_commande(request, self.__manager)

    async def handle_post_requete(self, request: Request):
        return await HttpCommands.handle_post_requete(request, self.__manager)

    async def handle_post_timeinfo(self, request: Request):
        return await HttpCommands.handle_post_timeinfo(request, self.__manager)

    async def transmettre_lecture(self, lecture: dict):
        producer = await self.__manager.context.get_producer()

        if producer is None:
            self.__logger.debug("Producer n'est pas pret, lecture n'est pas transmise")
            return

        message_enveloppe = {
            'instance_id': self.__manager.context.instance_id,
            'lecture': lecture,
        }

        await producer.event(
            message_enveloppe,
            SenseurspassifsWebRelayConstants.ROLE_SENSEURSPASSIFS_RELAI,
            SenseurspassifsWebRelayConstants.EVENEMENT_DOMAINE_LECTURE,
            exchange=Constantes.SECURITE_PRIVE
        )


class ServeurWebSocket:

    def __init__(self, manager: SenseurspassifsRelaiWebManager):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__manager = manager
        self.__websocket = None
        self.__task_group: Optional[TaskGroup] = None

    async def entretien(self):
        self.__logger.debug('Entretien')
        if self.__manager.context.fiche_publique is None:
            self.__logger.info("Pre-charger fiche publique")
            producer = await self.__manager.context.get_producer()
            try:
                signing_key = self.__manager.context.signing_key
                idmg = signing_key.enveloppe.idmg
                requete = {'idmg': idmg}
                reponse = await producer.request(
                    requete, 'CoreTopologie', exchange=Constantes.SECURITE_PRIVE, action='ficheMillegrille')

                if reponse.parsed.get('idmg') == idmg:
                    fiche = reponse.parsed
                    fiche['certificat'] = reponse.certificat.chaine_pem()
                    self.__manager.context.fiche_publique = fiche
            except asyncio.TimeoutError:
                self.__logger.info("MQ non pret pour charger fiche")

    async def __stop_thread(self):
        await self.__manager.context.wait()

    async def __serve(self):
        websocket_port = self.__manager.context.configuration.websocket_port
        ssl_context = self.__manager.context.ssl_context
        async with serve(self.handle_client, "0.0.0.0", websocket_port, ssl=ssl_context):
            self.__logger.info("Websocket started on port %d", websocket_port)
            await self.__manager.context.wait()  # wait until stopping

    async def run(self):

        try:
            try:
                async with TaskGroup() as group:
                    self.__task_group = group
                    group.create_task(self.__stop_thread())
                    group.create_task(self.__serve())
            except* Exception:
                if self.__manager.context.stopping is False:
                    self.__logger.exception("Unhandled thread exception - quitting")
                    self.__manager.context.stop()
                    raise ForceTerminateExecution()
        finally:
            self.__logger.info("Websocket stopped")

    async def handle_client(self, websocket: WebSocketServerProtocol):
        client_handler = WebSocketClientHandler(websocket, self.__manager)
        await client_handler.run()

    # async def transmettre_lecture(self, lecture: dict, correlation_appareil: CorrelationAppareil = None):
    #     producer = await self.__manager.context.get_producer()
    #
    #     if correlation_appareil is not None:
    #         lecture_relayee = lecture.copy()
    #         lecture_relayee['user_id'] = correlation_appareil.user_id
    #         lecture_relayee['uuid_appareil'] = correlation_appareil.uuid_appareil
    #         message_enveloppe = {
    #             'instance_id': self.__manager.context.instance_id,
    #             'lecture_relayee': lecture_relayee,
    #         }
    #     else:
    #         message_enveloppe = {
    #             'instance_id': self.__manager.context.instance_id,
    #             'lecture': lecture,
    #         }
    #
    #     await producer.event(
    #         message_enveloppe,
    #         SenseurspassifsWebRelayConstants.ROLE_SENSEURSPASSIFS_RELAI,
    #         SenseurspassifsWebRelayConstants.EVENEMENT_DOMAINE_LECTURE,
    #         exchange=Constantes.SECURITE_PRIVE
    #     )
