import asyncio

from millegrilles_senseurspassifs.SenseursPassifsMain import demarrer


def main():
    """
    Methode d'execution de l'application
    :return:
    """
    asyncio.run(demarrer())


if __name__ == '__main__':
    main()
