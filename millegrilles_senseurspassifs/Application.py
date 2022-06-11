import argparse
import asyncio
import datetime
import logging
import signal

from asyncio import Event, AbstractEventLoop, TimeoutError
from typing import Optional

from millegrilles_senseurspassifs.Configuration import ConfigurationSenseursPassifs
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs.RabbitMQDao import RabbitMQDao
from millegrilles_senseurspassifs.SenseursModule import SenseurModuleHandler
from millegrilles_senseurspassifs.ModulesBase import ModuleHandlerBase


class ApplicationInstance:

    def __init__(self):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

        self.__configuration = ConfigurationSenseursPassifs()
        self._etat_senseurspassifs = EtatSenseursPassifs(self.__configuration)

        # self.__module_entretien_rabbitmq: Optional[EntretienRabbitMq] = None
        # self.__tache_rabbitmq = TacheEntretien(datetime.timedelta(seconds=30), self.entretien_rabbitmq)

        self.__loop: Optional[AbstractEventLoop] = None
        self._stop_event: Optional[Event] = None  # Evenement d'arret global de l'application

        self.__rabbitmq_dao: Optional[RabbitMQDao] = None
        self._senseur_modules_handler = self.init_module_handler()

    def init_module_handler(self):
        # return SenseurModuleHandler(self.__etat_senseurspassifs)
        return ModuleHandlerBase(self._etat_senseurspassifs)

    def parse(self):
        parser = argparse.ArgumentParser(description="Demarrer l'application Senseurs Passifs de MilleGrilles")

        self._add_arguments(parser)

        args = parser.parse_args()
        if args.verbose:
            self.__logger.setLevel(logging.DEBUG)
            logging.getLogger('senseurspassifs_rpi').setLevel(logging.DEBUG)

        self.__logger.debug("args : %s" % args)

        return args

    def _add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            '--verbose', action="store_true", required=False,
            help="Active le logging maximal"
        )
        parser.add_argument(
            '--timezone', type=str, required=False,
            help="Timezone pytz pour l'horloge, ex: America/Halifax"
        )
        parser.add_argument(
            '--dummysenseurs', action="store_true", required=False,
            help="Initalise un emetteur de lecture dummy, pour tester la connexion (debug)"
        )
        parser.add_argument(
            '--dummylcd', action="store_true", required=False,
            help="Initalise un affichage dummy vers logs, pour tester AffichagesPassifs (debug)"
        )
        parser.add_argument(
            '--affichagelog', action="store_true", required=False,
            help="Initialise un affichage senseurs dans logging (debug)"
        )

    async def charger_configuration(self, args: argparse.Namespace):
        """
        Charge la configuration d'environnement (os.env)
        :return:
        """
        self.__logger.info("Charger la configuration")
        self.__loop = asyncio.get_event_loop()
        self._stop_event = Event()
        self.__configuration.parse_config(args.__dict__)

        self._etat_senseurspassifs.ajouter_listener(self._senseur_modules_handler.reload_configuration)

        await self._etat_senseurspassifs.reload_configuration()

        # self.__module_entretien_rabbitmq = EntretienRabbitMq(self.__etat_midcompte)
        # self.__etat_midcompte.ajouter_listener(self.__module_entretien_rabbitmq)

        await self._senseur_modules_handler.preparer_modules(args)

        self.__rabbitmq_dao = RabbitMQDao(self._stop_event, self._etat_senseurspassifs, self._senseur_modules_handler)

        self.__logger.info("charger_configuration prete")

    def exit_gracefully(self, signum=None, frame=None):
        self.__logger.info("Fermer application, signal: %d" % signum)
        self.__loop.call_soon_threadsafe(self._stop_event.set)

    async def fermer(self):
        self._stop_event.set()

    async def entretien_comptes(self):
        self.__logger.debug("entretien_comptes")

    async def entretien(self):
        self.__logger.info("entretien thread debut")

        while self._stop_event.is_set() is False:
            self.__logger.debug("run() debut execution cycle")

            # await self.__tache_rabbitmq.run()

            try:
                self.__logger.debug("run() fin execution cycle")
                await asyncio.wait_for(self._stop_event.wait(), 10)
            except TimeoutError:
                pass

        self.__logger.info("entretien thread fin")

    async def executer(self):
        """
        Boucle d'execution principale
        :return:
        """

        tasks = [
            asyncio.create_task(self.entretien()),
            asyncio.create_task(self.__rabbitmq_dao.run()),
            asyncio.create_task(self._senseur_modules_handler.run())
        ]

        # Execution de la loop avec toutes les tasks
        await asyncio.tasks.wait(tasks, return_when=asyncio.tasks.FIRST_COMPLETED)
