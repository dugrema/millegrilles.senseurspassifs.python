import argparse
import asyncio
import datetime
import logging

from asyncio import Event, AbstractEventLoop, TimeoutError
from typing import Optional

from millegrilles_messages.docker.Entretien import TacheEntretien
from millegrilles_senseurspassifs.Configuration import ConfigurationSenseursPassifs
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs.RabbitMQDao import RabbitMQDao
from millegrilles_senseurspassifs.ModulesBase import AppareilHandlerBase
from millegrilles_senseurspassifs.SenseursLogHandler import SenseursLogHandler
from millegrilles_messages.messages.CleCertificat import CleCertificat


class ApplicationInstance:

    def __init__(self):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

        self.__configuration = ConfigurationSenseursPassifs()
        self._etat_senseurspassifs = EtatSenseursPassifs(self.__configuration)

        self.__loop: Optional[AbstractEventLoop] = None
        self._stop_event: Optional[Event] = None  # Evenement d'arret global de l'application

        self.__rabbitmq_dao: Optional[RabbitMQDao] = None
        self._senseur_modules_handler = self.init_module_handler()
        self.__senseurs_log_handler = SenseursLogHandler(self._etat_senseurspassifs, self._senseur_modules_handler)

        self.__taches = self.preparer_taches()

    def init_module_handler(self):
        # return SenseurModuleHandler(self.__etat_senseurspassifs)
        return AppareilHandlerBase(self._etat_senseurspassifs)

    def preparer_taches(self) -> list:
        taches = list()
        taches.append(TacheEntretien(datetime.timedelta(minutes=30), self.rotation_logs))
        taches.append(TacheEntretien(datetime.timedelta(minutes=5), self.verifier_expirations))
        return taches

    def parse(self):
        parser = argparse.ArgumentParser(description="Demarrer l'application Senseurs Passifs de MilleGrilles")

        self._add_arguments(parser)

        args = parser.parse_args()
        if args.verbose:
            self.__logger.setLevel(logging.DEBUG)
            logging.getLogger('senseurspassifs_rpi').setLevel(logging.DEBUG)

        self.__logger.debug("args : %s" % args)

        return args

    def _add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument(
            '--verbose', action="store_true", required=False,
            help="Active le logging maximal"
        )
        parser.add_argument(
            '--timezone', type=str, required=False,
            help="Timezone pytz pour l'horloge, ex: America/Halifax"
        )
        parser.add_argument(
            '--dummysenseurs', action="store_true", required=False,
            help="Initalise un emetteur de lecture dummy, pour tester la connexion (debug)"
        )
        parser.add_argument(
            '--dummylcd', action="store_true", required=False,
            help="Initalise un affichage dummy vers logs, pour tester AffichagesPassifs (debug)"
        )
        parser.add_argument(
            '--affichagelog', action="store_true", required=False,
            help="Initialise un affichage senseurs dans logging (debug)"
        )

    async def charger_configuration(self, args: argparse.Namespace):
        """
        Charge la configuration d'environnement (os.env)
        :return:
        """
        self.__logger.info("Charger la configuration")
        self.__loop = asyncio.get_event_loop()
        self._stop_event = Event()
        self.__configuration.parse_config(args.__dict__)

        self._etat_senseurspassifs.ajouter_listener(self._senseur_modules_handler.reload_configuration)
        await self._etat_senseurspassifs.reload_configuration()
        await self._senseur_modules_handler.preparer_modules(args)

        self.__rabbitmq_dao = RabbitMQDao(self._stop_event, self._etat_senseurspassifs, self._senseur_modules_handler)

        self.__logger.info("charger_configuration prete")

    def exit_gracefully(self, signum=None, frame=None):
        self.__logger.info("Fermer application, signal: %d" % signum)
        self.__loop.call_soon_threadsafe(self._stop_event.set)

    async def fermer(self):
        self._stop_event.set()
        await self._senseur_modules_handler.fermer()

    async def __attendre_fermer(self):
        await self._stop_event.wait()
        self.__logger.info("executer __attendre_fermer")
        await self.fermer()

    async def entretien_comptes(self):
        self.__logger.debug("entretien_comptes")

    async def rotation_logs(self):
        await self.__senseurs_log_handler.rotation_logs()

    async def verifier_expirations(self):
        """ Verifie l'expiration de la configuration, reload au besoin """
        reload = False
        try:
            enveloppe = self._etat_senseurspassifs.clecertificat.enveloppe
            date_expiration = enveloppe.not_valid_after
        except TypeError:
            self.__logger.warning("Certificat n'a pas ete charge, on tente un reload de la configuration")
            reload = True  # Certificat manquant
        else:
            try:
                # Charger le certificat sur disque pour verifier si on a une nouvelle version
                configuration = self._etat_senseurspassifs.configuration
                clecertificat_disque = CleCertificat.from_files(configuration.key_pem_path, configuration.cert_pem_path)
                if clecertificat_disque.cle_correspondent():
                    date_expiration_disque = clecertificat_disque.enveloppe.not_valid_after

                    if date_expiration_disque > date_expiration:
                        self.__logger.info("Nouveau certificat disponible, on remplace la configuration")
                        reload = True
            except Exception:
                self.__logger.exception("Erreur verification date expiration certificat local")

        if reload is True:
            await self._etat_senseurspassifs.reload_configuration()

    # async def rotation_logs(self):
    #     date_now = datetime.datetime.utcnow()
    #     date_str = date_now.strftime('%Y%m%d%H%M%S')
    #
    #     path_logs = self._etat_senseurspassifs.configuration.lecture_log_directory
    #     path_fichier_log = path.join(path_logs, 'senseurs.jsonl')
    #     path_fichier_rotation = path.join(path_logs, 'senseurs.%s.jsonl' % date_str)
    #     try:
    #         os.rename(path_fichier_log, path_fichier_rotation)
    #     except FileNotFoundError:
    #         # Rien a faire, le fichier de lectures n'existe pas
    #         return
    #
    #     # Changer pointeur de sauvegarde de fichiers
    #     await self._senseur_modules_handler.reload_configuration()
    #
    #     # Generer fichiers de transactions par senseur pour conserver long-terme
    #     await asyncio.to_thread(self.generer_fichiers_transaction())
    #
    # def generer_fichiers_transaction(self):
    #     """
    #     Converti tous les fichiers senseurs.DATE.jsonl en transactions sous un repertoire pour chaque senseur.
    #     :return:
    #     """
    #     pass

    async def entretien(self):
        self.__logger.info("entretien thread debut")

        while self._stop_event.is_set() is False:
            self.__logger.debug("run() debut execution cycle")

            for tache in self.__taches:
                try:
                    await tache.run()
                except Exception:
                    self.__logger.exception("Erreur execution tache")

            try:
                self.__logger.debug("run() fin execution cycle")
                await asyncio.wait_for(self._stop_event.wait(), 10)
            except TimeoutError:
                pass

        self.__logger.info("entretien thread fin")

    async def executer(self):
        """
        Boucle d'execution principale
        :return:
        """

        tasks = [
            asyncio.create_task(self.entretien(), name="entretien"),
            asyncio.create_task(self.__rabbitmq_dao.run(), name="mq"),
            asyncio.create_task(self._senseur_modules_handler.run(), name="senseur_modules"),
            self.__attendre_fermer()
        ]

        # Execution de la loop avec toutes les tasks
        try:
            await asyncio.tasks.wait(tasks, return_when=asyncio.tasks.FIRST_COMPLETED)
        finally:
            await self.fermer()
