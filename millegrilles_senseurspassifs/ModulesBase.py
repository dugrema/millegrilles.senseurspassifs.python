import argparse
import logging

from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs.AppareilModule import AppareilHandler
from millegrilles_senseurspassifs.AffichagePassif import ModuleAfficheLignes


class AppareilHandlerBase(AppareilHandler):

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
        super().__init__(etat_senseurspassifs)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

    async def preparer_modules(self, args: argparse.Namespace):
        await super().preparer_modules(args)

        if args.affichagelog is True:
            self.__logger.info("Activer ModuleAffichageLignes")
            self._modules_consumer.append(ModuleAfficheLignes(self, self._etat_senseurspassifs, 'affichagelignes',
                                                              args.timezone))

