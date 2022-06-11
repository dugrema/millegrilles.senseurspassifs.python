import asyncio
import logging
import signal

from senseurspassifs_rpi.ApplicationRpi import ApplicationRpi


async def initialiser_application():
    logging.basicConfig()

    app = ApplicationRpi()

    args = app.parse()
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


async def demarrer():
    logger = logging.getLogger(__name__)

    logger.info("Setup app")
    app = await initialiser_application()
    # await app.preparer_modules()

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
