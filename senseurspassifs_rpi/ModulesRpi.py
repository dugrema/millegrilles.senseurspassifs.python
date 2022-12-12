import argparse
import asyncio
import logging
import json
import time

from typing import Optional

from millegrilles_senseurspassifs.AffichagePassif import ModuleAfficheLignes
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs.AppareilModule import AppareilHandler, SenseurModuleProducerAbstract


class RpiModuleHandler(AppareilHandler):

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        super().__init__(etat_senseurspassifs)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

    async def preparer_modules(self, args: argparse.Namespace):
        await super().preparer_modules(args)

        if args.lcd2lines is True:
            self.__logger.info("Activer LCD 2 lignes via TWI")
            affichage_lcd = await asyncio.to_thread(AffichageLCD2Lignes, self, self._etat_senseurspassifs,
                                                    'LCD2LignesTWI', args.timezone)
            self._modules_consumer.append(affichage_lcd)

        if args.dht is not None:
            pin = args.dht
            senseur_dht = SenseurDHT(self, self._etat_senseurspassifs, pin, self.traiter_lecture_interne)
            self._modules_producer.append(senseur_dht)

        if args.rf24hub is True:
            env_rf24 = args.rf24env
            rf24_hub = SenseurRF24(self, self._etat_senseurspassifs, self.traiter_lecture_interne, env_rf24)
            self._modules_producer.append(rf24_hub)


class AffichageLCD2Lignes(ModuleAfficheLignes):

    def __init__(self, handler: AppareilHandler, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str,
                 timezone_horloge: Optional[str] = None):
        super().__init__(handler, etat_senseurspassifs, no_senseur, timezone_horloge)

        from senseurspassifs_rpi.RPiTWI import LcdHandler

        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__lcd_handler: Optional[LcdHandler] = None
        self._initialiser()

        self._rafraichissement_horloge = 0.25

    def _initialiser(self):
        from senseurspassifs_rpi.RPiTWI import LcdHandler
        self.__lcd_handler = LcdHandler()
        self.__lcd_handler.initialise()
        time.sleep(0.1)  # S'assurer de laisser le temps a l'initialisation
        self.__lcd_handler.set_backlight(False)

    async def activer_affichage(self):
        self.__logger.info("Activer affichage")
        await super().activer_affichage()
        await asyncio.to_thread(self.__lcd_handler.set_backlight, True)

    async def desactiver_affichage(self):
        self.__logger.info("Desactiver affichage")
        await super().desactiver_affichage()
        # await asyncio.to_thread(self.__lcd_handler.set_backlight, False)
        await asyncio.to_thread(self.__lcd_handler.close)
        self._event_affichage_actif.clear()  # Va bloquer thread d'affichage
        self._lignes_affichage = list()  # Clear affichage
        await self._afficher_page(list())

    async def fermer(self):
        # Vider contenu, fermer backlight
        await self.desactiver_affichage()
        try:
            await asyncio.sleep(0.1)  # Attendre fin thread LCD
        except asyncio.TimeoutError:
            pass

        try:
            # Cleanup final
            self._lignes_affichage = list()  # Clear affichage
            await self._afficher_page(list())
            await asyncio.sleep(0.2)  # Laisser LCD terminer
        except asyncio.TimeoutError:
            pass

    async def _afficher_page(self, page: list):
        """
        Methode qui effectue l'affichage d'une page
        :param page:
        :return:
        """
        # self.__logger.debug("Lignes a afficher pour la page:\n%s" % '\n'.join(page))
        try:
            await asyncio.to_thread(self.__afficher_page_thread, page)
        except Exception:
            self.__logger.exception("Erreur affichage page LCD")

    def __afficher_page_thread(self, page: list):
        from senseurspassifs_rpi.RPiTWI import LcdHandler
        positions_lcd = [LcdHandler.LCD_LINE_1, LcdHandler.LCD_LINE_2]
        page_copy = page.copy()
        for position in positions_lcd:
            try:
                ligne = page_copy.pop(0)
            except IndexError:
                ligne = ''  # Vider le contenu de la ligne

            self.__lcd_handler.lcd_string(ligne, position)


class SenseurDHT(SenseurModuleProducerAbstract):

    def __init__(self, handler: AppareilHandler, etat_senseurspassifs: EtatSenseursPassifs, pin: int, lecture_callback):
        instance_id = etat_senseurspassifs.instance_id
        no_senseur = '%s_DHT' % instance_id
        super().__init__(handler, etat_senseurspassifs, no_senseur, lecture_callback)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

        from senseurspassifs_rpi.AdafruitDHT import ThermometreAdafruitGPIO
        self._reader = ThermometreAdafruitGPIO(uuid_senseur=no_senseur, pin=pin)

    async def run(self):
        while True:
            try:
                lecture = await self._reader.lire()
                senseurs = lecture['senseurs']

                # Transmettre lecture
                await self.lecture(senseurs)
            except:
                self.__logger.exception("Erreur traitement DHT")
            finally:
                try:
                    await asyncio.sleep(10)
                except asyncio.TimeoutError:
                    pass


class SenseurRF24(SenseurModuleProducerAbstract):

    def __init__(self, handler: AppareilHandler, etat_senseurspassifs: EtatSenseursPassifs, lecture_callback, environnement='prod'):
        instance_id = etat_senseurspassifs.instance_id
        no_senseur = '%s_RF24' % instance_id
        super().__init__(handler, etat_senseurspassifs, no_senseur, lecture_callback)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

        idmg = etat_senseurspassifs.clecertificat.enveloppe.idmg

        from senseurspassifs_rpi.RF24Server import NRF24Server
        self._rf24_server = NRF24Server(idmg, environnement)
        self.__queue_messages: Optional[asyncio.Queue] = None
        self.__loop = None

    async def run(self):
        self.__loop = asyncio.get_event_loop()
        self.__queue_messages = asyncio.Queue(maxsize=50)
        self.__logger.info("SenseurRF24 start")
        self._rf24_server.start(self.callback_lecture)

        tasks = [
            asyncio.create_task(self.traiter_messages()),
        ]

        try:
            await asyncio.tasks.wait(tasks, return_when=asyncio.tasks.FIRST_COMPLETED)
        finally:
            self._rf24_server.fermer()

        self.__logger.info("SenseurRF24 end")

    async def fermer(self):
        self._rf24_server.fermer()

    def callback_lecture(self, message):
        self.__loop.call_soon_threadsafe(self.__queue_messages.put_nowait, message)

    async def traiter_messages(self):
        while True:
            lecture = await self.__queue_messages.get()
            self.__logger.debug("Lecture RF24 recue:\n%s" % json.dumps(lecture, indent=2))
            try:
                no_senseur = lecture['uuid_senseur']
                senseurs = lecture['senseurs']
                await self.lecture(senseurs, no_senseur=no_senseur)
            except Exception:
                self.__logger.exception("Erreur traitement message")
