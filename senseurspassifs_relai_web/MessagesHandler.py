# Effectue la correlation des messages pour appareils web
import asyncio
import datetime

from millegrilles_messages.messages import Constantes

from millegrilles_messages.messages.EnveloppeCertificat import EnveloppeCertificat

MAX_REQUETES_CERTIFICAT = 5
EXPIRATION_APPAREIL = datetime.timedelta(minutes=10)
EXPIRATION_REQUETE_CERTIFICAT = datetime.timedelta(minutes=30)


class AppareilMessageHandler:

    def __init__(self, etat_senseurspassifs):
        self.__etat_senseurspassifs = etat_senseurspassifs
        self.__appareils = dict()
        self.__requetes_certificat = dict()

    def setup(self):
        pass

    async def entretien(self):
        for fingerprint, appareil in enumerate(self.__appareils.items()):
            if appareil.expire():
                del self.__appareils[fingerprint]

    async def demande_certificat(self, message: dict):
        cle_publique = message['en-tete']['cle_publique']
        try:
            requete = self.__requetes_certificat[cle_publique]
            reponse = await requete.get_reponse(timeout=None)
            if reponse is not None:
                # Reponse deja recue, on a transmet
                return reponse
        except asyncio.QueueEmpty:
            pass
        except KeyError:
            if len(self.__requetes_certificat) >= MAX_REQUETES_CERTIFICAT:
                raise Exception('Trop de requetes en attente')

            # Conserver nouvelle requete
            requete = CorrelationRequeteCertificat(cle_publique, message)
            self.__requetes_certificat[cle_publique] = requete

        # Emettre commande certificat vers SenseursPassifs, attendre reponse
        # todo emettre commande
        producer = self.__etat_senseurspassifs.producer
        commande = {
            'cn': message['cn'],
            'cle_publique': cle_publique,
        }
        try:
            reponse = await producer.executer_commande(commande, 'SenseursPassifs', 'inscrire', Constantes.SECURITE_PRIVE)
            return reponse
        except:
            # Attendre la reponse - raise timeout
            return await requete.get_reponse(timeout=2)

    async def enregistrer_appareil(self, certificat: EnveloppeCertificat):
        fingerprint = certificat.fingerprint
        appareil = self.__appareils.get(fingerprint)
        if appareil is None:
            appareil = CorrelationAppareil(certificat)
            self.__appareils[fingerprint] = appareil
        appareil.touch()


class CorrelationAppareil:
    """
    Queue de reception de messages pour un appareil
    """

    def __init__(self, certificat: EnveloppeCertificat):
        self.__derniere_activite = datetime.datetime.utcnow()
        self.__certificat = certificat
        self.__messages = asyncio.Queue(5)

    def touch(self):
        self.__derniere_activite = datetime.datetime.utcnow()

    @property
    def expire(self):
        return datetime.datetime.utcnow() - self.__derniere_activite > EXPIRATION_APPAREIL

    async def get_message(self, timeout=60):
        """
        Retourne un message. Attend max timeout si Q vide.
        :param timeout:
        :return:
        """
        return await asyncio.wait_for(self.__messages.get(), timeout)


class CorrelationRequeteCertificat:

    def __init__(self, cle_publique: str, message: dict):
        self.__derniere_activite = datetime.datetime.utcnow()
        self.__cle_publique = cle_publique
        self.__message = message
        self.__reponse = asyncio.Queue(1)
        self.__reponse_consommee = False

    def touch(self):
        self.__derniere_activite = datetime.datetime.utcnow()

    @property
    def expire(self):
        return datetime.datetime.utcnow() - self.__derniere_activite > EXPIRATION_REQUETE_CERTIFICAT

    @property
    def message(self):
        return self.__message

    async def get_reponse(self, timeout=60):
        if timeout is None:
            reponse = self.__reponse.get_nowait()
        else:
            reponse = await asyncio.wait_for(self.__reponse.get(), timeout)

        if reponse is not None:
            self.__reponse_consommee = True

        return reponse
