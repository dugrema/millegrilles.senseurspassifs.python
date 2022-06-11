import asyncio
import logging
import RPi.GPIO as GPIO

from typing import Optional

from senseurspassifs_rpi.RF24Server import NRF24Server


GPIO.setmode(GPIO.BCM)


class RF24Test:

    def __init__(self):
        self.__logger = logging.getLogger(__name__ + "." + self.__class__.__name__)
        self.rf24_server = NRF24Server('zeYncRqEqZ6eTEmUZ8whJFuHG796eSvCTWE4M432izXrp22bAtwGm7Jf', 'dev')
        self.__loop: Optional[asyncio.events.AbstractEventLoop] = None

    async def run(self):
        self.__loop = asyncio.get_event_loop()
        self.__logger.info("Debut run")
        self.rf24_server.start(self.callback_lecture)

        await asyncio.sleep(120)
        self.__logger.info("Fin run")

    def callback_lecture(self, message):
        self.__loop.call_soon_threadsafe(self.callback_async, message)

    async def callback_async(self, message):
        self.__logger.info("callback_lecture: Message recu\n%s" % message)


async def test():
    test = RF24Test()
    await test.run()


def main():
    logging.basicConfig()
    logging.getLogger(__name__).setLevel(logging.DEBUG)
    logging.getLogger('millegrilles_senseurspassifs').setLevel(logging.DEBUG)

    print("Demarrage test")
    asyncio.run(test())
    print("Main termine")


if __name__ == '__main__':
    main()


