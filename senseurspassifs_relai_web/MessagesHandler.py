# Effectue la correlation des messages pour appareils web
import asyncio
import datetime
import logging
import json
from asyncio import TaskGroup

from typing import Optional, Union

import pytz

from millegrilles_messages.messages import Constantes

from millegrilles_messages.messages.EnveloppeCertificat import EnveloppeCertificat
from millegrilles_messages.messages.MessagesModule import MessageWrapper
from senseurspassifs_relai_web.Chiffrage import preparer_cle_chiffrage
from senseurspassifs_relai_web.Context import SenseurspassifsRelaiWebContext

MAX_REQUETES_CERTIFICAT = 10
EXPIRATION_APPAREIL = datetime.timedelta(minutes=10)
EXPIRATION_REQUETE_CERTIFICAT = datetime.timedelta(minutes=3)


class CorrelationHook:

    def __init__(self):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

        self.__derniere_activite = datetime.datetime.now(tz=pytz.UTC)
        self.__reponse = asyncio.Queue(3)
        self.__reponse_consommee = False

    def touch(self):
        self.__derniere_activite = datetime.datetime.now(tz=pytz.UTC)

    @property
    def expire(self):
        return datetime.datetime.now(tz=pytz.UTC) - self.__derniere_activite > EXPIRATION_REQUETE_CERTIFICAT

    @property
    def is_message_pending(self):
        return not self.__reponse.empty()

    async def put_message(self, message: Union[dict, MessageWrapper], nowait=True):
        try:
            if nowait:
                self.__reponse.put_nowait(message)
            else:
                await self.__reponse.put(message)
        except asyncio.QueueFull:
            self.__logger.error("Erreur reception message appareil, Q full")

    async def get_reponse(self, timeout: Optional[int] = 60) -> Optional[MessageWrapper]:
        if timeout is None:
            reponse = self.__reponse.get_nowait()
        else:
            reponse = await asyncio.wait_for(self.__reponse.get(), timeout)

        if reponse is not None:
            self.__reponse_consommee = True

        return reponse


class CorrelationAppareil(CorrelationHook):
    """
    Queue de reception de messages pour un appareil
    """

    def __init__(self, certificat: EnveloppeCertificat, emettre_lectures=True):
        super().__init__()
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__certificat = certificat
        self.__senseurs_externes: Optional[list] = None
        self.__lectures_pending = dict()
        self.__emettre_lectures = emettre_lectures
        self.__cle_chiffrage: Optional[bytes] = None
        self.__relai_messages_actif = True

    @property
    def fingerprint(self) -> str:
        return self.__certificat.fingerprint

    @property
    def uuid_appareil(self):
        return self.__certificat.subject_common_name

    @property
    def user_id(self):
        return self.__certificat.get_user_id

    def preparer_cle_chiffrage(self, cle_peer: str) -> str:
        self.__cle_chiffrage, cle_peer_str = preparer_cle_chiffrage(cle_peer)
        return cle_peer_str

    def activer_relai_messages(self):
        self.__relai_messages_actif = True

    def take_lectures_pending(self):
        if len(self.__lectures_pending) > 0:
            lectures = self.__lectures_pending
            self.__lectures_pending = dict()
            return lectures

    async def recevoir_lecture(self, message: MessageWrapper):
        parsed = message.parsed
        uuid_appareil = parsed['uuid_appareil']
        if self.uuid_appareil == uuid_appareil:
            pass  # Skip, ce sont des lectures internes de l'appareil
        else:
            # Verifier si on veut des lectures de cet appareil
            if self.__senseurs_externes is not None:
                for senseur_externe in self.__senseurs_externes:

                    try:
                        uuid_appareil_externe, nom_senseur = senseur_externe.split(':')
                    except (AttributeError, KeyError):
                        continue  # Mauvais nom, pas un senseur externe

                    if uuid_appareil == uuid_appareil_externe:
                        try:
                            lectures = self.__lectures_pending[uuid_appareil]
                        except KeyError:
                            lectures = dict()
                            self.__lectures_pending[uuid_appareil] = lectures
                        try:
                            lectures[nom_senseur] = parsed['senseurs'][nom_senseur]
                            self.__logger.debug("Lectures pending appareil %s : %s" % (self.uuid_appareil, lectures))
                        except KeyError:
                            pass  # Senseur sans lecture/absent

                if self.__emettre_lectures is True and len(self.__lectures_pending) > 0 and self.is_message_pending is False:
                    lectures_pending = self.take_lectures_pending()
                    # Aucun message en attente, retourner les lectures immediatement
                    message = {
                        'ok': True,
                        'lectures_senseurs': lectures_pending,
                        '_action': 'lectures_senseurs',
                    }
                    await self.put_message(message)

    def set_senseurs_externes(self, senseurs: Optional[list]):
        self.__logger.debug("Enregistrement senseurs externes pour appareil %s : %s" % (self.uuid_appareil, senseurs))
        self.__senseurs_externes = senseurs

    @property
    def chiffrage_disponible(self):
        return self.__cle_chiffrage is not None

    @property
    def relai_messages_disponible(self):
        return self.__relai_messages_actif

    @property
    def cle_dechiffrage(self):
        return self.__cle_chiffrage

    def clear_chiffrage(self):
        self.__relai_messages_actif = False
        self.__cle_chiffrage = None


class CorrelationRequeteCertificat(CorrelationHook):

    def __init__(self, cle_publique: str, message: dict):
        super().__init__()
        self.__cle_publique = cle_publique
        self.__message = message

    @property
    def message(self):
        return self.__message


class AppareilMessageHandler:

    def __init__(self, context: SenseurspassifsRelaiWebContext):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__context = context
        self.__appareils: dict[str, CorrelationAppareil] = dict()
        self.__requetes_certificat: dict[str, CorrelationRequeteCertificat] = dict()

    async def run(self):
        async with TaskGroup() as group:
            group.create_task(self.__maintenance_thread())

    async def __stop_thread(self):
        await self.__context.wait()

        # Cleanup before stopping
        await self.__on_stop()

    async def __on_stop(self):
        """ Attempt emitting a disconnect message for all devices. """
        pass  # TODO

    async def __maintenance_thread(self):
        while self.__context.stopping is False:
            try:
                await self.__maintenance()
            except asyncio.CancelledError as e:
                raise e
            except:
                self.__logger.exception("__maintenance_thread Unhandled exception")
            await self.__context.wait(120)

    async def set_device_correlation(self, correlation: CorrelationAppareil):
        fingerprint = correlation.fingerprint
        self.__appareils[fingerprint] = correlation

    def remove_device(self, fingerprint: str):
        try:
            existing = self.__appareils[fingerprint]
            del self.__appareils[fingerprint]
            existing.clear_chiffrage()
        except KeyError:
            pass

    async def create_device_correlation(self, certificat: EnveloppeCertificat, senseurs: Optional[list] = None,
                                        emettre_lectures=True) -> CorrelationAppareil:
        """
        Create a correlation for a device. If correlation already exists, returns it.
        :param certificat:
        :param senseurs:
        :param emettre_lectures:
        :return:
        """

        fingerprint = certificat.fingerprint
        try:
            correlation = self.__appareils[fingerprint]
            correlation.touch()
            return correlation
        except KeyError:
            pass

        correlation = CorrelationAppareil(certificat, emettre_lectures)
        correlation.touch()

        if senseurs is not None:
            correlation.set_senseurs_externes(senseurs)

        self.__appareils[fingerprint] = correlation

        return correlation

    async def __maintenance(self):
        retirer = list()
        for fingerprint, appareil in self.__appareils.items():
            if appareil.expire:
                retirer.append(fingerprint)

        for fingerprint in retirer:
            self.__logger.debug("Retrait appareil expire cle %s" % fingerprint)
            del self.__appareils[fingerprint]

        retirer = list()
        for cle_publique, requete in self.__requetes_certificat.items():
            if requete.expire:
                retirer.append(cle_publique)

        for cle_publique in retirer:
            self.__logger.debug("Retrait requete expiree cle %s" % cle_publique)
            del self.__requetes_certificat[cle_publique]

    async def recevoir_message_mq(self, message: MessageWrapper):

        # Tenter match par fingerprint certificat (pubkey)
        try:
            await self.__appareils[message.pubkey].put_message(message)
            self.__logger.debug("Routing message MQ appareil via fingerprint %s" % message.pubkey)
            return
        except KeyError:
            pass

        # Tenter match par cle_publique
        try:
            await self.__requetes_certificat[message.parsed['cle_publique']].put_message(message)
            self.__logger.debug("Routing message MQ appareil via cle_publiquye %s" % message.parsed['cle_publique'])
            return
        except KeyError:
            pass

        action = message.routage['action']
        if action == 'fichePublique':
            # Conserver la fichePublique
            self.__logger.debug("Fiche publique mise a jour")
            fiche = message.parsed
            fiche['certificat'] = message.certificat.chaine_pem()
            self.__context.fiche_publique = fiche
            return

        user_id = message.routage['partition']

        if action == 'lectureConfirmee':
            # Permettre a chaque appareil de l'usager de recevoir la lecture
            for app in self.__appareils.values():
                if app.user_id == user_id:
                    try:
                        await app.recevoir_lecture(message)
                    except Exception:
                        self.__logger.exception("Erreur traitement message appareil %s" % app.uuid_appareil)
            return
        elif action == 'commandeAppareil':
            # Permettre a chaque appareil de l'usager de recevoir la lecture
            certificat = message.certificat
            user_id_certificat = certificat.get_user_id
            try:
                uuid_appareil = message.parsed['uuid_appareil']
                for app in self.__appareils.values():
                    if app.uuid_appareil == uuid_appareil and app.user_id == user_id_certificat:
                        try:
                            await app.put_message(message, nowait=False)
                            return
                        except Exception:
                            self.__logger.exception("Erreur traitement commande appareil %s" % app.uuid_appareil)
            except KeyError:
                pass

            return
        elif action in ['evenementMajDisplays', 'evenementMajProgrammes', 'majConfigurationAppareil']:
            try:
                uuid_appareil = message.parsed['uuid_appareil']
                for app in self.__appareils.values():
                    if app.uuid_appareil == uuid_appareil and app.user_id == user_id:
                        try:
                            await app.put_message(message, nowait=False)
                        except Exception:
                            self.__logger.exception("Erreur traitement maj display %s" % app.uuid_appareil)
            except KeyError:
                pass

            return

        self.__logger.warning("Message MQ sans match appareil")

    async def request_device_registration(self, message: dict):
        cle_publique = message['pubkey']
        try:
            requete = self.__requetes_certificat[cle_publique]
            requete.touch()
        except KeyError:
            if len(self.__requetes_certificat) >= MAX_REQUETES_CERTIFICAT:
                raise Exception('request_device_registration Too many waiting requests')

            # Conserver nouvelle requete
            requete = CorrelationRequeteCertificat(cle_publique, message)
            self.__requetes_certificat[cle_publique] = requete

        try:
            reponse = await requete.get_reponse(timeout=None)
            if reponse is not None:
                # Reponse deja recue, on a transmet
                return reponse
        except asyncio.QueueEmpty:
            pass

        # Emettre commande certificat vers SenseursPassifs, attendre reponse
        contenu = json.loads(message['contenu'])
        producer = await self.__context.get_producer()
        commande = {
            'uuid_appareil': contenu['uuid_appareil'],
            'instance_id': self.__context.instance_id,
            'user_id': contenu['user_id'],
            'cle_publique': cle_publique,
            'csr': contenu['csr'],
        }
        try:
            reponse = await producer.command(commande, 'SenseursPassifs', 'inscrireAppareil', Constantes.SECURITE_PRIVE)
            reponse_parsed = reponse.parsed
            if reponse_parsed.get('certificat') or reponse_parsed.get('challenge'):
                return reponse
        except Exception:
            # Attendre la reponse - raise timeout
            self.__logger.exception("request_device_registration Unhandled error")

        return await requete.get_reponse(timeout=60)


