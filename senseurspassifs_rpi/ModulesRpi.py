import argparse
import asyncio

from typing import Optional

from millegrilles_senseurspassifs.AffichagePassif import ModuleAfficheLignes
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs.SenseursModule import SenseurModuleHandler

from senseurspassifs_rpi.RPiTWI import LcdHandler


class RpiModuleHandler(SenseurModuleHandler):

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        super().__init__(etat_senseurspassifs)

    async def preparer_modules(self, args: argparse.Namespace):
        await super().preparer_modules(args)

        if args.lcd2lines is True:
            self.__logger.info("Activer LCD 2 lignes via TWI")
            affichage_lcd = await asyncio.to_thread(AffichageLCD2Lignes, self, self._etat_senseurspassifs, 'LCD2LignesTWI')
            self._modules_producer.append(affichage_lcd)


class AffichageLCD2Lignes(ModuleAfficheLignes):

    def __init__(self, handler: SenseurModuleHandler, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str):
        super().__init__(handler, etat_senseurspassifs, no_senseur)
        self.__lcd_handler: Optional[LcdHandler] = None
        self._initialiser()

    def _initialiser(self):
        self.__lcd_handler = LcdHandler()
        self.__lcd_handler.initialise()

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
