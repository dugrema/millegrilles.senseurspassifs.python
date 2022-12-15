import asyncio
import logging
import ssl

from aiohttp import web
from asyncio import Event
from asyncio.exceptions import TimeoutError
from typing import Optional

from senseurspassifs_relai_web import HttpCommands

from millegrilles_messages.messages import Constantes
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
import millegrilles_senseurspassifs.Constantes as ConstantesSenseursPassifs
from senseurspassifs_relai_web.Configuration import ConfigurationWeb
from senseurspassifs_relai_web.MessagesHandler import AppareilMessageHandler


class WebServer:

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.etat_senseurspassifs = etat_senseurspassifs
        self.message_handler = AppareilMessageHandler(self.etat_senseurspassifs)

        self.configuration = ConfigurationWeb()
        self.__app = web.Application()
        self.__stop_event: Optional[Event] = None

        self.__ssl_context = None

    def setup(self, configuration: Optional[dict] = None):
        self._charger_configuration(configuration)
        self._preparer_routes()

        self.__ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            self.__ssl_context.load_verify_locations(self.configuration.ca_pem_path)
        except FileNotFoundError as e:
            self.__logger.error("CA non trouve : %s" % self.configuration.ca_pem_path)
            raise e

        try:
            self.__ssl_context.load_cert_chain(self.configuration.cert_pem_path, self.configuration.key_pem_path)
        except FileNotFoundError as e:
            self.__logger.error("Cert/cles non trouves : %s / %s" % (self.configuration.cert_pem_path, self.configuration.key_pem_path))
            raise e

    def _charger_configuration(self, configuration: Optional[dict] = None):
        self.configuration.parse_config(configuration)

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

    async def entretien(self):
        self.__logger.debug('Entretien')
        try:
            await self.message_handler.entretien()
        except Exception:
            self.__logger.exception("Erreur entretien message_handler")

    async def run(self, stop_event: Optional[Event] = None):
        if stop_event is not None:
            self.__stop_event = stop_event
        else:
            self.__stop_event = Event()

        runner = web.AppRunner(self.__app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.configuration.port, ssl_context=self.__ssl_context)
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
        return web.json_response({'ok': True})

    async def handle_post_inscrire(self, request):
        return await HttpCommands.handle_post_inscrire(self, request)

    async def handle_post_poll(self, request):
        return await HttpCommands.handle_post_poll(self, request)

    async def handle_post_renouveler(self, request):
        return await HttpCommands.handle_post_renouveler(self, request)

    async def handle_post_commande(self, request):
        return await HttpCommands.handle_post_commande(self, request)

    async def handle_post_requete(self, request):
        return await HttpCommands.handle_post_requete(self, request)

    async def handle_post_timeinfo(self, request):
        return await HttpCommands.handle_post_timeinfo(self, request)

    async def transmettre_lecture(self, lecture: dict):
        producer = self.etat_senseurspassifs.producer

        if producer is None:
            self.__logger.debug("Producer n'est pas pret, lecture n'est pas transmise")
            return

        event_producer = producer.producer_pret()
        try:
            await asyncio.wait_for(event_producer.wait(), 1)
        except TimeoutError:
            self.__logger.debug("Producer MQ pas pret, abort transmission")
            return

        message_enveloppe = {
            'instance_id': self.etat_senseurspassifs.instance_id,
            'lecture': lecture,
            # 'uuid_appareil': uuid_appareil,
            # 'user_id': user_id,
            # 'senseurs': lectures_senseurs,
        }

        await producer.emettre_evenement(
            message_enveloppe,
            ConstantesSenseursPassifs.ROLE_SENSEURSPASSIFS_RELAI,
            ConstantesSenseursPassifs.EVENEMENT_DOMAINE_LECTURE,
            exchanges=[Constantes.SECURITE_PRIVE]
        )


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
            'commande.senseurspassifs_relai.%s.challengeAppareil' % instance_id,
            'evenement.SenseursPassifs.*.evenementMajDisplays',
            'evenement.SenseursPassifs.*.lectureConfirmee',
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
