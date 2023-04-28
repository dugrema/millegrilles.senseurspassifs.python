import asyncio
import datetime
import json
import logging
import pytz

from aiohttp import web
from cryptography.exceptions import InvalidSignature

from millegrilles_messages.messages import Constantes
from millegrilles_messages.messages.MessagesModule import MessageWrapper

logger = logging.getLogger(__name__)

CONST_MAX_TIMEOUT_HTTP = 270
CONST_DEFAUT_TIMEOUT_HTTP = 60


async def handle_post_inscrire(server, request):
    try:
        commande = await request.json()
        logger.debug("handle_post_inscrire commande recue : %s" % json.dumps(commande, indent=2))

        # Valider signature
        etat = server.etat_senseurspassifs
        await etat.validateur_message.verifier(commande, verifier_certificat=False)
        logger.debug("handle_post_inscrire Resultat validation OK")

        # Valider le contenu
        try:
            contenu = json.loads(commande['contenu'])
            contenu['user_id']
            contenu['uuid_appareil']
            contenu['csr']
        except KeyError:
            reponse = {'ok': False, 'err': 'Params manquants'}
            reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(Constantes.KIND_REPONSE, reponse)
            return web.json_response(status=400)

        # Verifier si on a recu le certificat pour la cle publique
        try:
            reponse = await server.message_handler.demande_certificat(commande)
            reponse_parsed = reponse.parsed
            if reponse_parsed.get('certificat') or reponse_parsed.get('challenge'):
                return web.json_response(reponse_parsed)  # Reponse externe, code http 200
            else:
                # Timeout (commande inscription sans certificat/challenge)
                reponse = {'ok': False}
        except asyncio.TimeoutError:
            reponse = {'ok': False, 'err': 'Timeout'}

        reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(Constantes.KIND_REPONSE, reponse)

        # Retour code pour dire que la demande d'inscription est recue.
        return web.json_response(reponse, status=202)
    except InvalidSignature:
        # Erreur de signature, message rejete
        return web.json_response(status=403)
    except Exception as e:
        logger.exception("handle_post_inscrire Erreur %s" % str(e))
        return web.json_response(status=500)


async def handle_post_poll(server, request):
    try:
        commande = await request.json()
        logger.debug("handle_post_poll Etat recu %s" % commande)

        etat = server.etat_senseurspassifs
        enveloppe = await etat.validateur_message.verifier(commande)
        user_id = enveloppe.get_user_id

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            return web.json_response(status=403)

        # Emettre l'etat de l'appareil (une lecture)
        # uuid_appareil = enveloppe.subject_common_name
        # lectures_senseurs = commande['lectures_senseurs']
        await server.transmettre_lecture(commande)

        try:
            senseurs = commande['senseurs']
        except KeyError:
            senseurs = None

        correlation = await server.message_handler.enregistrer_appareil(enveloppe, senseurs)

        # Verifier si on a une lecture d'appareils en attente
        lectures_pending = correlation.take_lectures_pending()
        if lectures_pending is not None and correlation.is_message_pending is False:
            # Retourner les lectures en attente
            reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(
                Constantes.KIND_REPONSE,
                {'ok': True, 'lectures_senseurs': lectures_pending},
                action='lectures_senseurs'
            )
            return web.json_response(reponse)

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
                reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(Constantes.KIND_COMMANDE, reponse, action=reponse['_action'])
        except asyncio.TimeoutError:
            reponse = {'ok': False, 'err': 'Timeout'}
            reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(Constantes.KIND_REPONSE, reponse)

        return web.json_response(reponse)

    except Exception as e:
        logger.error("handle_post_poll Erreur %s" % str(e))
        return web.json_response(status=500)


async def handle_post_renouveler(server, request):
    """
    Renouveler un certificat d'appareil (pas expire)
    :param server:
    :param request:
    :return:
    """
    try:
        commande = await request.json()
        logger.debug("handle_post_renouveler Demande recue %s" % commande)

        etat = server.etat_senseurspassifs

        # Verifier - s'assure que la signature est valide et certificat est encore actif
        enveloppe = await etat.validateur_message.verifier(commande)
        user_id = enveloppe.get_user_id

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            return web.json_response(status=403)

        entete = commande['en-tete']
        try:
            if entete['action'] != 'signerAppareil' or entete['domaine'] != 'SenseursPassifs':
                reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(
                    Constantes.KIND_REPONSE,
                    {'ok': False, 'err': 'Mauvais domaine/action'})
                return web.json_response(data=reponse, status=400)
        except KeyError:
            reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(
                Constantes.KIND_REPONSE,
                {'ok': False, 'err': 'Mauvais domaine/action'})
            return web.json_response(data=reponse, status=400)

        # Faire le relai de la commande - CorePki/certissuer s'occupent des renouvellements de certs actifs
        producer = etat.producer

        try:
            reponse = await producer.executer_commande(
                commande, 'SenseursPassifs', 'signerAppareil', Constantes.SECURITE_PRIVE, noformat=True)
            reponse = reponse.parsed
        except asyncio.TimeoutError:
            reponse = {'ok': False, 'err': 'Timeout'}
            reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(Constantes.KIND_REPONSE, reponse)

        return web.json_response(data=reponse, status=200)

    except Exception as e:
        logger.error("handle_post_poll Erreur %s" % str(e))
        return web.json_response(status=500)


async def handle_post_commande(server, request):
    print("Commande recue")
    return web.Response(status=202)


async def handle_post_requete(server, request):
    try:
        requete = await request.json()
        logger.debug("handle_post_request Etat recu %s" % requete)

        etat = server.etat_senseurspassifs
        enveloppe = await etat.validateur_message.verifier(requete)
        user_id = enveloppe.get_user_id

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            return web.json_response(status=403)

        # Touch (conserver presence appareil)
        await server.message_handler.enregistrer_appareil(enveloppe)

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
        except asyncio.TimeoutError:
            reponse = {'ok': False, 'err': 'Timeout'}
            reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(Constantes.KIND_REPONSE, reponse)

        return web.json_response(reponse)

    except Exception as e:
        logger.error("handle_post_poll Erreur %s" % str(e))
        return web.json_response(status=500)


async def handle_post_timeinfo(server, request):
    try:
        requete = await request.json()
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

        reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(Constantes.KIND_REPONSE, reponse)
        return web.json_response(reponse)

    except Exception as e:
        logger.error("handle_get_timeinfo Erreur %s" % str(e))
        return web.json_response(status=500)
