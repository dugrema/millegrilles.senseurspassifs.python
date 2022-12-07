# Effectue la correlation des messages pour appareils web
import asyncio
import datetime
import logging

from typing import Optional

from millegrilles_messages.messages import Constantes

from millegrilles_messages.messages.EnveloppeCertificat import EnveloppeCertificat
from millegrilles_messages.messages.MessagesModule import MessageWrapper

MAX_REQUETES_CERTIFICAT = 5
EXPIRATION_APPAREIL = datetime.timedelta(minutes=10)
EXPIRATION_REQUETE_CERTIFICAT = datetime.timedelta(minutes=3)


class CorrelationHook:

    def __init__(self):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

        self.__derniere_activite = datetime.datetime.utcnow()
        self.__reponse = asyncio.Queue(1)
        self.__reponse_consommee = False

    def touch(self):
        self.__derniere_activite = datetime.datetime.utcnow()

    @property
    def expire(self):
        return datetime.datetime.utcnow() - self.__derniere_activite > EXPIRATION_REQUETE_CERTIFICAT

    def put_message(self, message: MessageWrapper):
        try:
            self.__reponse.put_nowait(message)
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

    def __init__(self, certificat: EnveloppeCertificat):
        super().__init__()
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__certificat = certificat

    @property
    def uuid_appareil(self):
        return self.__certificat.subject_common_name

    @property
    def user_id(self):
        return self.__certificat.get_user_id

    def recevoir_lecture(self, message: MessageWrapper):
        parsed = message.parsed
        uuid_appareil = parsed['uuid_appareil']
        if self.uuid_appareil == uuid_appareil:
            pass  # Skip, ce sont des lectures internes de l'appareil
        else:
            # Verifier si on veut des lectures de cet appareil
            # TODO
            pass


class CorrelationRequeteCertificat(CorrelationHook):

    def __init__(self, cle_publique: str, message: dict):
        super().__init__()
        self.__cle_publique = cle_publique
        self.__message = message

    @property
    def message(self):
        return self.__message


class AppareilMessageHandler:

    def __init__(self, etat_senseurspassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__etat_senseurspassifs = etat_senseurspassifs
        self.__appareils = dict()
        self.__requetes_certificat = dict()

    def setup(self):
        pass

    async def entretien(self):
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

        # Tenter match par fingerprint
        try:
            self.__appareils[message.parsed['fingerprint']].put_message(message)
            self.__logger.debug("Routing message MQ appareil via fingerprint %s" % message.parsed['fingerprint'])
            return
        except KeyError:
            pass

        # Tenter match par cle_publique
        try:
            self.__requetes_certificat[message.parsed['cle_publique']].put_message(message)
            self.__logger.debug("Routing message MQ appareil via cle_publiquye %s" % message.parsed['cle_publique'])
            return
        except KeyError:
            pass

        action = message.routing_key.split('.').pop()
        user_id = message.parsed['en-tete']['partition']

        if action == 'lectureConfirmee':
            # Permettre a chaque appareil de l'usager de recevoir la lecture
            for app in self.__appareils.values():
                if app.user_id == user_id:
                    app.recevoir_lecture(message)
        elif action in ['evenementMajDisplays']:
            try:
                uuid_appareil = message.parsed['uuid_appareil']
                for app in self.__appareils.values():
                    if app.uuid_appareil == uuid_appareil and app.user_id == user_id:
                        app.put_message(message)
                        return
            except KeyError:
                pass

        self.__logger.warning("Message MQ sans match appareil")

    async def demande_certificat(self, message: dict):
        cle_publique = message['en-tete']['cle_publique']
        try:
            requete = self.__requetes_certificat[cle_publique]
            requete.touch()
        except KeyError:
            if len(self.__requetes_certificat) >= MAX_REQUETES_CERTIFICAT:
                raise Exception('Trop de requetes en attente')

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
        producer = self.__etat_senseurspassifs.producer
        commande = {
            'uuid_appareil': message['uuid_appareil'],
            'instance_id': self.__etat_senseurspassifs.instance_id,
            'user_id': message['user_id'],
            'cle_publique': cle_publique,
            'csr': message['csr'],
        }
        try:
            reponse = await producer.executer_commande(commande, 'SenseursPassifs', 'inscrireAppareil', Constantes.SECURITE_PRIVE)
            reponse_parsed = reponse.parsed
            if reponse_parsed.get('certificat') or reponse_parsed.get('challenge'):
                return reponse
        except Exception:
            # Attendre la reponse - raise timeout
            self.__logger.exception("Erreur commande inscrireAppareil")

        return await requete.get_reponse(timeout=60)

    async def enregistrer_appareil(self, certificat: EnveloppeCertificat) -> CorrelationAppareil:
        fingerprint = certificat.fingerprint

        appareil = self.__appareils.get(fingerprint)
        if appareil is None:
            appareil = CorrelationAppareil(certificat)
            self.__appareils[fingerprint] = appareil

        appareil.touch()

        return appareil



