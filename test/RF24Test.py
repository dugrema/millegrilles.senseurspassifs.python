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
        self.__queue_messages: Optional[asyncio.Queue] = None

    async def run(self):
        self.__queue_messages = asyncio.Queue(maxsize=50)
        self.__logger.info("Debut run")
        self.rf24_server.start(self.callback_lecture)

        tasks = [
            asyncio.create_task(self.traiter_messages()),
            asyncio.create_task(asyncio.sleep(120)),
        ]

        await asyncio.tasks.wait(tasks, return_when=asyncio.tasks.FIRST_COMPLETED)

        self.__logger.info("Fin run")

    def callback_lecture(self, message):
        self.__queue_messages.put_nowait(message)

    async def traiter_messages(self):
        while True:
            message = await self.__queue_messages.get()
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


