import asyncio

from senseurspassifs_relai_web.ApplicationRelaiWeb import demarrer


def main():
    """
    Methode d'execution de l'application
    :return:
    """
    asyncio.run(demarrer())


if __name__ == '__main__':
    main()
