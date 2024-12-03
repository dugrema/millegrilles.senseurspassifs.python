import asyncio
import datetime
import json
import logging

import pytz

from aiohttp.web import Request, Response, json_response
from cryptography.exceptions import InvalidSignature

from millegrilles_messages.messages import Constantes
from millegrilles_messages.messages.MessagesModule import MessageWrapper
from senseurspassifs_relai_web.SenseurspassifsRelaiWebManager import SenseurspassifsRelaiWebManager

logger = logging.getLogger(__name__)

CONST_MAX_TIMEOUT_HTTP = 270
CONST_DEFAUT_TIMEOUT_HTTP = 60


async def handle_post_inscrire(request: Request, manager: SenseurspassifsRelaiWebManager):
    try:
        commande = await request.json()
        logger.debug("handle_post_inscrire commande recue : %s" % json.dumps(commande, indent=2))

        # Valider signature
        context = manager.context
        await context.validateur_message.verifier(commande, verifier_certificat=False)
        logger.debug("handle_post_inscrire Resultat validation OK")

        # Valider le contenu
        contenu = json.loads(commande['contenu'])
        if {'user_id', 'uuid_appareil', 'csr'}.issubset(contenu) is False:
            reponse = {'ok': False, 'err': 'Params manquants'}
            reponse, _ = context.formatteur.signer_message(Constantes.KIND_REPONSE, reponse)
            return json_response(status=400)

        # Verifier si on a recu le certificat pour la cle publique
        try:
            reponse = await manager.request_device_registration(commande)
            reponse_parsed = reponse.parsed
            if reponse_parsed.get('certificat') or reponse_parsed.get('challenge'):
                return json_response(reponse_parsed['__original'])  # Reponse externe, code http 200
            else:
                # Timeout (commande inscription sans certificat/challenge)
                reponse = {'ok': False}
        except asyncio.TimeoutError:
            reponse = {'ok': False, 'err': 'Timeout'}

        reponse, _ = context.formatteur.signer_message(Constantes.KIND_REPONSE, reponse)

        # Retour code pour dire que la demande d'inscription est recue.
        return json_response(reponse, status=202)
    except InvalidSignature:
        # Erreur de signature, message rejete
        return json_response(status=403)
    except Exception as e:
        logger.exception("handle_post_inscrire Erreur %s" % str(e))
        return json_response(status=500)


async def handle_post_poll(request: Request, manager: SenseurspassifsRelaiWebManager):
    try:
        commande = await request.json()
        logger.debug("handle_post_poll Etat recu %s" % commande)

        context = manager.context
        enveloppe = await context.validateur_message.verifier(commande)
        user_id = enveloppe.get_user_id

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            return json_response(status=403)

        # Emettre l'etat de l'appareil (une lecture)
        # uuid_appareil = enveloppe.subject_common_name
        # lectures_senseurs = commande['lectures_senseurs']
        await manager.send_readings(commande)

        try:
            senseurs = commande['senseurs']
        except KeyError:
            senseurs = None

        correlation = await manager.create_device_correlation(enveloppe, senseurs)

        # Verifier si on a une lecture d'appareils en attente
        lectures_pending = correlation.take_lectures_pending()
        if lectures_pending is not None and correlation.is_message_pending is False:
            # Retourner les lectures en attente
            reponse, _ = context.formatteur.signer_message(
                Constantes.KIND_REPONSE,
                {'ok': True, 'lectures_senseurs': lectures_pending},
                action='lectures_senseurs'
            )
            return json_response(reponse)

        try:
            timeout_http = commande['http_timeout']
            if timeout_http < 0:
                timeout_http = 0
            elif timeout_http > CONST_MAX_TIMEOUT_HTTP:
                timeout_http = CONST_DEFAUT_TIMEOUT_HTTP
        except KeyError:
            timeout_http = CONST_MAX_TIMEOUT_HTTP  # Par defaut, 60 secondes

        try:
            reponse = await correlation.get_reponse(timeout_http)
            if isinstance(reponse, MessageWrapper):
                reponse = reponse.parsed
            elif isinstance(reponse, dict):
                reponse, _ = context.formatteur.signer_message(Constantes.KIND_COMMANDE, reponse, action=reponse['_action'])
        except asyncio.TimeoutError:
            reponse = {'ok': False, 'err': 'Timeout'}
            reponse, _ = context.formatteur.signer_message(Constantes.KIND_REPONSE, reponse)

        return json_response(reponse)

    except Exception as e:
        logger.error("handle_post_poll Erreur %s" % str(e))
        return json_response(status=500)


async def handle_post_renouveler(request: Request, manager: SenseurspassifsRelaiWebManager):
    """
    Renouveler un certificat d'appareil (pas expire)
    """
    try:
        commande = await request.json()
        logger.debug("handle_post_renouveler Demande recue %s" % commande)

        context = manager.context

        # Verifier - s'assure que la signature est valide et certificat est encore actif
        enveloppe = await context.validateur_message.verifier(commande)
        user_id = enveloppe.get_user_id

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            return json_response(status=403)

        routage = commande['routage']
        try:
            if routage['action'] != 'signerAppareil' or routage['domaine'] != 'SenseursPassifs':
                reponse, _ = context.formatteur.signer_message(
                    Constantes.KIND_REPONSE,
                    {'ok': False, 'err': 'Mauvais domaine/action'})
                return json_response(data=reponse, status=400)
        except KeyError:
            reponse, _ = context.formatteur.signer_message(
                Constantes.KIND_REPONSE,
                {'ok': False, 'err': 'Mauvais domaine/action'})
            return json_response(data=reponse, status=400)

        # Faire le relai de la commande - CorePki/certissuer s'occupent des renouvellements de certs actifs

        try:
            producer = await context.get_producer()
            reponse = await producer.command(
                commande, 'SenseursPassifs', 'signerAppareil', Constantes.SECURITE_PRIVE, noformat=True)
            reponse = reponse.parsed
        except asyncio.TimeoutError:
            reponse = {'ok': False, 'err': 'Timeout'}
            reponse, _ = context.formatteur.signer_message(Constantes.KIND_REPONSE, reponse)

        return json_response(data=reponse, status=200)

    except Exception as e:
        logger.error("handle_post_poll Erreur %s" % str(e))
        return json_response(status=500)


async def handle_post_commande(request: Request, manager: SenseurspassifsRelaiWebManager):
    print("Commande recue")
    return Response(status=202)


async def handle_post_requete(request: Request, manager: SenseurspassifsRelaiWebManager):
    try:
        requete = await request.json()
        logger.debug("handle_post_request Etat recu %s" % requete)

        context = manager.context
        enveloppe = await context.validateur_message.verifier(requete)
        user_id = enveloppe.get_user_id

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            return json_response(status=403)

        # Touch (conserver presence appareil)
        await manager.create_device_correlation(enveloppe)

        # Emettre la requete
        routage = requete['routage']
        domaine = routage['domaine']
        action = routage['action']
        partition = routage.get('partition')
        exchange = Constantes.SECURITE_PRIVE

        try:
            producer = await context.get_producer()
            reponse = await producer.request(requete, domaine, action, exchange, partition, noformat=True)
            reponse = reponse.parsed
        except asyncio.TimeoutError:
            reponse = {'ok': False, 'err': 'Timeout'}
            reponse, _ = context.formatteur.signer_message(Constantes.KIND_REPONSE, reponse)

        return json_response(reponse)

    except Exception as e:
        logger.error("handle_post_poll Erreur %s" % str(e))
        return json_response(status=500)


async def handle_post_timeinfo(request: Request, manager: SenseurspassifsRelaiWebManager):
    try:
        requete = await request.json()
        reponse = {'ok': True}

        timezone_str = None
        try:
            now = datetime.datetime.now(tz=pytz.utc)
            timezone_str = requete['timezone']
            timezone_pytz = pytz.timezone(timezone_str)
            offset = timezone_pytz.utcoffset(now)
            offset_seconds = int(offset.total_seconds())
            reponse['timezone_offset'] = offset_seconds
        except pytz.exceptions.UnknownTimeZoneError:
            logger.error("Timezone %s inconnue" % timezone_str)
        except KeyError:
            pass  # OK, pas de timezone

        reponse, _ = manager.context.formatteur.signer_message(Constantes.KIND_REPONSE, reponse)
        return json_response(reponse)

    except Exception as e:
        logger.error("handle_get_timeinfo Erreur %s" % str(e))
        return json_response(status=500)
