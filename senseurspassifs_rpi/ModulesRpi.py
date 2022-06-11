import argparse
import asyncio
import logging

from typing import Optional

from millegrilles_senseurspassifs.AffichagePassif import ModuleAfficheLignes
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs.SenseursModule import SenseurModuleHandler, SenseurModuleProducerAbstract

from senseurspassifs_rpi.RPiTWI import LcdHandler
from senseurspassifs_rpi.AdafruitDHT import ThermometreAdafruitGPIO


class RpiModuleHandler(SenseurModuleHandler):

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        super().__init__(etat_senseurspassifs)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

    async def preparer_modules(self, args: argparse.Namespace):
        await super().preparer_modules(args)

        if args.lcd2lines is True:
            self.__logger.info("Activer LCD 2 lignes via TWI")
            affichage_lcd = await asyncio.to_thread(AffichageLCD2Lignes, self, self._etat_senseurspassifs, 'LCD2LignesTWI')
            self._modules_consumer.append(affichage_lcd)

        if args.dht is not None:
            pin = args.dht
            senseur_dht = SenseurDHT(self, self._etat_senseurspassifs, pin, self.traiter_lecture_interne)
            self._modules_producer.append(senseur_dht)


class AffichageLCD2Lignes(ModuleAfficheLignes):

    def __init__(self, handler: SenseurModuleHandler, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str):
        super().__init__(handler, etat_senseurspassifs, no_senseur)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__lcd_handler: Optional[LcdHandler] = None
        self._initialiser()

    def _initialiser(self):
        self.__lcd_handler = LcdHandler()
        self.__lcd_handler.initialise()
        self.__lcd_handler.set_backlight(False)

    async def activer_affichage(self):
        self.__logger.info("Activer affichage")
        await asyncio.to_thread(self.__lcd_handler.set_backlight, True)

    async def desactiver_affichage(self):
        self.__logger.info("Desactiver affichage")
        await asyncio.to_thread(self.__lcd_handler.set_backlight, False)
        self.__event_affichage_actif.clear()
        self.__lignes_affichage = list()  # Clear affichage

    async def _afficher_page(self, page: list):
        """
        Methode qui effectue l'affichage d'une page
        :param page:
        :return:
        """
        self.__logger.info("Lignes a afficher pour la page:\n%s" % '\n'.join(page))
        positions_lcd = [LcdHandler.LCD_LINE_1, LcdHandler.LCD_LINE_2]
        page_copy = page.copy()
        for position in positions_lcd:
            try:
                ligne = page_copy.pop(0)
            except IndexError:
                ligne = ''  # Vider le contenu de la ligne

            self.__lcd_handler.lcd_string(ligne, position)


class SenseurDHT(SenseurModuleProducerAbstract):

    def __init__(self, handler: SenseurModuleHandler, etat_senseurspassifs: EtatSenseursPassifs, pin: int, lecture_callback):
        instance_id = etat_senseurspassifs.instance_id
        no_senseur = '%s_DHT' % instance_id
        super().__init__(handler, etat_senseurspassifs, no_senseur, lecture_callback)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
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

