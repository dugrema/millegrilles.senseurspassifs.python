import asyncio
import datetime
import json
import logging
import pytz

from cryptography.exceptions import InvalidSignature

from millegrilles_messages.messages import Constantes
from millegrilles_messages.messages.MessagesModule import MessageWrapper

logger = logging.getLogger(__name__)


async def handle_message(handler, message: bytes):

    server = handler.server
    websocket = handler.websocket

    try:
        commande = json.loads(message)
        etat = server.etat_senseurspassifs
        enveloppe = await etat.validateur_message.verifier(commande)

        entete = commande['en-tete']
        action = entete['action']

        print("Recu message %s valide %s" % (action, enveloppe))

        if action == 'etatAppareil':
            return await handle_status(handler, commande)
        elif action == 'getTimezoneInfo':
            return await handle_get_timezone_info(server, websocket, commande)
        elif action == 'getAppareilDisplayConfiguration':
            return await handle_requete(server, websocket, commande, enveloppe)
        elif action == 'signerAppareil':
            return await handle_renouvellement(handler, commande, enveloppe)
        elif action == 'getFichePublique':
            return await handle_get_fiche(handler, commande, enveloppe)
        elif action == 'getRelaisWeb':
            return await handle_get_relais_web(handler, commande, enveloppe)
        else:
            logger.error("handle_post_poll Action inconnue %s" % action)

    except Exception as e:
        logger.error("handle_post_poll Erreur %s" % str(e))


async def handle_status(handler, commande: dict):
    server = handler.server
    try:
        logger.debug("handle_status Etat recu %s" % commande)

        etat = server.etat_senseurspassifs
        enveloppe = await etat.validateur_message.verifier(commande)
        user_id = enveloppe.get_user_id

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            logger.info("Mauvais role certificat (%s) pour etat appareil" % enveloppe.get_roles)
            return

        # Emettre l'etat de l'appareil (une lecture)
        await handler.transmettre_lecture(commande)

        try:
            senseurs = commande['senseurs']
        except KeyError:
            senseurs = None

        correlation = await server.message_handler.enregistrer_appareil(enveloppe, senseurs, emettre_lectures=False)
        await handler.set_correlation(correlation)

        return correlation

        # # Verifier si on a une lecture d'appareils en attente
        # lectures_pending = correlation.take_lectures_pending()
        # if lectures_pending is not None and correlation.is_message_pending is False:
        #     # Retourner les lectures en attente
        #     reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(
        #         {'ok': True, 'lectures_senseurs': lectures_pending},
        #         action='lectures_senseurs'
        #     )
        #     await websocket.send(json.dumps(reponse).encode('utf-8'))

    except Exception as e:
        logger.error("handle_post_poll Erreur %s" % str(e))


async def handle_get_timezone_info(server, websocket, requete: dict):
    reponse = {'ok': True}

    timezone_str = None
    try:
        now = datetime.datetime.utcnow()
        timezone_str = requete['timezone']
        timezone_pytz = pytz.timezone(timezone_str)
        offset = timezone_pytz.utcoffset(now)
        offset_seconds = int(offset.total_seconds())
        reponse['timezone_offset'] = offset_seconds
    except pytz.exceptions.UnknownTimeZoneError:
        logger.error("Timezone %s inconnue" % timezone_str)
    except KeyError:
        pass  # OK, pas de timezone

    reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(reponse, action='timezoneInfo')

    await websocket.send(json.dumps(reponse).encode('utf-8'))


async def handle_get_relais_web(handler, commande: dict, enveloppe):
    server = handler.server
    websocket = handler.websocket
    etat = server.etat_senseurspassifs

    fiche = dict(etat.fiche_publique)
    if fiche is not None:
        try:
            url_relais = [app['url'] for app in fiche['applications']['senseurspassifs_relai'] if
                          app['nature'] == 'dns']
            reponse = {'relais': url_relais}
            reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(reponse, action='relaisWeb')
            await websocket.send(json.dumps(reponse).encode('utf-8'))
        except KeyError:
            pass  # OK, pas de timezone


async def handle_requete(server, websocket, requete: dict, enveloppe):
    try:
        logger.debug("handle_post_request Etat recu %s" % requete)

        etat = server.etat_senseurspassifs
        user_id = enveloppe.get_user_id
        entete_requete = requete['en-tete']
        action_requete = entete_requete['action']

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            logger.error("Requete refusee pour roles %s" % enveloppe.get_roles)
            return

        # Touch (conserver presence appareil)
        await server.message_handler.enregistrer_appareil(enveloppe, emettre_lectures=False)

        # Emettre la requete
        entete = requete['en-tete']
        domaine = entete['domaine']
        action = entete['action']
        partition = entete.get('partition')
        exchange = Constantes.SECURITE_PRIVE

        producer = etat.producer

        try:
            reponse = await producer.executer_requete(requete, domaine, action, exchange, partition, noformat=True)
            reponse = reponse.parsed

            # Injecter _action (en-tete de reponse ne contient pas d'action)
            reponse['_action'] = action_requete

            await websocket.send(json.dumps(reponse).encode('utf-8'))
        except asyncio.TimeoutError:
            pass

    except Exception:
        logger.exception("Erreur traitement requete")


async def handle_renouvellement(handler, commande: dict, enveloppe):
    try:
        logger.debug("handle_renouvellement Demande recue %s" % commande)

        server = handler.server
        websocket = handler.websocket
        etat = server.etat_senseurspassifs

        # Verifier - s'assure que la signature est valide et certificat est encore actif
        user_id = enveloppe.get_user_id

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            logger.info("handle_renouvellement Role certificat renouvellement invalide : %s" % enveloppe.get_roles)

        entete = commande['en-tete']
        try:
            if entete['action'] != 'signerAppareil' or entete['domaine'] != 'SenseursPassifs':
                logger.info("handle_renouvellement Action/domaine certificat renouvellement invalide")
        except KeyError:
            logger.info("handle_renouvellement Action/domaine certificat renouvellement invalide")

        # Faire le relai de la commande - CorePki/certissuer s'occupent des renouvellements de certs actifs
        producer = etat.producer

        try:
            reponse = await producer.executer_commande(
                commande, 'SenseursPassifs', 'signerAppareil', Constantes.SECURITE_PRIVE, noformat=True)
            reponse = reponse.parsed
            reponse['_action'] = 'signerAppareil'

            reponse_bytes = json.dumps(reponse).encode('utf-8')

            await websocket.send(reponse_bytes)
        except asyncio.TimeoutError:
            logger.info("handle_renouvellement Erreur commande signerAppareil (timeout)")

    except Exception as e:
        logger.error("handle_renouvellement Erreur %s" % str(e))


async def handle_get_fiche(handler, commande: dict, enveloppe):
    server = handler.server
    websocket = handler.websocket
    etat = server.etat_senseurspassifs

    fiche = dict(etat.fiche_publique)
    if fiche is not None:
        reponse_bytes = json.dumps(fiche).encode('utf-8')
        await websocket.send(reponse_bytes)
