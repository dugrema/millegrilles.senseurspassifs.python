import json
import logging

from asyncio import Event
from typing import Optional

from millegrilles_messages.messages.CleCertificat import CleCertificat
from millegrilles_messages.messages.EnveloppeCertificat import EnveloppeCertificat
from millegrilles_messages.messages.FormatteurMessages import SignateurTransactionSimple, FormatteurMessageMilleGrilles
from millegrilles_messages.messages.ValidateurCertificats import ValidateurCertificatCache
from millegrilles_messages.messages.ValidateurMessage import ValidateurMessage
from millegrilles_senseurspassifs.Configuration import ConfigurationSenseursPassifs
from millegrilles_messages.messages.MessagesModule import MessageProducerFormatteur


class EtatSenseursPassifs:

    def __init__(self, configuration: ConfigurationSenseursPassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__configuration = configuration

        self.__configuration_json: Optional[dict] = None

        self.__instance_id: Optional[str] = None
        self.__mq_host: Optional[str] = None
        self.__mq_port: Optional[int] = None
        self.__clecertificat: Optional[CleCertificat] = None
        self.__certificat_millegrille: Optional[EnveloppeCertificat] = None

        self.__listeners_actions = list()

        self.__formatteur_message: Optional[FormatteurMessageMilleGrilles] = None
        self.__validateur_certificats: Optional[ValidateurCertificatCache] = None
        self.__validateur_message: Optional[ValidateurMessage] = None

        # self.__stop_event: Optional[Event] = None
        self.__producer: Optional[MessageProducerFormatteur] = None

    async def reload_configuration(self):
        self.__logger.info("Reload configuration sur disque ou dans docker")

        config_path = self.__configuration.config_path
        with open(config_path, 'r') as fichier:
            self.__configuration_json = json.load(fichier)

        self.__instance_id = self.__configuration_json['instance_id']

        self.__mq_host = self.__configuration.mq_host or self.__configuration_json.get('mq_host') or 'localhost'
        self.__mq_port = self.__configuration.mq_port or self.__configuration_json.get('mq_port') or 5673

        # Charger et verificat cle/certificat
        self.__clecertificat = CleCertificat.from_files(
            self.__configuration.key_pem_path, self.__configuration.cert_pem_path)

        self.__certificat_millegrille = EnveloppeCertificat.from_file(self.__configuration.ca_pem_path)

        if self.__clecertificat is not None:
            idmg = self.__clecertificat.enveloppe.idmg
            signateur = SignateurTransactionSimple(self.__clecertificat)
            self.__formatteur_message = FormatteurMessageMilleGrilles(idmg, signateur)
            self.__validateur_certificats = ValidateurCertificatCache(self.__certificat_millegrille)
            self.__validateur_message = ValidateurMessage(self.__validateur_certificats)

        for listener in self.__listeners_actions:
            await listener()

    def ajouter_listener(self, listener):
        self.__listeners_actions.append(listener)

    async def fermer(self):
        for listener in self.__listeners_actions:
            await listener(fermer=True)

    @property
    def configuration(self):
        return self.__configuration

    @property
    def clecertificat(self):
        return self.__clecertificat

    @property
    def instance_id(self):
        return self.__instance_id

    @property
    def mq_host(self):
        return self.__mq_host

    @property
    def mq_port(self):
        return self.__mq_port

    def set_producer(self, producer: MessageProducerFormatteur):
        self.__producer = producer

    @property
    def producer(self):
        return self.__producer