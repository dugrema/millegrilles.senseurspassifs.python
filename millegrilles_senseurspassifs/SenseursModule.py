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
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs import Constantes as ConstantesSenseursPassifs


class SenseurModuleHandler:

    def __init__(self, etat_senseurspassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__etat_senseurspassifs = etat_senseurspassifs

        self.__modules_consumer = list()
        self.__modules_producer = list()

        self.__sink_fichier: Optional[io.TextIOBase] = None
        self.__q_lectures: Optional[asyncio.queues.Queue] = None

    async def preparer_modules(self, args: argparse.Namespace):
        self.__q_lectures = asyncio.queues.Queue(maxsize=20)

        if args.dummysenseurs is True:
            self.__logger.info("Activer dummy senseurs")
            self.__modules_producer.append(DummyProducer(self.__etat_senseurspassifs, 'dummy_1', self.traiter_lecture_interne))

        if args.dummylcd is True:
            self.__logger.info("Activer dummy LCD")
            raise NotImplementedError('todo')

    async def reload_configuration(self):
        path_logs = self.__etat_senseurspassifs.configuration.lecture_log_directory
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

        if len(self.__modules_consumer) == 0 and len(self.__modules_producer) == 0:
            raise ValueError('Aucuns modules configure')

        for module in self.__modules_consumer:
            tasks.append(asyncio.create_task(module.run()))

        for module in self.__modules_producer:
            tasks.append(asyncio.create_task(module.run()))

        # Execution de la loop avec toutes les tasks
        self.__logger.info("Debut execution modules")
        await asyncio.tasks.wait(tasks, return_when=asyncio.tasks.FIRST_COMPLETED)
        self.__logger.info("Fin execution modules")

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

            for consumer in self.__modules_consumer:
                await consumer.traiter(message)

    async def recevoir_confirmation_lecture(self, message):
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
                'instance_id': self.__etat_senseurspassifs.instance_id,
                'uuid_senseur': no_senseur,
                'senseurs': lectures_senseurs,
            }
        }

        # Sink vers fichier buffer interne
        await self.__q_lectures.put(message_interne)

    async def transmettre_lecture(self, message: dict):
        event_producer = self.producer.producer_pret()
        await asyncio.wait_for(event_producer.wait(), 5)

        partition = self.__etat_senseurspassifs.partition

        await self.producer.emettre_evenement(message, ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS,
                                              ConstantesSenseursPassifs.EVENEMENT_DOMAINE_LECTURE,
                                              partition=partition, exchanges=[Constantes.SECURITE_PRIVE])

    @property
    def producer(self):
        return self.__etat_senseurspassifs.producer


class SenseurModuleProducerAbstract:
    """
    Module de production de lectures
    """

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str, lecture_callback):
        self._etat_senseurspassifs = etat_senseurspassifs
        self._no_senseur = no_senseur
        self.__lecture_callback = lecture_callback

        self._event_stop: Optional[Event] = None

    async def run(self):
        """
        Override pour executer une task d'entretien
        :return:
        """
        # Note : placeholder, aucun effet (wait forever) - override si necessaire
        await self._event_stop.wait()

    async def lecture(self, senseurs: dict):
        """
        Utiliser pour emettre une lecture.
        :param senseurs:
        :return:
        """
        await self.__lecture_callback(self._no_senseur, senseurs)


class SenseurModuleConsumerAbstract:
    """
    Module de reception de lectures (e.g. affichage LCD)
    """

    def __init__(self):
        pass

    def traiter(self, message):
        pass

    def routing_keys(self) -> list:
        raise NotImplementedError("Override")


class DummyProducer(SenseurModuleProducerAbstract):

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str, lecture_callback):
        super().__init__(etat_senseurspassifs, no_senseur, lecture_callback)
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
