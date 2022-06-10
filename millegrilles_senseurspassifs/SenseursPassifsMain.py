import argparse
import asyncio
import datetime
import logging
import signal

from asyncio import Event, AbstractEventLoop, TimeoutError
from typing import Optional

from millegrilles_messages.docker.Entretien import TacheEntretien
from millegrilles_senseurspassifs.Configuration import ConfigurationSenseursPassifs
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs


class ApplicationInstance:

    def __init__(self):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

        self.__configuration = ConfigurationSenseursPassifs()
        self.__etat_midcompte = EtatSenseursPassifs(self.__configuration)

        # self.__module_entretien_rabbitmq: Optional[EntretienRabbitMq] = None
        # self.__tache_rabbitmq = TacheEntretien(datetime.timedelta(seconds=30), self.entretien_rabbitmq)

        self.__loop: Optional[AbstractEventLoop] = None
        self._stop_event: Optional[Event] = None  # Evenement d'arret global de l'application

    async def charger_configuration(self, args: argparse.Namespace):
        """
        Charge la configuration d'environnement (os.env)
        :return:
        """
        self.__logger.info("Charger la configuration")
        self.__loop = asyncio.get_event_loop()
        self._stop_event = Event()
        self.__configuration.parse_config(args.__dict__)
        await self.__etat_midcompte.reload_configuration()

        # self.__module_entretien_rabbitmq = EntretienRabbitMq(self.__etat_midcompte)
        # self.__etat_midcompte.ajouter_listener(self.__module_entretien_rabbitmq)

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
            # asyncio.create_task(self.__web_server.run(self._stop_event))
        ]

        # Execution de la loop avec toutes les tasks
        await asyncio.tasks.wait(tasks, return_when=asyncio.tasks.FIRST_COMPLETED)


async def initialiser_application():
    logging.basicConfig()

    app = ApplicationInstance()

    args = parse()
    if args.verbose:
        logging.getLogger('millegrilles_messages').setLevel(logging.DEBUG)
        logging.getLogger('millegrilles_senseurspassifs').setLevel(logging.DEBUG)
        logging.getLogger('__main__').setLevel(logging.DEBUG)
    else:
        logging.getLogger('millegrilles_messages').setLevel(logging.WARN)
        logging.getLogger('millegrilles_senseurspassifs').setLevel(logging.WARN)

    await app.charger_configuration(args)

    signal.signal(signal.SIGINT, app.exit_gracefully)
    signal.signal(signal.SIGTERM, app.exit_gracefully)
    # signal.signal(signal.SIGHUP, app.reload_configuration)

    return app


def parse():
    logger = logging.getLogger(__name__ + '.parse')
    parser = argparse.ArgumentParser(description="Demarrer l'application Senseurs Passifs de MilleGrilles")

    parser.add_argument(
        '--verbose', action="store_true", required=False,
        help="Active le logging maximal"
    )

    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    logger.debug("args : %s" % args)

    return args


async def demarrer():
    logger = logging.getLogger(__name__)

    logger.info("Setup app")
    app = await initialiser_application()
    # await app.preparer_environnement()

    try:
        logger.info("Debut execution app")
        await app.executer()
    except KeyboardInterrupt:
        logger.info("Arret execution app via signal (KeyboardInterrupt), fin thread main")
    except:
        logger.exception("Exception durant execution app, fin thread main")
    finally:
        logger.info("Fin execution app")
        await app.fermer()  # S'assurer de mettre le flag de stop_event


def main():
    """
    Methode d'execution de l'application
    :return:
    """
    asyncio.run(demarrer())


if __name__ == '__main__':
    main()
