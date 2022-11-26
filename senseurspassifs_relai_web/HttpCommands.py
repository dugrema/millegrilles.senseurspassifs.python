import asyncio
import json
import logging

from aiohttp import web
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)


async def handle_post_inscrire(server, request):
    try:
        commande = await request.json()
        logger.debug("handle_post_inscrire commande recue : %s" % json.dumps(commande, indent=2))

        # Valider la commande
        etat = server.etat_senseurspassifs
        await etat.validateur_message.verifier(commande)
        print("handle_post_inscrire Resultat validation OK")

        # Verifier si on a recu le certificat pour la cle publique
        try:
            reponse = await server.message_handler.demande_certificat(commande)
            return web.json_response(reponse)  # Reponse externe, code http 200
        except asyncio.TimeoutError:
            reponse = {'ok': False, 'err': 'Timeout'}
            #reponse = {'ok': True, 'challenge': [4, 1, 2, 3]}
            #reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(reponse)
            #return web.json_response(reponse)
        except Exception as e:
            logger.error("handle_post_inscrire Erreur : %s" % e)
            reponse = {'ok': False, 'err': str(e)}

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
    await asyncio.sleep(1)
    return web.json_response({"text": "Allo, c'est ma reponse"})


async def handle_post_commande(server, request):
    print("Commande recue")
    return web.Response(status=202)
