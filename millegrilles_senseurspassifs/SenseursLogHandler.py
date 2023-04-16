import asyncio
import datetime
import json
import logging
import lzma
import string

from os import path, rename, listdir, makedirs, unlink

from millegrilles_messages.messages import Constantes
from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs import Constantes as ConstantesSenseursPassifs


class SenseursLogHandler:

    def __init__(self, etat_senseurspassifs: EtatSenseursPassifs, senseur_modules_handler):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__etat_senseurspassifs = etat_senseurspassifs
        self.__senseur_modules_handler = senseur_modules_handler

    async def rotation_logs(self):
        date_now = datetime.datetime.utcnow()
        date_str = date_now.strftime('%Y%m%d%H%M%S')

        path_logs = self.__etat_senseurspassifs.configuration.lecture_log_directory
        path_fichier_log = path.join(path_logs, 'senseurs.jsonl')
        path_fichier_rotation = path.join(path_logs, 'senseurs.%s.jsonl' % date_str)
        try:
            rename(path_fichier_log, path_fichier_rotation)
        except FileNotFoundError:
            # Rien a faire, le fichier de lectures n'existe pas
            return

        # Changer pointeur de sauvegarde de fichiers
        await self.__senseur_modules_handler.reload_configuration()

        # Generer fichiers de transactions par senseur pour conserver long-terme
        await asyncio.to_thread(self.generer_fichiers_transaction)

    @property
    def path_pending(self):
        path_logs = self.__etat_senseurspassifs.configuration.lecture_log_directory
        return path.join(path_logs, 'pending')

    @property
    def path_archives(self):
        path_logs = self.__etat_senseurspassifs.configuration.lecture_log_directory
        return path.join(path_logs, 'archives')

    def generer_fichiers_transaction(self):
        """
        Converti tous les fichiers senseurs.DATE.jsonl en transactions sous un repertoire pour chaque senseur.
        :return:
        """
        path_logs = self.__etat_senseurspassifs.configuration.lecture_log_directory
        fichiers = self.get_liste_fichiers()

        # Creer repertoires
        makedirs(self.path_pending, exist_ok=True)
        makedirs(self.path_archives, exist_ok=True)

        # Lire les evenements, generer les transactions par senseur
        lectures_cumulees = dict()  # Key = uuid_senseur, value = [lectures]

        for nom_fichier in fichiers:
            path_fichier = path.join(path_logs, nom_fichier)
            with open(path_fichier, 'r') as fichier:
                for ligne in fichier:
                    try:
                        lecture = json.loads(ligne)
                    except json.JSONDecodeError:
                        self.__logger.exception("Erreur decodage fichier %s - corrompu" % path_fichier)
                        continue

                    try:
                        uuid_senseur = lecture['uuid_senseur']
                        senseurs_lectures = lecture['senseurs']  # Appareils
                    except KeyError:
                        continue

                    for senseur_id, value in senseurs_lectures.items():
                        try:
                            dict_lectures = lectures_cumulees[senseur_id]
                            liste_lectures = dict_lectures['lectures']
                        except KeyError:
                            liste_lectures = list()
                            dict_lectures = {
                                'instance_id': self.__etat_senseurspassifs.instance_id,
                                'uuid_senseur': uuid_senseur,
                                'senseur': senseur_id,
                                'lectures': liste_lectures
                            }
                            lectures_cumulees[senseur_id] = dict_lectures

                        liste_lectures.append(value)

                        if len(liste_lectures) >= 1000:
                            # Flush une transaction pour ce senseur
                            self.generer_fichier_transaction(dict_lectures)
                            liste_lectures.clear()  # Reset liste du senseur

        for senseur_id, dict_lectures in lectures_cumulees.items():
            self.generer_fichier_transaction(dict_lectures)

        # Supprimer tous les fichiers de transaction
        for nom_fichier in fichiers:
            path_fichier = path.join(path_logs, nom_fichier)
            try:
                unlink(path_fichier)
            except FileNotFoundError:
                pass  # Deja supprime

    def get_liste_fichiers(self):
        path_logs = self.__etat_senseurspassifs.configuration.lecture_log_directory
        fichiers_directory = listdir(path_logs)

        fichiers_log = list()

        for fichier in fichiers_directory:
            fichier_split = fichier.split('.')
            try:
                if fichier_split[0] == 'senseurs' and fichier_split[2] == 'jsonl':
                    date_fichier = fichier_split[1]
                    fichiers_log.append(date_fichier)
            except IndexError:
                pass

        fichiers_log = ['senseurs.%s.jsonl' % f for f in sorted(fichiers_log)]

        return fichiers_log

    def generer_fichier_transaction(self, dict_lectures: dict):
        transaction, uuid_transaction = self.__etat_senseurspassifs.formatteur_message.signer_message(
            Constantes.KIND_EVENEMENT, dict_lectures.copy(), ConstantesSenseursPassifs.DOMAINE_SENSEURSPASSIFS,
            action=ConstantesSenseursPassifs.EVENEMENT_DOMAINE_LECTURE)

        try:
            uuid_senseur = transaction['uuid_senseur']
            lectures = transaction['lectures']
            plusvieux_timestamp_int = lectures[0]['timestamp']
            pluvieux_timestamp = datetime.datetime.utcfromtimestamp(plusvieux_timestamp_int)
            pluvieux_timestamp_str = pluvieux_timestamp.strftime('%Y%m%d%H%M%S')

            senseur_id_formatte = format_filename(transaction['senseur'])
            uuid_senseur_formatte = uuid_senseur.replace('-', '')

            nom_fichier_transaction = '%s.%s.%s.json.tar.xz' % (
                uuid_senseur_formatte, senseur_id_formatte, pluvieux_timestamp_str)
        except (TypeError, KeyError):
            self.__logger.exception("Fichier log pour senseur ne peut pas etre traite (dropped) : %s", dict_lectures)
            return

        path_fichier = path.join(self.path_pending, nom_fichier_transaction)

        with lzma.open(path_fichier, 'wt') as fichier_transaction:
            json.dump(transaction, fichier_transaction, sort_keys=True)


def format_filename(s):
    """
    source: https://gist.github.com/seanh/93666
    Take a string and return a valid filename constructed from the string.
    Uses a whitelist approach: any characters not present in valid_chars are
    removed. Also spaces are replaced with underscores.

    Note: this method may produce invalid filenames such as ``, `.` or `..`
    When I use this method I prepend a date string like '2009_01_15_19_46_32_'
    and append a file extension like '.txt', so I avoid the potential of using
    an invalid filename.
    """
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    filename = ''.join(c for c in s if c in valid_chars)
    filename = filename.replace(' ', '_')  # I don't like spaces in filenames.
    return filename