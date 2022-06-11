import asyncio
import logging

from senseurspassifs_rpi.RF24Server import NRF24Server


class RF24Test:

    def __init__(self):
        self.__logger = logging.getLogger(__name__ + "." + self.__class__.__name__)
        self.rf24_server = NRF24Server('zeYncRqEqZ6eTEmUZ8whJFuHG796eSvCTWE4M432izXrp22bAtwGm7Jf', 'dev')

    async def run(self):
        self.rf24_server.set_callback_lecture(self.callback_lecture)
        await self.rf24_server.run()

    async def callback_lecture(self, message):
        self.__logger.info("callback_lecture: Message recu\n%s" % message)


async def test():
    test = RF24Test()
    await asyncio.wait_for(test.run(), 120)


def main():
    print("Demarrage test")
    asyncio.run(test())
    print("Main termine")


if __name__ == '__main__':
    main()


