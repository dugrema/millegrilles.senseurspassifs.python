import asyncio
import datetime
import logging
import json
from asyncio import TaskGroup

import pytz

from typing import Optional, Union

from astral import LocationInfo
from astral.sun import sun
from websockets import ConnectionClosedError, WebSocketServerProtocol
from websockets.frames import CloseCode

from millegrilles_messages.bus.BusContext import ForceTerminateExecution
from millegrilles_messages.messages import Constantes
from millegrilles_messages.messages.EnveloppeCertificat import EnveloppeCertificat
from millegrilles_messages.messages.MessagesModule import MessageWrapper
from senseurspassifs_relai_web.Chiffrage import dechiffrer_message_chacha20poly1305, attacher_reponse_chiffree
from senseurspassifs_relai_web.MessagesHandler import CorrelationAppareil
from senseurspassifs_relai_web.SenseurspassifsRelaiWebManager import SenseurspassifsRelaiWebManager

LOGGER = logging.getLogger(__name__)


class WebSocketClientHandler:

    def __init__(self, websocket: WebSocketServerProtocol, manager: SenseurspassifsRelaiWebManager):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__websocket: WebSocketServerProtocol = websocket
        self.__manager: SenseurspassifsRelaiWebManager = manager
        self.__correlation: Optional[CorrelationAppareil] = None
        self.__event_correlation = asyncio.Event()
        self.__date_connexion = datetime.datetime.now(tz=pytz.UTC)

        self.__presence_emise: Optional[datetime.datetime] = None
        self.__uuid_appareil: Optional[str] = None
        self.__user_id: Optional[str] = None
        self.__version: Optional[str] = None

        self.__client_stopping = asyncio.Event()

    @property
    def websocket(self) -> WebSocketServerProtocol:
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
            producer = await self.__manager.context.get_producer()

            await producer.event(evenement,
                                 domain='senseurspassifs_relai',
                                 action='presenceAppareil',
                                 exchange=Constantes.SECURITE_PRIVE)

            self.__presence_emise = datetime.datetime.now()

    async def run(self):
        self.__logger.debug("run Connexion client %s" % self.__correlation)
        try:
            async with TaskGroup() as group:
                group.create_task(self.__recevoir_messages())
                group.create_task(self.__relai_messages())
                group.create_task(self.__relai_lectures())
                group.create_task(self.__connection_closed_waiter())
                group.create_task(self.__watchdog())
        except* asyncio.CancelledError as e:
            raise e
        except* ForceTerminateExecution:
            self.__logger.info("Closing thread")
        except* Exception:
            if self.__manager.context.stopping is False:
                self.__logger.exception("Unhandled error, thread closed - diconnecting device %s/%s", self.__user_id, self.__uuid_appareil)
                await self.websocket.close(CloseCode.ABNORMAL_CLOSURE, 'Thread closed')

        self.__logger.debug("End connexion userid: %s, uuid_appareil: %s, fingerprint: %s, connection date: %s",
                            self.__user_id, self.__uuid_appareil, self.__correlation.fingerprint, self.__date_connexion)

    async def __connection_closed_waiter(self):
        await self.__websocket.wait_closed()
        # Release all threads
        self.__client_stopping.set()
        await self.__correlation.put_message(None)

    async def __watchdog(self):
        while self.__manager.context.stopping is False and self.__client_stopping.is_set() is False:
            if self.__correlation and self.__correlation.expire:
                self.__logger.info("Client connection expired, disconnecting")
                await self.websocket.close(CloseCode.TRY_AGAIN_LATER, "Timeout")
                return
            try:
                await asyncio.wait_for(self.__client_stopping.wait(), 60)
                return  # Stopping
            except asyncio.TimeoutError:
                pass

        if self.__websocket.open:
            await self.websocket.close(CloseCode.NORMAL_CLOSURE, "Closing")

    async def __recevoir_messages(self):
        self.__logger.debug("__recevoir_messages Connexion '%s'", self.__date_connexion)

        try:
            async for message in self.__websocket:
                await self.__handle_message(message)
                try:
                    await self.presence_appareil()
                except Exception:
                    self.__logger.exception("__recevoir_messages Erreur emettre presence appareil")
                self.__correlation.touch()

        except ConnectionClosedError:
            self.__logger.debug("Connexion %s fermee incorrectement" % self.__date_connexion)
        finally:
            self.__event_correlation.set()  # Cleanup

        try:
            await self.presence_appareil(deconnecte=True)
        except Exception:
            self.__logger.exception("__recevoir_messages Erreur emettre presence appareil")

        self.__logger.debug("__recevoir_messages Fin connexion '%s'" % self.__date_connexion)

    async def __relai_messages(self):
        await self.__event_correlation.wait()
        self.__logger.debug("Debut relai_messages")

        while self.__websocket.open:
            try:
                reponse = await self.__correlation.response_queue.get()
                if self.__manager.context.stopping or self.__client_stopping.is_set():
                    return  # Stopping

                if isinstance(reponse, MessageWrapper):
                    reponse = reponse.parsed['__original']
                elif isinstance(reponse, dict):
                    continue

                if reponse is not None:
                    attacher_reponse_chiffree(self.__correlation, reponse, enveloppe=None)
                    await self.__websocket.send(json.dumps(reponse).encode('utf-8'))

            except asyncio.TimeoutError:
                pass

    async def __relai_lectures(self):
        await self.__event_correlation.wait()
        self.__logger.debug("Debut relai_lectures")

        while self.__websocket.open:
            lectures_pending = self.__correlation.take_lectures_pending()
            if lectures_pending is not None and len(lectures_pending) > 0:
                # Retourner les lectures en attente

                reponse, _ = self.__manager.context.formatteur.signer_message(
                    Constantes.KIND_COMMANDE,
                    {'ok': True, 'lectures_senseurs': lectures_pending},
                    action='lectures_senseurs'
                )

                # Ajouter element relai_chiffre si possible
                attacher_reponse_chiffree(self.__correlation, reponse, enveloppe=None)

                reponse_bytes = json.dumps(reponse).encode('utf-8')
                await self.__websocket.send(reponse_bytes)

            # Faire une aggregation de 20 secondes de lectures
            try:
                await asyncio.wait_for(self.__client_stopping.wait(), 20)
                return  # Stopping
            except asyncio.TimeoutError:
                pass  # Loop

    async def __transmettre_lecture(self, lecture: dict, correlation_appareil: Optional[CorrelationAppareil] = None):
        await self.__manager.send_readings_correlation(lecture, correlation_appareil)

    async def __handle_message(self, message: bytes):
        # Extraire information de l'enveloppe du message
        try:
            commande = json.loads(message)
            context = self.__manager.context
            action = commande['routage']['action']

            # Check if the sig element is present (means the message is not encrypted)
            if 'sig' in commande:
                # Message is not encrypted
                enveloppe = await context.validateur_message.verifier(commande)

                try:
                    uuid_appareil = enveloppe.subject_common_name
                    user_id = enveloppe.get_user_id
                    self.set_params_appareil(uuid_appareil, user_id)
                except AttributeError:
                    LOGGER.exception("Erreur set_params_appareils")

                if action == 'etatAppareil':
                    return await self.__handle_status(commande)
                elif action == 'getTimezoneInfo':
                    return await self.__handle_get_timezone_info(commande)
                elif action in ['getAppareilDisplayConfiguration', 'getAppareilProgrammesConfiguration']:
                    return await self.__handle_requete(commande, enveloppe)
                elif action == 'signerAppareil':
                    return await self.__handle_renouvellement(commande, enveloppe)
                elif action == 'getFichePublique':
                    return await self.__handle_get_fiche(commande, enveloppe)
                elif action == 'getRelaisWeb':
                    return await self.__handle_get_relais_web()
                elif action == 'echangerClesChiffrage':
                    return await self.__handle_echanger_cles_chiffrage(commande, enveloppe)
                elif action == 'confirmerRelai':
                    return await self.__handle_confirmer_relai(commande, enveloppe)
            else:
                # Encrypted message
                ciphertext = commande['ciphertext']
                tag = commande['tag']
                nonce = commande['nonce']

                try:
                    cle_dechiffrage = self.__correlation.cle_dechiffrage
                    commande = dechiffrer_message_chacha20poly1305(cle_dechiffrage, nonce, tag, ciphertext)
                    commande = json.loads(commande)

                    if action == 'etatAppareilRelai':
                        return await self.__handle_relai_status(commande)
                    elif action == 'getRelaisWeb':
                        return await self.__handle_get_relais_web()
                    elif action == 'getTimezoneInfo':
                        return await self.__handle_get_timezone_info(commande)
                except asyncio.CancelledError as e:
                    raise e
                except Exception:
                    LOGGER.exception('Erreur dechiffrage, on desactive le chiffrage')
                    self.__correlation.clear_chiffrage()
                    reponse, _ = self.__manager.context.formatteur.signer_message(
                        Constantes.KIND_COMMANDE, dict(), action='resetSecret')
                    await self.__websocket.send(json.dumps(reponse).encode('utf-8'))

            LOGGER.error("handle_message Action inconnue %s" % action)

        except asyncio.CancelledError as e:
            raise e
        except Exception as e:
            LOGGER.error("handle_message Unhandled error %s" % str(e))


    async def __handle_status(self, commande: dict):
        try:
            LOGGER.debug("handle_status Etat recu %s" % commande)

            enveloppe = await self.__manager.context.validateur_message.verifier(commande)
            user_id = enveloppe.get_user_id

            # S'assurer d'avoir un appareil de role senseurspassifs
            if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
                LOGGER.info("Mauvais role certificat (%s) pour etat appareil" % enveloppe.get_roles)
                return

            contenu = json.loads(commande['contenu'])
            try:
                senseurs = contenu['senseurs']
            except KeyError:
                senseurs = None

            await self.__create_device_correlation(enveloppe, senseurs, emettre_lectures=False)

            # Emettre l'etat de l'appareil (une lecture)
            await self.__transmettre_lecture(commande)

        except Exception as e:
            LOGGER.error("handle_status Erreur %s" % str(e))

    async def __create_device_correlation(self, certificat: EnveloppeCertificat, senseurs: Optional[list] = None,
                                          emettre_lectures=True):
        self.__correlation = await self.__manager.create_device_correlation(certificat, senseurs, emettre_lectures)
        self.__event_correlation.set()

    async def __handle_relai_status(self, commande: dict):
        try:
            LOGGER.debug("handle_relai_status uuid_appareil: %s, etat recu %s" % (self.__correlation.uuid_appareil, commande))

            # Emettre l'etat de l'appareil (une lecture)
            await self.__transmettre_lecture(commande, self.__correlation)

            try:
                senseurs = commande['senseurs']
                if senseurs is not None:
                    self.__correlation.set_senseurs_externes(senseurs)
            except KeyError:
                pass

            return self.__correlation

        except Exception as e:
            LOGGER.error("handle_relai_status Erreur %s" % str(e))

    async def __handle_get_timezone_info(self, requete: dict):
        producer = await self.__manager.context.get_producer()

        reponse = {'ok': True}

        uuid_appareil = self.__correlation.uuid_appareil
        user_id = self.__correlation.user_id
        timezone_str = None
        geoposition = None

        try:
            requete_appareil = {'user_id': user_id, 'uuid_appareil': uuid_appareil}
            reponse_appareil = await producer.request(
                requete_appareil, 'SenseursPassifs', 'getTimezoneAppareil', exchange=Constantes.SECURITE_PRIVE, timeout=3)
            timezone_str = reponse_appareil.parsed.get('timezone')
            geoposition = reponse_appareil.parsed.get('geoposition') or dict()
        except asyncio.TimeoutError:
            pass

        # Note : les valeurs fournies dans la requete viennent de l'appareil (e.g. GPS, override)
        try:
            latitude = requete.get('latitude') or geoposition.get('latitude')
            longitude = requete.get('longitude') or geoposition.get('longitude')
        except AttributeError:
            latitude = None
            longitude = None

        if timezone_str is None:
            try:
                timezone_str = requete['timezone']
                reponse['timezone'] = timezone_str
            except KeyError:
                timezone_str = None

        if timezone_str:
            reponse['timezone'] = timezone_str
            try:
                timezone_pytz = pytz.timezone(timezone_str)
                info_tz = calculer_transition_tz(timezone_pytz)
                reponse.update(info_tz)
            except pytz.exceptions.UnknownTimeZoneError:
                LOGGER.error("Timezone %s inconnue" % timezone_str)
            except KeyError:
                # pas de timezone
                reponse['ok'] = False
        else:
            reponse['ok'] = False

        # Verifier si on retourne l'information de l'horaire solaire de la journee
        if isinstance(latitude, (float, int)) and isinstance(longitude, (float, int)):
            reponse['latitude'] = latitude
            reponse['longitude'] = longitude
            reponse['solaire_utc'] = calculer_horaire_solaire(latitude, longitude)
            reponse['ok'] = True

        reponse, _ = self.__manager.context.formatteur.signer_message(Constantes.KIND_COMMANDE, reponse, action='timezoneInfo')

        attacher_reponse_chiffree(self.__correlation, reponse, enveloppe=None)

        await self.__websocket.send(json.dumps(reponse).encode('utf-8'))

    async def __handle_get_relais_web(self):
        fiche = self.__manager.context.fiche_publique
        if fiche is not None:
            try:
                url_relais = parse_fiche_relais(fiche)
                reponse = {'relais': url_relais}
                reponse, _ = self.__manager.context.formatteur.signer_message(Constantes.KIND_COMMANDE, reponse, action='relaisWeb')
                attacher_reponse_chiffree(self.__correlation, reponse, enveloppe=None)
                await self.__websocket.send(json.dumps(reponse).encode('utf-8'))
            except KeyError:
                pass  # OK, pas de timezone

    async def __handle_requete(self, requete: dict, enveloppe):
        try:
            LOGGER.debug("handle_post_request Etat recu %s" % requete)

            user_id = enveloppe.get_user_id
            routage_requete = requete['routage']
            action_requete = routage_requete['action']

            # S'assurer d'avoir un appareil de role senseurspassifs
            if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
                LOGGER.error("Requete refusee pour roles %s" % enveloppe.get_roles)
                return

            # # Touch (conserver presence appareil)
            # await server.message_handler.create_device_correlation(enveloppe, emettre_lectures=False)

            # Emettre la requete
            domaine_requete = routage_requete['domaine']
            partition_requete = routage_requete.get('partition')
            exchange = Constantes.SECURITE_PRIVE

            try:
                producer = await self.__manager.context.get_producer()
                reponse = await producer.request(
                    requete, domaine_requete, action_requete, exchange, partition_requete, noformat=True)
                reponse = reponse.parsed['__original']

                # Injecter _action (en-tete de reponse ne contient pas d'action)
                reponse['attachements'] = {'action': action_requete}

                attacher_reponse_chiffree(self.__correlation, reponse, enveloppe=None)

                await self.__websocket.send(json.dumps(reponse).encode('utf-8'))
            except asyncio.TimeoutError:
                pass

        except Exception:
            LOGGER.exception("Erreur traitement requete")

    async def __handle_renouvellement(self, commande: dict, enveloppe):
        try:
            LOGGER.debug("handle_renouvellement Demande recue %s" % commande)

            # Verifier - s'assure que la signature est valide et certificat est encore actif
            user_id = enveloppe.get_user_id

            # S'assurer d'avoir un appareil de role senseurspassifs
            if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
                LOGGER.info("handle_renouvellement Role certificat renouvellement invalide : %s" % enveloppe.get_roles)
                return  # Skip

            routage = commande['routage']
            try:
                if routage['action'] != 'signerAppareil' or routage['domaine'] != 'SenseursPassifs':
                    LOGGER.info("handle_renouvellement Action/domaine certificat renouvellement invalide")
                    return  # Skip
            except KeyError:
                LOGGER.info("handle_renouvellement Action/domaine certificat renouvellement invalide")
                return  # Skip

            # Faire le relai de la commande - CorePki/certissuer s'occupent des renouvellements de certs actifs
            try:
                producer = await self.__manager.context.get_producer()
                reponse = await producer.command(
                    commande, 'SenseursPassifs', 'signerAppareil', Constantes.SECURITE_PRIVE, noformat=True)
                reponse = reponse.parsed['__original']

                # Injecter _action (en-tete de reponse ne contient pas d'action)
                reponse['attachements'] = {'action': 'signerAppareil'}

                attacher_reponse_chiffree(self.__correlation, reponse, enveloppe=None)

                reponse_bytes = json.dumps(reponse).encode('utf-8')

                await self.__websocket.send(reponse_bytes)
            except asyncio.TimeoutError:
                LOGGER.info("handle_renouvellement Erreur commande signerAppareil (timeout)")

        except Exception as e:
            LOGGER.error("handle_renouvellement Erreur %s" % str(e))

    async def __handle_get_fiche(self, commande: dict, enveloppe):
        fiche = self.__manager.context.fiche_publique
        if fiche is not None:
            reponse_bytes = json.dumps(fiche).encode('utf-8')
            await self.__websocket.send(reponse_bytes)

    async def __handle_echanger_cles_chiffrage(self, commande: dict, enveloppe: EnveloppeCertificat):
        user_id = enveloppe.get_user_id

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            LOGGER.info("Mauvais role certificat (%s) pour etat appareil" % enveloppe.get_roles)
            return

        # correlation = await self.__manager.enregistrer_appareil(enveloppe, emettre_lectures=False)
        # await self.__set_correlation(correlation)
        if self.__correlation is None:
            await self.__create_device_correlation(enveloppe, emettre_lectures=False)

        contenu = json.loads(commande['contenu'])

        try:
            version = contenu['version']
            self.set_version(version)
        except (AttributeError, KeyError):
            LOGGER.debug("Version non disponible")

        # Valider enveloppe, doit correspondre a l'appareil authentifie
        LOGGER.debug("handle_echanger_cles_chiffrage commande : %s" % commande)
        cle_peer = contenu['peer']
        cle_publique_locale = await self.echanger_cle_chiffrage(cle_peer)

        reponse = {'peer': cle_publique_locale}
        reponse, _ = self.__manager.context.formatteur.signer_message(
            Constantes.KIND_COMMANDE, reponse, action='echangerSecret')

        reponse_bytes = json.dumps(reponse).encode('utf-8')
        await self.__websocket.send(reponse_bytes)


    async def __handle_confirmer_relai(self, commande: dict, enveloppe: EnveloppeCertificat):
        # Verifier que la commande est bien pour le certificat local

        try:
            fingerprint = enveloppe.fingerprint
            if fingerprint != self.__correlation.fingerprint:
                raise Exception('handle_confirmer_relai: Wrong fingerprint response - deactivating encryption')

            # Transmettre la commande de confirmation vers le domaine SenseursPassifs
            # Va permettre de faire le relai de l'etat du senseur via signature locale
            if commande['routage']['action'] != 'confirmerRelai' or commande['routage']['domaine'] != 'SenseursPassifs':
                raise Exception('handle_confirmer_relai: mauvais domaine/action pour commande confirmation : %s' % commande['routage'])

            producer = await self.__manager.context.get_producer()
            result = await producer.command(commande, 'SenseursPassifs', 'confirmerRelai', Constantes.SECURITE_PRIVE,
                                            noformat=True, timeout=5)
            if result.parsed.get('ok') is True:
                # Tout est pret, le relai peut maintenant signer le contenu du client
                self.activer_relai_messages()
            else:
                self.__logger.error("Error activating encrypted message relay: %s", result)

        except asyncio.CancelledError as e:
            raise e
        except Exception:
            LOGGER.exception("Erreur confirmation relai avec domaine, desactiver chiffrage avec microcontrolleur")
            self.__correlation.clear_chiffrage()
            # Desactiver le chiffrage avec le client
            reponse, _ = self.__manager.context.formatteur.signer_message(
                Constantes.KIND_COMMANDE, dict(), action='resetSecret')
            reponse_bytes = json.dumps(reponse).encode('utf-8')
            await self.__websocket.send(reponse_bytes)

    async def echanger_cle_chiffrage(self, cle_peer: str):
        return self.__correlation.preparer_cle_chiffrage(cle_peer)

    def activer_relai_messages(self):
        self.__correlation.activer_relai_messages()


def calculer_transition_tz(tz):
    transition_times = tz._utc_transition_times
    now = datetime.datetime.now()
    current_offset_secs = int(tz.utcoffset(now).total_seconds())

    next_transition = None
    for transition in transition_times:
        if transition > now:
            next_transition = transition
            break

    reponse = {'timezone_offset': current_offset_secs}

    if next_transition:
        timestamp_utc = datetime.datetime(
            next_transition.year, next_transition.month, next_transition.day,
            next_transition.hour, next_transition.minute, tzinfo=pytz.UTC)
        next_transition_secs = int(timestamp_utc.timestamp())
        next_offset_secs = int(tz.utcoffset(next_transition).total_seconds())
        reponse['transition_time'] = next_transition_secs
        reponse['transition_offset'] = next_offset_secs

    return reponse


def calculer_horaire_solaire(latitude: Union[float, int], longitude: Union[float, int]):

    location_info = LocationInfo("ici", "ici", "UTC", latitude, longitude)

    today = datetime.datetime.now().date()
    vals = ['dawn', 'sunrise', 'noon', 'sunset', 'dusk']

    s = sun(location_info.observer, date=today, tzinfo="UTC")

    # Convertir les valeurs en timestamps (epoch secs)
    timestamp_vals = dict()
    for val in vals:
        # Convertir le temps en liste [heure UTC, minute]
        temps_solaire = s[val]
        heure_list = [temps_solaire.hour, temps_solaire.minute]
        timestamp_vals[val] = heure_list

    return timestamp_vals


def parse_fiche_relais(fiche: dict):
    app_instance_pathname = dict()
    for instance_id, app_params in fiche['applicationsV2']['senseurspassifs_relai']['instances'].items():
        try:
            app_instance_pathname[instance_id] = app_params['pathname']
            LOGGER.debug("instance_id %s pathname %s" % (instance_id, app_params['pathname']))
        except KeyError:
            pass

    LOGGER.debug("relais %d instances" % len(app_instance_pathname))

    url_relais = list()
    for instance_id, instance_params in fiche['instances'].items():
        try:
            pathname = app_instance_pathname[instance_id]
        except KeyError:
            continue  # Pas de path

        try:
            port = instance_params['ports']['https']
        except KeyError:
            port = 443

        try:
            for domaine in instance_params['domaines']:
                url_relais.append(f'https://{domaine}:{port}{pathname}')
        except KeyError:
            pass

    return url_relais
