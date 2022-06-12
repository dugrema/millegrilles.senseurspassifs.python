import argparse
import asyncio
import datetime
import io
import json
import logging
import random

from asyncio import Event, TimeoutError
from typing import Optional
from os import path, makedirs

from millegrilles_messages.messages import Constantes
from millegrilles_messages.messages.MessagesModule import MessageWrapper, MessageProducerFormatteur
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs import Constantes as ConstantesSenseursPassifs


class SenseurModuleHandler:

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self._etat_senseurspassifs = etat_senseurspassifs

        self._modules_consumer = list()
        self._modules_producer = list()

        self.__sink_fichier: Optional[io.TextIOBase] = None
        self.__q_lectures: Optional[asyncio.queues.Queue] = None

    async def preparer_modules(self, args: argparse.Namespace):
        self.__q_lectures = asyncio.queues.Queue(maxsize=20)

        if args.dummysenseurs is True:
            self.__logger.info("Activer dummy senseurs")
            self._modules_producer.append(DummyProducer(self, self._etat_senseurspassifs, 'dummy_1', self.traiter_lecture_interne))

        if args.dummylcd is True:
            self.__logger.info("Activer dummy LCD")
            self._modules_consumer.append(DummyConsumer(self, self._etat_senseurspassifs, 'dummy_lcd'))

    async def reload_configuration(self):
        path_logs = self._etat_senseurspassifs.configuration.lecture_log_directory
        makedirs(path_logs, exist_ok=True)

        path_fichier_log = path.join(path_logs, 'senseurs.jsonl')

        if self.__sink_fichier is not None:
            self.__sink_fichier.close()
        sink = open(path_fichier_log, 'a')
        self.__sink_fichier = sink

    async def run(self):
        # Creer une liste de tasks pour executer tous les modules
        tasks = [
            asyncio.create_task(self.traitement_lectures())
        ]

        if len(self._modules_consumer) == 0 and len(self._modules_producer) == 0:
            raise ValueError('Aucuns modules configure')

        for module in self._modules_consumer:
            tasks.append(asyncio.create_task(module.run()))

        for module in self._modules_producer:
            tasks.append(asyncio.create_task(module.run()))

        # Execution de la loop avec toutes les tasks
        self.__logger.info("Debut execution modules")
        await asyncio.tasks.wait(tasks, return_when=asyncio.tasks.FIRST_COMPLETED)
        self.__logger.info("Fin execution modules")

    async def fermer(self):
        for producer in self._modules_producer:
            try:
                await producer.fermer()
            except Exception:
                self.__logger.exception("Erreur fermeture producer")

    async def traitement_lectures(self):
        while True:
            message = await self.__q_lectures.get()
            self.__logger.debug("traitement_lectures %s" % message)

            if message.get('interne') is True and self.__sink_fichier is not None:
                # Sauvegarder lecture
                message_lectures = message['message']
                # senseurs = message_lectures['senseurs']

                json.dump(message_lectures, self.__sink_fichier)
                self.__sink_fichier.write('\n')  # Terminer la ligne
                self.__sink_fichier.flush()

                # Transmettre sur MQ
                await self.transmettre_lecture(message_lectures)

            elif message.get('confirmation') is True:
                pass  # Rien a faire

            for consumer in self._modules_consumer:
                await consumer.traiter(message)

    async def recevoir_confirmation_lecture(self, message: MessageWrapper):
        """
        Recoit tous les evenements de confirmation de lectures
        :param message:
        :return:
        """
        self.__logger.debug("recevoir_message Traiter dans chaque consumer %s" % message)

        message_interne = {
            'confirmation': True,
            'message': message,
        }

        await self.__q_lectures.put(message_interne)

    async def traiter_lecture_interne(self, no_senseur: str, lectures_senseurs: dict):

        message_interne = {
            'interne': True,
            'message': {
                'instance_id': self._etat_senseurspassifs.instance_id,
                'uuid_senseur': no_senseur,
                'senseurs': lectures_senseurs,
            }
        }

        # Sink vers fichier buffer interne
        await self.__q_lectures.put(message_interne)

    async def transmettre_lecture(self, message: dict):
        if self.producer is None:
            self.__logger.debug("Producer n'est pas pret, lecture n'est pas transmise")
            return

        event_producer = self.producer.producer_pret()
        await asyncio.wait_for(event_producer.wait(), 5)

        partition = self._etat_senseurspassifs.partition

        await self.producer.emettre_evenement(message, ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS,
                                              ConstantesSenseursPassifs.EVENEMENT_DOMAINE_LECTURE,
                                              partition=partition, exchanges=[Constantes.SECURITE_PRIVE])

    @property
    def producer(self):
        return self._etat_senseurspassifs.producer

    def get_routing_key_consumers(self) -> list:
        # Creer liste de routing keys (dedupe avec set)
        routing_keys = set()
        for consumer in self._modules_consumer:
            routing_keys.update(consumer.routing_keys())

        return list(routing_keys)


class SenseurModuleProducerAbstract:
    """
    Module de production de lectures
    """

    def __init__(self, handler: SenseurModuleHandler, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str, lecture_callback):
        self._handler = handler
        self._etat_senseurspassifs = etat_senseurspassifs
        self._no_senseur = no_senseur
        self.__lecture_callback = lecture_callback

    async def run(self):
        """
        Override pour executer une task d'entretien
        :return:
        """
        # Note : placeholder, aucun effet (wait forever) - override si necessaire
        await Event().wait()

    async def lecture(self, senseurs: dict):
        """
        Utiliser pour emettre une lecture.
        :param senseurs:
        :return:
        """
        await self.__lecture_callback(self._no_senseur, senseurs)

    async def fermer(self):
        pass


class SenseurModuleConsumerAbstract:
    """
    Module de reception de lectures (e.g. affichage LCD)
    """

    def __init__(self, handler: SenseurModuleHandler, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self._handler = handler
        self._etat_senseurspassifs = etat_senseurspassifs
        self._no_senseur = no_senseur
        self._configuration_hub: Optional[dict] = None

        self.__event_attente: Optional[Event] = None

    async def run(self):
        self.__event_attente = Event()

        # Chargement initial de configuration
        await self.charger_configuration()

        while self.__event_attente.is_set() is False:

            if self._configuration_hub is None:
                # Chargement initial de la configuration du hub
                configuration_hub = await self.get_configuration_hub()
                await self.appliquer_configuration(configuration_hub)
                await self.rafraichir()
            try:
                await asyncio.wait_for(self.__event_attente.wait(), 30)
            except TimeoutError:
                pass

    async def charger_configuration(self):
        configuration = self._etat_senseurspassifs.configuration
        path_config = path.join(configuration.senseurspassifs_path, 'dummyconsumer.%s.json' % self._no_senseur)
        try:
            with open(path_config, 'r') as fichier:
                await self.appliquer_configuration(json.load(fichier))
                await self.rafraichir()
        except FileNotFoundError:
            self.__logger.debug("Fichier %s n'est pas preset" % path_config)
        except json.decoder.JSONDecodeError:
            self.__logger.debug("Fichier %s est corrompu" % path_config)

    async def appliquer_configuration(self, configuration_hub: dict):
        self._configuration_hub = configuration_hub

        # Conserver sur disque
        configuration = self._etat_senseurspassifs.configuration
        path_config = path.join(configuration.senseurspassifs_path, 'dummyconsumer.%s.json' % self._no_senseur)
        with open(path_config, 'w') as fichier:
            json.dump(configuration_hub, fichier, indent=2)

    async def get_configuration_hub(self):
        producer: MessageProducerFormatteur = self._etat_senseurspassifs.producer
        if producer is not None:
            try:
                await asyncio.wait_for(producer.producer_pret().wait(), 5)

                requete = {'instance_id': self._etat_senseurspassifs.instance_id}
                configuration_hub = await producer.executer_requete(
                    requete, ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS,
                    ConstantesSenseursPassifs.REQUETE_GET_NOEUD, Constantes.SECURITE_PRIVE)

                return configuration_hub.parsed

            except TimeoutError:
                self.__logger.warning("get_configuration_hub Timeout producer - Echec requete configuration hub")

    async def traiter(self, message):
        raise NotImplementedError('Override')

    def routing_keys(self) -> list:
        raise NotImplementedError('Override')


class DummyProducer(SenseurModuleProducerAbstract):
    """
    Exemple de producer. Utilise --dummysenseur pour activer sur command line.
    """

    def __init__(self, handler: SenseurModuleHandler, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str, lecture_callback):
        super().__init__(handler, etat_senseurspassifs, no_senseur, lecture_callback)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

    async def run(self):
        event_attente = Event()
        while event_attente.is_set() is False:
            await self.__produire_lecture()
            try:
                await asyncio.wait_for(event_attente.wait(), 5)
            except TimeoutError:
                pass

    async def __produire_lecture(self):
        humidite = random.randrange(0, 1000) / 10
        temperature = random.randrange(-500, 500) / 10

        timestamp = int(datetime.datetime.now().timestamp())
        dict_message = {
            'dummy/temperature': {
                'valeur': round(temperature, 1),
                'timestamp': timestamp,
                'type': 'temperature',
            },
            'dummy/humidite': {
                'valeur': round(humidite, 1),
                'timestamp': timestamp,
                'type': 'humidite',
            }
        }

        self.__logger.debug("Produire lecture dummy %s" % dict_message)

        await self.lecture(dict_message)


class DummyConsumer(SenseurModuleConsumerAbstract):
    """
    Exemple de consumer. Utilise --dummylcd pour activer sur command line.
    """

    def __init__(self, handler: SenseurModuleHandler, etat_senseurspassifs, no_senseur: str):
        super().__init__(handler, etat_senseurspassifs, no_senseur)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

        self.__uuid_senseurs = list()

    async def appliquer_configuration(self, configuration_hub: dict):
        await super().appliquer_configuration(configuration_hub)

        # Maj liste de senseurs utilise par ce consumer
        self.__uuid_senseurs = self.get_uuid_senseurs()

    async def traiter(self, message):
        self.__logger.debug("DummyConsumer Traiter message %s" % message)
        # Matcher message pour ce senseur
        if message.get('interne') is True:
            message_recu = message['message']
            action = 'lecture'
        elif message.get('confirmation') is True:
            message_wrapper = message['message']
            routing_key = message_wrapper.routing_key
            action = routing_key.split('.').pop()
            message_recu = message_wrapper.parsed
        else:
            return

        if action in ['lecture', 'lectureConfirmee']:
            if message_recu.get('uuid_senseur') in self.__uuid_senseurs:
                senseurs = message_recu['senseurs']
                self.__logger.info("DummyConsumer recu lecture %s" % senseurs)
        elif action == 'majNoeud':
            self.__logger.debug("Remplacement configuration noeud avec %s" % message_recu)
            await self.appliquer_configuration(message_recu)

    def routing_keys(self) -> list:
        """
        :return: list de routing keys utilisees par ce module
        """
        return [
            'evenement.SenseursPassifs.lectureConfirmee',
            'evenement.SenseursPassifs.%s.majNoeud' % self._etat_senseurspassifs.instance_id,
        ]

    def get_uuid_senseurs(self) -> list:
        if self._configuration_hub is None:
            return list()

        try:
            lignes = self._configuration_hub['lcd_affichage']
        except KeyError:
            return list()

        uuid_senseurs = set()
        for ligne in lignes:
            try:
                uuid_senseurs.add(ligne['uuid'])
            except KeyError:
                pass

        return list(uuid_senseurs)

    async def rafraichir(self):
        producer: MessageProducerFormatteur = self._etat_senseurspassifs.producer
        if producer is not None and len(self.__uuid_senseurs) > 0:
            try:
                await asyncio.wait_for(producer.producer_pret().wait(), 5)

                requete_noeuds = {}
                liste_noeuds_wrapper = await producer.executer_requete(
                    requete_noeuds, ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS,
                    ConstantesSenseursPassifs.REQUETE_LISTE_NOEUDS, Constantes.SECURITE_PRIVE)
                liste_noeuds = liste_noeuds_wrapper.parsed['noeuds']
                instance_ids = [u['instance_id'] for u in liste_noeuds]

                for instance_id in instance_ids:
                    requete = {'uuid_senseurs': self.__uuid_senseurs}
                    senseurs_wrapper = await producer.executer_requete(
                        requete, ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS,
                        ConstantesSenseursPassifs.REQUETE_LISTE_SENSEURS_PAR_UUID, Constantes.SECURITE_PRIVE,
                        partition=instance_id)
                    senseurs = senseurs_wrapper.parsed['senseurs']
                    for senseur in senseurs:
                        # Emettre message senseur comme message interne
                        uuid_senseur = senseur['uuid_senseur']
                        lectures_senseurs = senseur['senseurs']
                        await self._handler.traiter_lecture_interne(uuid_senseur, lectures_senseurs)

                pass

            except TimeoutError:
                self.__logger.warning("get_configuration_hub Timeout producer - Echec requete configuration hub")
