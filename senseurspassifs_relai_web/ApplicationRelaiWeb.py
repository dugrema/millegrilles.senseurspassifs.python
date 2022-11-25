import argparse
import asyncio
import logging
import signal

from millegrilles_senseurspassifs.Application import ApplicationInstance
from senseurspassifs_relai_web.ModulesRelaiWeb import RelaiWebModuleHandler


class ApplicationRelaiWeb(ApplicationInstance):

    def init_module_handler(self):
        return RelaiWebModuleHandler(self._etat_senseurspassifs)

    def _add_arguments(self, parser: argparse.ArgumentParser):
        super()._add_arguments(parser)
        # parser.add_argument(
        #     '--lcd2lines', action="store_true", required=False,
        #     help="Initialise l'affichage LCD 2 lignes via TWI (I2C)"
        # )


async def initialiser_application():
    logging.basicConfig()

    app = ApplicationRelaiWeb()

    args = app.parse()
    if args.verbose:
        logging.getLogger('millegrilles_messages').setLevel(logging.DEBUG)
        logging.getLogger('millegrilles_senseurspassifs').setLevel(logging.DEBUG)
        logging.getLogger('senseurspassifs_relai_web').setLevel(logging.DEBUG)
        logging.getLogger('__main__').setLevel(logging.DEBUG)
    else:
        logging.getLogger('millegrilles_messages').setLevel(logging.WARN)
        logging.getLogger('millegrilles_senseurspassifs').setLevel(logging.WARN)
        logging.getLogger('senseurspassifs_relai_web').setLevel(logging.WARN)

    await app.charger_configuration(args)

    signal.signal(signal.SIGINT, app.exit_gracefully)
    signal.signal(signal.SIGTERM, app.exit_gracefully)
    # signal.signal(signal.SIGHUP, app.reload_configuration)

    return app


async def demarrer():
    logger = logging.getLogger(__name__)

    logger.info("Setup app")
    app = await initialiser_application()

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
