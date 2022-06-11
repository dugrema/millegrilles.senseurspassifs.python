import asyncio

from senseurspassifs_rpi.AdafruitDHT import ThermometreAdafruitGPIO


class testAM2302:

    def __init__(self):
        # Note: garage pin=24, cuisine=18
        self._reader = ThermometreAdafruitGPIO(uuid_senseur='DummyDHT', pin=27)

    async def test_lire1(self):
        lecture = await self._reader.lire()
        print("Resultat lecture: %s" % lecture)


async def test():
    test = testAM2302()
    await test.test_lire1()


def main():
    print("Demarrage test")
    asyncio.run(test())
    print("Main termine")


if __name__ == '__main__':
    main()
