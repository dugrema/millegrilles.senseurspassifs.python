import asyncio
import json
import logging

from aiohttp import web
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)

CONST_MAX_TIMEOUT_HTTP = 270
CONST_DEFAUT_TIMEOUT_HTTP = 60


async def handle_post_inscrire(server, request):
    try:
        commande = await request.json()
        logger.debug("handle_post_inscrire commande recue : %s" % json.dumps(commande, indent=2))

        # Valider le contenu
        try:
            commande['user_id']
            commande['uuid_appareil']
            commande['csr']
        except KeyError:
            reponse = {'ok': False, 'err': 'Params manquants'}
            reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(reponse)
            return web.json_response(status=400)

        # Valider signature
        etat = server.etat_senseurspassifs
        await etat.validateur_message.verifier(commande)
        logger.debug("handle_post_inscrire Resultat validation OK")

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

        reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(reponse)

        # Retour code pour dire que la demande d'inscription est recue.
        return web.json_response(reponse, status=202)
    except InvalidSignature:
        # Erreur de signature, message rejete
        return web.json_response(status=403)
    except Exception as e:
        logger.error("handle_post_inscrire Erreur %s" % str(e))
        return web.json_response(status=500)


async def handle_post_poll(server, request):
    try:
        commande = await request.json()
        logger.debug("handle_post_poll Etat recu %s" % commande)

        etat = server.etat_senseurspassifs
        enveloppe = await etat.validateur_message.verifier(commande)

        # S'assurer d'avoir un appareil de role senseurspassifs
        if 'senseurspassifs' not in enveloppe.get_roles:
            return web.json_response(status=403)

        # Emettre l'etat de l'appareil (une lecture)
        uuid_appareil = enveloppe.subject_common_name
        lectures_senseurs = commande['lectures_senseurs']
        await server.transmettre_lecture(uuid_appareil, lectures_senseurs)

        correlation = await server.message_handler.enregistrer_appareil(enveloppe)

        try:
            timeout_http = commande['http_timeout']
            if timeout_http < 0:
                timeout_http = 0
            elif timeout_http > CONST_MAX_TIMEOUT_HTTP:
                timeout_http = CONST_DEFAUT_TIMEOUT_HTTP
        except KeyError:
            timeout_http = CONST_MAX_TIMEOUT_HTTP  # Par defaut, 60 secondes

        try:
            reponse_wrappee = await correlation.get_reponse(timeout_http)
            reponse = reponse_wrappee.parsed
        except asyncio.TimeoutError:
            reponse = {'ok': False, 'err': 'Timeout'}
            reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(reponse)

        return web.json_response(reponse)

    except Exception as e:
        logger.error("handle_post_poll Erreur %s" % str(e))
        return web.json_response(status=500)


async def handle_post_commande(server, request):
    print("Commande recue")
    return web.Response(status=202)
