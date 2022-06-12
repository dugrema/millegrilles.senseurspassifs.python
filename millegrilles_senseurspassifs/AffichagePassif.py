"""
Module d'affichage de lectures avec appareil.
"""
import asyncio
import datetime
import logging
import pytz

from typing import Optional

from millegrilles_messages.messages import Constantes
from millegrilles_messages.messages.MessagesModule import MessageProducerFormatteur
from millegrilles_senseurspassifs import Constantes as ConstantesSenseursPassifs
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs.SenseursModule import SenseurModuleHandler, SenseurModuleConsumerAbstract


class ModuleCollecteSenseurs(SenseurModuleConsumerAbstract):

    def __init__(self, handler: SenseurModuleHandler, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str):
        super().__init__(handler, etat_senseurspassifs, no_senseur)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__uuid_senseurs = list()
        self._etat_courant_senseurs = dict()

    async def appliquer_configuration(self, configuration_hub: dict):
        await super().appliquer_configuration(configuration_hub)

        # Maj liste de senseurs utilise par ce consumer
        self.__uuid_senseurs = self.get_uuid_senseurs()

    async def traiter(self, message):
        self.__logger.debug("ModuleAffichageLignes Traiter message %s" % message)

        # Matcher message pour ce senseur
        if message.get('interne') is True:
            message_recu = message['message']
            action = 'lecture'
        elif message.get('confirmation') is True:
            message_wrapper = message['message']
            routing_key = message_wrapper.routing_key
            action = routing_key.split('.').pop()
            message_recu = message_wrapper.parsed
        else:
            return

        if action in ['lecture', 'lectureConfirmee']:
            if message_recu.get('uuid_senseur') in self.__uuid_senseurs:
                await self.maj_etat_interne(message_recu)
        elif action == 'majNoeud':
            self.__logger.debug("Remplacement configuration noeud avec %s" % message_recu)
            await self.appliquer_configuration(message_recu)

    def routing_keys(self) -> list:
        return [
            'evenement.%s.lectureConfirmee' % ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS,
            'evenement.%s.%s.majNoeud' % (ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS, self._etat_senseurspassifs.instance_id),
        ]

    def get_uuid_senseurs(self) -> list:
        if self._configuration_hub is None:
            return list()

        try:
            lignes = self._configuration_hub['lcd_affichage']
        except KeyError:
            return list()

        uuid_senseurs = set()
        for ligne in lignes:
            try:
                uuid_senseurs.add(ligne['uuid'])
            except KeyError:
                pass

        return list(uuid_senseurs)

    async def rafraichir(self):
        producer: MessageProducerFormatteur = self._etat_senseurspassifs.producer
        if producer is not None and len(self.__uuid_senseurs) > 0:
            try:
                await asyncio.wait_for(producer.producer_pret().wait(), 5)

                requete_noeuds = {}
                liste_noeuds_wrapper = await producer.executer_requete(
                    requete_noeuds, ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS,
                    ConstantesSenseursPassifs.REQUETE_LISTE_NOEUDS, Constantes.SECURITE_PRIVE)
                liste_noeuds = liste_noeuds_wrapper.parsed['noeuds']
                instance_ids = [u['instance_id'] for u in liste_noeuds]

                for instance_id in instance_ids:
                    requete = {'uuid_senseurs': self.__uuid_senseurs}
                    try:
                        senseurs_wrapper = await producer.executer_requete(
                            requete, ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS,
                            ConstantesSenseursPassifs.REQUETE_LISTE_SENSEURS_PAR_UUID, Constantes.SECURITE_PRIVE,
                            partition=instance_id)
                    except TimeoutError:
                        self.__logger.warning("WARN Echec requete pour charger senseur %s (instance_id %s)" % (self.__uuid_senseurs, instance_id))
                        continue

                    senseurs = senseurs_wrapper.parsed['senseurs']
                    for senseur in senseurs:
                        # Emettre message senseur comme message interne
                        uuid_senseur = senseur['uuid_senseur']
                        lectures_senseurs = senseur['senseurs']
                        await self._handler.traiter_lecture_interne(uuid_senseur, lectures_senseurs)

                pass

            except TimeoutError:
                self.__logger.warning("rafraichir Timeout producer - Echec requete configuration hub")
            except Exception:
                self.__logger.exception("rafraichir Erreur traitement")

    async def maj_etat_interne(self, message: dict):
        uuid_senseur = message['uuid_senseur']
        senseurs = message['senseurs']
        self.__logger.info("ModuleAffichageLignes recu lecture %s = %s" % (uuid_senseur, senseurs))
        self._etat_courant_senseurs[uuid_senseur] = message


class ModuleAfficheLignes(ModuleCollecteSenseurs):
    """
    Genere des lignes/pages a afficher pour le contenu des senseurs
    """

    def __init__(self, handler: SenseurModuleHandler, etat_senseurspassifs: EtatSenseursPassifs, no_senseur: str):
        super().__init__(handler, etat_senseurspassifs, no_senseur)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__lignes_par_page = 2
        self.__delai_pages = 5.0
        self.__event_page: Optional[asyncio.Event] = None
        self._event_affichage_actif: Optional[asyncio.Event] = None

        self._lignes_affichage = list()

    def set_lignes_par_page(self, lignes: int):
        self.__lignes_par_page = lignes

    async def appliquer_configuration(self, configuration_hub: dict):
        await super().appliquer_configuration(configuration_hub)

        try:
            if configuration_hub is None:
                await self.desactiver_affichage()
            elif configuration_hub.get('lcd_actif') is True:
                await self.activer_affichage()
            elif configuration_hub.get('lcd_actif') is False:
                await self.desactiver_affichage()
        except KeyError:
            pass

    async def run(self):
        """
        Override run, ajoute la task d'affichage de l'ecran
        :return:
        """
        self.__event_page = asyncio.Event()
        self._event_affichage_actif = asyncio.Event()
        tasks = [
            asyncio.create_task(super().run()),
            asyncio.create_task(self.run_affichage())
        ]
        await asyncio.tasks.wait(tasks, return_when=asyncio.tasks.FIRST_COMPLETED)

    async def activer_affichage(self):
        self.__logger.info("Activer affichage")
        self.__event_page.clear()
        self._event_affichage_actif.set()

    async def desactiver_affichage(self):
        self.__logger.info("Desactiver affichage")
        self._lignes_affichage = list()  # Clear affichage
        self._event_affichage_actif.clear()
        self.__event_page.set()

    async def run_affichage(self):
        while True:
            await self._event_affichage_actif.wait()  # Attendre que l'affichage soit active

            if self._event_affichage_actif.is_set():
                page = self._get_page()
                if page is None:
                    # On est entre deux passes d'affichage, afficher l'heure
                    await self.__afficher_heure()
                    continue

                await self._afficher_page(page)

                try:
                    await asyncio.wait_for(self.__event_page.wait(), self.__delai_pages)
                except asyncio.TimeoutError:
                    pass  # Prochaine page

    async def _afficher_page(self, page: list):
        """
        Methode qui effectue l'affichage d'une page
        :param page:
        :return:
        """
        self.__logger.info("Lignes a afficher pour la page:\n%s" % '\n'.join(page))

    def _get_page(self) -> Optional[list]:
        if self._lignes_affichage is None:
            self._lignes_affichage = self._generer_page()
        elif len(self._lignes_affichage) == 0:
            self._lignes_affichage = None
            return None

        # Recuperer lignes
        lignes = self._lignes_affichage[0:self.__lignes_par_page]

        # Retirer lignes consommees
        self._lignes_affichage = self._lignes_affichage[self.__lignes_par_page:]

        return lignes

    async def __afficher_heure(self):
        nb_secs = float(self.__delai_pages)
        increments = 0.25
        while nb_secs > 0.0 and self.__event_page.is_set() is False:
            nb_secs -= increments

            # Prendre heure courante, formatter
            now = datetime.datetime.utcnow().astimezone(pytz.UTC)  # Set date a UTC
            # if self._timezone_horloge is not None:
            #     now = now.astimezone(self._timezone_horloge)  # Converti vers timezone demande
            datestring = now.strftime('%Y-%m-%d')
            timestring = now.strftime('%H:%M:%S')

            lignes_affichage = [datestring, timestring]
            logging.debug("Horloge: %s" % str(lignes_affichage))
            await self._afficher_page(lignes_affichage)

            try:
                await asyncio.wait_for(self.__event_page.wait(), increments)
            except asyncio.TimeoutError:
                pass

    def _generer_page(self) -> list:
        """
        Genere toutes les lignes de donnees en utilisant le formattage demande
        :return:
        """
        lignes = []

        try:
            instance_id = self._configuration_hub['instance_id']
        except (TypeError, KeyError):
            self.__logger.warning("Configuration de l'affichage %s n'est pas encore recue" % self._no_senseur)
            return list()

        try:
            formattage = self._configuration_hub['lcd_affichage']
            for ligne in formattage:
                self.__logger.debug("Formatter ligne %s" % str(ligne))
                lignes.append(self.formatter_ligne(instance_id, ligne))

            return lignes
        except KeyError:
            return list()  # Aucune configuration

    def formatter_ligne(self, noeud_id: str, formattage: dict):
        format = formattage['affichage']

        uuid_senseur = formattage.get('uuid')
        cle_senseur = uuid_senseur

        cle_appareil = formattage.get('appareil')

        # Si on a un senseur/cle, on va chercher la valeur dans le cache de documents
        if uuid_senseur is not None and uuid_senseur != '' and \
                cle_appareil is not None and cle_appareil != '':

            flag = ''
            try:
                doc_senseur = self._etat_courant_senseurs[cle_senseur]
                doc_appareil = doc_senseur['senseurs'][cle_appareil]
                try:
                    ts_app = doc_appareil['timestamp']
                    date_courante = datetime.datetime.utcnow()
                    date_lecture = datetime.datetime.utcfromtimestamp(ts_app)
                    exp_1 = datetime.timedelta(minutes=5)
                    exp_2 = datetime.timedelta(minutes=30)
                    if date_lecture + exp_2 < date_courante:
                        flag = '!'
                    elif date_lecture + exp_1 < date_courante:
                        flag = '?'
                except KeyError:
                    pass
                valeur = doc_appareil['valeur']
            except KeyError:
                # Noeud/senseur/appareil inconnu
                self.__logger.warning("Noeud %s, senseur %s, appareil %s inconnu" % (noeud_id, uuid_senseur, cle_appareil))
                return 'N/A'

            try:
                return format.format(valeur,) + flag
            except KeyError:
                return '!' + format

        else:
            # Formattage libre avec valeurs systeme
            return format
