import asyncio
import datetime
import json
import logging

from os import path, rename, listdir

from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs


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

    def generer_fichiers_transaction(self):
        """
        Converti tous les fichiers senseurs.DATE.jsonl en transactions sous un repertoire pour chaque senseur.
        :return:
        """
        path_logs = self.__etat_senseurspassifs.configuration.lecture_log_directory
        fichiers = self.get_liste_fichiers()

        # Lire les evenements, generer les transactions par senseur
        for nom_fichier in fichiers:
            path_fichier = path.join(path_logs, nom_fichier)
            with open(path_fichier, 'r') as fichier:
                ligne = fichier.readline()
                try:
                    lecture = json.loads(ligne)
                except json.JSONDecodeError:
                    self.__logger

        pass

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