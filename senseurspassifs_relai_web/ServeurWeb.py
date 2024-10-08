import asyncio
import datetime
import logging
import ssl
import json

from aiohttp import web
from asyncio import Event
from asyncio.exceptions import TimeoutError
from typing import Optional
from websockets import serve, ConnectionClosedError

from . import HttpCommands
from .WebSocketCommands import handle_message

from millegrilles_messages.messages import Constantes
from millegrilles_messages.messages.MessagesModule import MessageWrapper
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
import millegrilles_senseurspassifs.Constantes as ConstantesSenseursPassifs
from senseurspassifs_relai_web.Configuration import ConfigurationWeb
from senseurspassifs_relai_web.MessagesHandler import AppareilMessageHandler, CorrelationAppareil
from senseurspassifs_relai_web.Chiffrage import attacher_reponse_chiffree


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


class ServeurWebSocket:

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.etat_senseurspassifs = etat_senseurspassifs
        self.message_handler = AppareilMessageHandler(self.etat_senseurspassifs)

        self.configuration = ConfigurationWeb()
        self.__websocket = None
        self.__stop_event: Optional[Event] = None

        self.__ssl_context = None

    def setup(self, configuration: Optional[dict] = None):
        self._charger_configuration(configuration)

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

    async def entretien(self):
        self.__logger.debug('Entretien')
        try:
            await self.message_handler.entretien()
        except Exception:
            self.__logger.exception("Erreur entretien message_handler")

        if self.etat_senseurspassifs.fiche_publique is None:
            self.__logger.info("Pre-charger fiche publique")
            producer = self.etat_senseurspassifs.producer
            if producer is not None:
                try:
                    await asyncio.wait_for(producer.producer_pret().wait(), 5)
                    idmg = self.etat_senseurspassifs.clecertificat.enveloppe.idmg
                    requete = {'idmg': idmg}
                    reponse = await producer.executer_requete(
                        requete, 'CoreTopologie', exchange=Constantes.SECURITE_PRIVE, action='ficheMillegrille')

                    if reponse.parsed.get('idmg') == idmg:
                        fiche = reponse.parsed
                        fiche['_certificat'] = reponse.certificat.chaine_pem()
                        self.etat_senseurspassifs.set_fiche_publique(fiche)
                except asyncio.TimeoutError:
                    self.__logger.info("MQ non pret pour charger fiche")

    async def run(self, stop_event: Optional[Event] = None):
        if stop_event is not None:
            self.__stop_event = stop_event
        else:
            self.__stop_event = Event()

        try:
            async with serve(self.handle_client, "0.0.0.0", self.configuration.websocket_port, ssl=self.__ssl_context):
                self.__logger.info("Websocket demarre")

                while not self.__stop_event.is_set():
                    await self.entretien()
                    try:
                        await asyncio.wait_for(self.__stop_event.wait(), 30)
                    except TimeoutError:
                        pass
        finally:
            self.__logger.info("Site arrete")

    async def handle_client(self, websocket):
        client_handler = WebSocketClientHandler(self, websocket)
        await client_handler.run()

    async def transmettre_lecture(self, lecture: dict, correlation_appareil: CorrelationAppareil = None):
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

        if correlation_appareil is not None:
            lecture_relayee = lecture.copy()
            lecture_relayee['user_id'] = correlation_appareil.user_id
            lecture_relayee['uuid_appareil'] = correlation_appareil.uuid_appareil
            message_enveloppe = {
                'instance_id': self.etat_senseurspassifs.instance_id,
                'lecture_relayee': lecture_relayee,
            }
        else:
            message_enveloppe = {
                'instance_id': self.etat_senseurspassifs.instance_id,
                'lecture': lecture,
            }

        await producer.emettre_evenement(
            message_enveloppe,
            ConstantesSenseursPassifs.ROLE_SENSEURSPASSIFS_RELAI,
            ConstantesSenseursPassifs.EVENEMENT_DOMAINE_LECTURE,
            exchanges=[Constantes.SECURITE_PRIVE]
        )


class WebSocketClientHandler:

    def __init__(self, server, websocket):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__server = server
        self.__websocket = websocket
        self.__correlation = None
        self.__event_correlation = asyncio.Event()
        self.__date_connexion = datetime.datetime.utcnow()

        self.__presence_emise: Optional[datetime.datetime] = None
        self.__uuid_appareil: Optional[str] = None
        self.__user_id: Optional[str] = None
        self.__version: Optional[str] = None

    @property
    def server(self):
        return self.__server

    @property
    def websocket(self):
        return self.__websocket

    def set_params_appareil(self, uuid_appareil: str, user_id: str):
        self.__uuid_appareil = uuid_appareil
        self.__user_id = user_id

    def set_version(self, version: str):
        self.__version = version

    async def presence_appareil(self, deconnecte=False):
        evenement = None
        if self.__uuid_appareil and self.__user_id:
            if deconnecte is True:
                evenement = {'uuid_appareil': self.__uuid_appareil, 'user_id': self.__user_id, 'deconnecte': True}
            elif self.__presence_emise is None:
                evenement = {'uuid_appareil': self.__uuid_appareil, 'user_id': self.__user_id, 'version': self.__version}

        if evenement:
            producer = self.__server.etat_senseurspassifs.producer
            if producer is None:
                self.__logger.debug("Producer n'est pas pret, lecture n'est pas transmise")
                return

            try:
                await asyncio.wait_for(producer.producer_pret().wait(), 1)
            except TimeoutError:
                self.__logger.debug("Producer MQ pas pret, abort transmission")
                return

            await producer.emettre_evenement(evenement,
                                             domaine='senseurspassifs_relai',
                                             action='presenceAppareil',
                                             exchanges=Constantes.SECURITE_PRIVE)

            self.__presence_emise = datetime.datetime.now()

    async def set_correlation(self, correlation):
        self.__correlation = correlation
        self.__event_correlation.set()

    async def run(self):
        self.__logger.debug("run Connexion client %s" % self.__correlation)
        await asyncio.gather(
            self.recevoir_messages(),
            self.relai_messages(),
            self.relai_lectures(),
        )
        self.__logger.debug("run Fin connexion %s/%s" % (self.__correlation, self.__date_connexion))

    async def recevoir_messages(self):
        self.__logger.debug("Connexion '%s'" % self.__date_connexion)

        try:
            async for message in self.__websocket:
                await handle_message(self, message)
                try:
                    await self.presence_appareil()
                except Exception:
                    self.__logger.exception("recevoir_messages Erreur emettre presence appareil")

        except ConnectionClosedError:
            self.__logger.debug("Connexion %s fermee incorrectement" % self.__date_connexion)
        finally:
            self.__event_correlation.set()  # Cleanup

        try:
            await self.presence_appareil(deconnecte=True)
        except Exception:
            self.__logger.exception("recevoir_messages Erreur emettre presence appareil")

        self.__logger.debug("Fin connexion '%s'" % self.__date_connexion)

    async def relai_messages(self):
        await self.__event_correlation.wait()
        self.__logger.debug("Debut relai_messages")

        while self.__websocket.open:
            try:
                reponse = await self.__correlation.get_reponse(5)

                if isinstance(reponse, MessageWrapper):
                    reponse = reponse.parsed['__original']
                elif isinstance(reponse, dict):
                    continue

                if reponse is not None:
                    attacher_reponse_chiffree(self.__correlation, reponse, enveloppe=None)
                    # if self.__correlation.chiffrage_disponible:
                    #     cle_dechiffrage = self.__correlation.cle_dechiffrage
                    #     message_chiffre = json.dumps({'contenu': reponse['contenu'], 'enveloppe': None})
                    #     # Chiffrer le contenu
                    #     message_chiffre = chiffrer_message_chacha20poly1305(cle_dechiffrage, message_chiffre)
                    #     reponse['attachements'] = {'relai_chiffre': message_chiffre}
                    await self.__websocket.send(json.dumps(reponse).encode('utf-8'))

            except asyncio.TimeoutError:
                pass

    async def relai_lectures(self):
        await self.__event_correlation.wait()
        self.__logger.debug("Debut relai_lectures")

        while self.__websocket.open:
            lectures_pending = self.__correlation.take_lectures_pending()
            if lectures_pending is not None and len(lectures_pending) > 0:
                # Retourner les lectures en attente

                reponse, _ = self.__server.etat_senseurspassifs.formatteur_message.signer_message(
                    Constantes.KIND_COMMANDE,
                    {'ok': True, 'lectures_senseurs': lectures_pending},
                    action='lectures_senseurs'
                )

                # Ajouter element relai_chiffre si possible
                attacher_reponse_chiffree(self.__correlation, reponse, enveloppe=None)

                # if self.__correlation.chiffrage_disponible:
                #     cle_dechiffrage = self.__correlation.cle_dechiffrage
                #     message_chiffre = json.dumps({'contenu': reponse['contenu'], 'enveloppe': None})
                #     # Chiffrer le contenu
                #     message_chiffre = chiffrer_message_chacha20poly1305(cle_dechiffrage, message_chiffre)
                #     reponse['attachements'] = {'relai_chiffre': message_chiffre}

                reponse_bytes = json.dumps(reponse).encode('utf-8')
                await self.__websocket.send(reponse_bytes)

            # Faire une aggregation de 20 secondes de lectures
            try:
                await asyncio.sleep(20)
            except asyncio.TimeoutError:
                pass  # OK

    async def transmettre_lecture(self, lecture: dict, correlation_appareil = None):
        await self.server.transmettre_lecture(lecture, correlation_appareil)


class ModuleSenseurWebServer:
    """ Wrapper de module pour le web server """

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__web_server = WebServer(etat_senseurspassifs)
        self.__websocket_server = ServeurWebSocket(etat_senseurspassifs)

    def setup(self, configuration: Optional[dict] = None):
        self.__web_server.setup(configuration)
        self.__websocket_server.setup(configuration)

    def routing_keys(self) -> list:
        instance_id = self.__web_server.etat_senseurspassifs.instance_id
        return [
            'commande.senseurspassifs_relai.%s.challengeAppareil' % instance_id,
            'commande.senseurspassifs_relai.%s.commandeAppareil' % instance_id,
            'evenement.SenseursPassifs.*.evenementMajDisplays',
            'evenement.SenseursPassifs.*.evenementMajProgrammes',
            'evenement.SenseursPassifs.*.lectureConfirmee',
            'evenement.SenseursPassifs.*.majConfigurationAppareil',
            (Constantes.SECURITE_PUBLIC, 'evenement.CoreTopologie.fichePublique'),
        ]

    async def recevoir_message_mq(self, message):
        """ Traiter messages recus via routing keys """
        self.__logger.debug("ModuleSenseurWebServer Traiter message %s" % message)
        try:
            await self.__web_server.message_handler.recevoir_message_mq(message)
            await self.__websocket_server.message_handler.recevoir_message_mq(message)
        except Exception as e:
            self.__logger.exception("Erreur traitement message %s : %s" % (message.routing_key, e))

    async def entretien(self):
        await self.__web_server.entretien()

    async def run(self, stop_event: Optional[Event] = None):
        await asyncio.gather(
            self.__web_server.run(stop_event),
            self.__websocket_server.run(stop_event)
        )
