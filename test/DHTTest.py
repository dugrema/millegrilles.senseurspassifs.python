from senseurspassifs_rpi.AdafruitDHT import ThermometreAdafruitGPIO


class testAM2302:

    def __init__(self):
        # Note: garage pin=24, cuisine=18
        self._reader = ThermometreAdafruitGPIO(uuid_senseur='DummyDHT', pin=27)

    def test_lire1(self):
        self._reader.lire()


def main():
    print("Demarrage test")
    test = testAM2302()
    test.test_lire1()
    print("Main termine")


if __name__ == '__main__':
    main()
