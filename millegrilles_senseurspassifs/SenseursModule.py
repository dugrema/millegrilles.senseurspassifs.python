import argparse
import asyncio
import datetime
import logging
import random

from asyncio import Event, TimeoutError
from typing import Optional

from millegrilles_messages.messages import Constantes
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs import Constantes as ConstantesSenseursPassifs


class SenseurModuleHandler:

    def __init__(self, etat_senseurspassifs):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__etat_senseurspassifs = etat_senseurspassifs

        self.__modules_consumer = list()
        self.__modules_producer = list()

    async def preparer_modules(self, args: argparse.Namespace):
        if args.dummysenseurs is True:
            self.__logger.info("Activer dummy senseurs")
            self.__modules_consumer.append(DummyProducer(self.__etat_senseurspassifs, 'dummy_1'))

        if args.dummylcd is True:
            self.__logger.info("Activer dummy LCD")
            raise NotImplementedError('todo')

    async def run(self):
        # Creer une liste de tasks pour executer tous les modules
        tasks = list()

        for module in self.__modules_consumer:
            tasks.append(asyncio.create_task(module.run()))

        for module in self.__modules_producer:
            tasks.append(asyncio.create_task(module.run()))

        if len(tasks) == 0:
            raise ValueError('Aucuns modules configure')

        # Execution de la loop avec toutes les tasks
        self.__logger.info("Debut execution modules")
        await asyncio.tasks.wait(tasks, return_when=asyncio.tasks.FIRST_COMPLETED)
        self.__logger.info("Fin execution modules")

    async def recevoir_confirmation_lecture(self, message):
        """
        Recoit tous les evenements de confirmation de lectures
        :param message:
        :return:
        """
        self.__logger.debug("recevoir_message Traiter dans chaque consumer %s" % message)
        for consumer in self.__modules_consumer:
            await consumer.traiter(message)


class SenseurModuleProducerAbstract:
    """
    Module de production de lectures
    """

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str):
        self._etat_senseurspassifs = etat_senseurspassifs
        self._no_senseur = no_senseur
        self._event_stop: Optional[Event] = None

    @property
    def producer(self):
        return self._etat_senseurspassifs.producer

    async def run(self):
        """
        Override pour executer une task d'entretien
        :return:
        """
        # Note : placeholder, aucun effet (wait forever) - override si necessaire
        await self._event_stop.wait()

    async def transmettre_lecture(self, lectures_senseurs: dict):
        message = {
            'instance_id': self._etat_senseurspassifs.instance_id,
            'uuid_senseur': self._no_senseur,
            'senseurs': lectures_senseurs,
        }

        event_producer = self.producer.producer_pret()
        await asyncio.wait_for(event_producer.wait(), 5)

        partition = self._etat_senseurspassifs.partition

        await self.producer.emettre_evenement(message, ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS,
                                              ConstantesSenseursPassifs.EVENEMENT_DOMAINE_LECTURE,
                                              partition=partition, exchanges=[Constantes.SECURITE_PRIVE])


class SenseurModuleConsumerAbstract:
    """
    Module de reception de lectures (e.g. affichage LCD)
    """

    def __init__(self):
        pass

    def traiter(self, message):
        pass


class DummyProducer(SenseurModuleProducerAbstract):

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str):
        super().__init__(etat_senseurspassifs, no_senseur)
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

        await self.transmettre_lecture(dict_message)
