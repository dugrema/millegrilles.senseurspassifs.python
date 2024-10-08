import asyncio
import datetime
import json
import logging
import pytz

from astral import LocationInfo
from astral.sun import sun

from cryptography.exceptions import InvalidSignature

from millegrilles_messages.messages import Constantes
from millegrilles_messages.messages.MessagesModule import MessageWrapper
from senseurspassifs_relai_web.Chiffrage import dechiffrer_message_chacha20poly1305, attacher_reponse_chiffree

logger = logging.getLogger(__name__)


async def handle_message(handler, message: bytes):

    server = handler.server
    websocket = handler.websocket

    # Extraire information de l'enveloppe du message
    try:
        commande = json.loads(message)
        etat = server.etat_senseurspassifs
        action = commande['routage']['action']

        fingerprint = commande.get('fingerprint')
        try:
            correlation_appareil = server.message_handler.get_correlation_appareil(fingerprint)
        except ValueError:
            # Appareil inconnu - OK
            correlation_appareil = None

        try:
            commande['sig']  # Verifier que l'element sig est present (message non chiffre)
            enveloppe = await etat.validateur_message.verifier(commande)

            try:
                uuid_appareil = enveloppe.subject_common_name
                user_id = enveloppe.get_user_id
                handler.set_params_appareil(uuid_appareil, user_id)
            except AttributeError:
                logger.exception("Erreur set_params_appareils")

            if action == 'etatAppareil':
                return await handle_status(handler, correlation_appareil, commande)
            elif action == 'getTimezoneInfo':
                return await handle_get_timezone_info(server, websocket, correlation_appareil, commande)
            elif action in ['getAppareilDisplayConfiguration', 'getAppareilProgrammesConfiguration']:
                return await handle_requete(server, websocket, correlation_appareil, commande, enveloppe)
            elif action == 'signerAppareil':
                return await handle_renouvellement(handler, correlation_appareil, commande, enveloppe)
            elif action == 'getFichePublique':
                return await handle_get_fiche(handler, correlation_appareil, commande, enveloppe)
            elif action == 'getRelaisWeb':
                return await handle_get_relais_web(handler, correlation_appareil)
            elif action == 'echangerClesChiffrage':
                return await handle_echanger_cles_chiffrage(handler, correlation_appareil, commande, enveloppe)
            elif action == 'confirmerRelai':
                return await handle_confirmer_relai(handler, correlation_appareil, commande, enveloppe)

        except KeyError:
            ciphertext = commande['ciphertext']
            tag = commande['tag']
            nonce = commande['nonce']

            try:
                cle_dechiffrage = correlation_appareil.cle_dechiffrage
                commande = dechiffrer_message_chacha20poly1305(cle_dechiffrage, nonce, tag, ciphertext)
                commande = json.loads(commande)

                if action == 'etatAppareilRelai':
                    return await handle_relai_status(handler, correlation_appareil, commande)
                elif action == 'getRelaisWeb':
                    return await handle_get_relais_web(handler, correlation_appareil)
                elif action == 'getTimezoneInfo':
                    return await handle_get_timezone_info(server, websocket, correlation_appareil, commande)

            except Exception:
                logger.exception('Erreur dechiffrage, on desactive le chiffrage')
                correlation_appareil.clear_chiffrage()
                reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(
                    Constantes.KIND_COMMANDE, dict(), action='resetSecret')
                await websocket.send(json.dumps(reponse).encode('utf-8'))

        logger.error("handle_message Action inconnue %s" % action)

    except Exception as e:
        logger.error("handle_message Erreur %s" % str(e))


async def handle_status(handler, correlation_appareil, commande: dict):
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

        contenu = json.loads(commande['contenu'])
        try:
            senseurs = contenu['senseurs']
        except KeyError:
            senseurs = None

        correlation = await server.message_handler.enregistrer_appareil(enveloppe, senseurs, emettre_lectures=False)
        await handler.set_correlation(correlation)

        return correlation

    except Exception as e:
        logger.error("handle_status Erreur %s" % str(e))


async def handle_relai_status(handler, correlation_appareil, commande: dict):
    server = handler.server
    try:
        logger.debug("handle_relai_status uuid_appareil: %s, etat recu %s" % (correlation_appareil.uuid_appareil, commande))

        # Emettre l'etat de l'appareil (une lecture)
        await handler.transmettre_lecture(commande, correlation_appareil)

        correlation_appareil.touch()
        try:
            senseurs = commande['senseurs']
            if senseurs is not None:
                correlation_appareil.set_senseurs_externes(senseurs)
        except KeyError:
            pass

        return correlation_appareil

    except Exception as e:
        logger.error("handle_relai_status Erreur %s" % str(e))


def calculer_transition_tz(tz):
    transition_times = tz._utc_transition_times
    now = datetime.datetime.now()
    current_offset_secs = int(tz.utcoffset(now).total_seconds())

    next_transition = None
    for transition in transition_times:
        if transition > now:
            next_transition = transition
            break

    reponse = {'timezone_offset': current_offset_secs}

    if next_transition:
        timestamp_utc = datetime.datetime(
            next_transition.year, next_transition.month, next_transition.day,
            next_transition.hour, next_transition.minute, tzinfo=pytz.UTC)
        next_transition_secs = int(timestamp_utc.timestamp())
        next_offset_secs = int(tz.utcoffset(next_transition).total_seconds())
        reponse['transition_time'] = next_transition_secs
        reponse['transition_offset'] = next_offset_secs

    return reponse


async def handle_get_timezone_info(server, websocket, correlation_appareil, requete: dict):
    etat = server.etat_senseurspassifs
    producer = etat.producer

    reponse = {'ok': True}

    # timezone_str = None
    uuid_appareil = correlation_appareil.uuid_appareil
    user_id = correlation_appareil.user_id
    timezone_str = None
    geoposition = None

    # try:
    #     requete_usager = {'user_id': user_id}
    #     reponse_usager = await producer.executer_requete(
    #         requete_usager, 'SenseursPassifs', 'getConfigurationUsager', exchange=Constantes.SECURITE_PRIVE, timeout=3)
    #     timezone_str = reponse_usager.parsed['timezone']
    # except (KeyError, asyncio.TimeoutError):
    #     pass

    try:
        requete_appareil = {'user_id': user_id, 'uuid_appareil': uuid_appareil}
        reponse_appareil = await producer.executer_requete(
            requete_appareil, 'SenseursPassifs', 'getTimezoneAppareil', exchange=Constantes.SECURITE_PRIVE, timeout=3)
        timezone_str = reponse_appareil.parsed.get('timezone')
        geoposition = reponse_appareil.parsed.get('geoposition') or dict()
    except asyncio.TimeoutError:
        pass

    # Note : les valeurs fournies dans la requete viennent de l'appareil (e.g. GPS, override)
    latitude = requete.get('latitude') or geoposition.get('latitude')
    longitude = requete.get('longitude') or geoposition.get('longitude')

    if timezone_str is None:
        try:
            timezone_str = requete['timezone']
            reponse['timezone'] = timezone_str
        except KeyError:
            timezone_str = None

    if timezone_str:
        reponse['timezone'] = timezone_str
        try:
            # now = datetime.datetime.utcnow()
            # timezone_str = requete['timezone']
            timezone_pytz = pytz.timezone(timezone_str)
            # offset = timezone_pytz.utcoffset(now)
            # offset_seconds = int(offset.total_seconds())
            # reponse['timezone_offset'] = offset_seconds
            info_tz = calculer_transition_tz(timezone_pytz)
            reponse.update(info_tz)
        except pytz.exceptions.UnknownTimeZoneError:
            logger.error("Timezone %s inconnue" % timezone_str)
        except KeyError:
            # pas de timezone
            reponse['ok'] = False
    else:
        reponse['ok'] = False

    # Verifier si on retourne l'information de l'horaire solaire de la journee
    if isinstance(latitude, (float, int)) and isinstance(longitude, (float, int)):
        reponse['latitude'] = latitude
        reponse['longitude'] = longitude
        reponse['solaire_utc'] = calculer_horaire_solaire(latitude, longitude)
        reponse['ok'] = True

    reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(Constantes.KIND_COMMANDE, reponse, action='timezoneInfo')

    attacher_reponse_chiffree(correlation_appareil, reponse, enveloppe=None)

    await websocket.send(json.dumps(reponse).encode('utf-8'))


def calculer_horaire_solaire(latitude, longitude):

    location_info = LocationInfo("ici", "ici", "UTC", latitude, longitude)

    today = datetime.datetime.now().date()
    vals = ['dawn', 'sunrise', 'noon', 'sunset', 'dusk']

    s = sun(location_info.observer, date=today, tzinfo="UTC")

    # Convertir les valeurs en timestamps (epoch secs)
    timestamp_vals = dict()
    for val in vals:
        # Convertir le temps en liste [heure UTC, minute]
        temps_solaire = s[val]
        heure_list = [temps_solaire.hour, temps_solaire.minute]
        timestamp_vals[val] = heure_list

    return timestamp_vals


async def handle_get_relais_web(handler, correlation_appareil):
    server = handler.server
    websocket = handler.websocket
    etat = server.etat_senseurspassifs

    fiche = dict(etat.fiche_publique)
    if fiche is not None:
        try:
            url_relais = parse_fiche_relais(fiche)

            # url_relais = [app['url'] for app in fiche['applications']['senseurspassifs_relai'] if
            #               app['nature'] == 'dns']

            reponse = {'relais': url_relais}
            reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(Constantes.KIND_COMMANDE, reponse, action='relaisWeb')
            attacher_reponse_chiffree(correlation_appareil, reponse, enveloppe=None)
            await websocket.send(json.dumps(reponse).encode('utf-8'))
        except KeyError:
            pass  # OK, pas de timezone


def parse_fiche_relais(fiche: dict):
    app_instance_pathname = dict()
    for instance_id, app_params in fiche['applicationsV2']['senseurspassifs_relai']['instances'].items():
        try:
            app_instance_pathname[instance_id] = app_params['pathname']
            logger.debug("instance_id %s pathname %s" % (instance_id, app_params['pathname']))
        except KeyError:
            pass

    logger.debug("relais %d instances" % len(app_instance_pathname))

    url_relais = list()
    for instance_id, instance_params in fiche['instances'].items():
        try:
            pathname = app_instance_pathname[instance_id]
        except KeyError:
            continue  # Pas de path

        try:
            port = instance_params['ports']['https']
        except KeyError:
            port = 443

        try:
            for domaine in instance_params['domaines']:
                url_relais.append(f'https://{domaine}:{port}{pathname}')
        except KeyError:
            pass

    return url_relais


async def handle_requete(server, websocket, correlation_appareil, requete: dict, enveloppe):
    try:
        logger.debug("handle_post_request Etat recu %s" % requete)

        etat = server.etat_senseurspassifs
        user_id = enveloppe.get_user_id
        routage_requete = requete['routage']
        action_requete = routage_requete['action']

        # S'assurer d'avoir un appareil de role senseurspassifs
        if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
            logger.error("Requete refusee pour roles %s" % enveloppe.get_roles)
            return

        # Touch (conserver presence appareil)
        await server.message_handler.enregistrer_appareil(enveloppe, emettre_lectures=False)

        # Emettre la requete
        domaine_requete = routage_requete['domaine']
        partition_requete = routage_requete.get('partition')
        exchange = Constantes.SECURITE_PRIVE

        producer = etat.producer

        try:
            reponse = await producer.executer_requete(
                requete, domaine_requete, action_requete, exchange, partition_requete, noformat=True)
            reponse = reponse.parsed['__original']

            # Injecter _action (en-tete de reponse ne contient pas d'action)
            reponse['attachements'] = {'action': action_requete}

            attacher_reponse_chiffree(correlation_appareil, reponse, enveloppe=None)

            await websocket.send(json.dumps(reponse).encode('utf-8'))
        except asyncio.TimeoutError:
            pass

    except Exception:
        logger.exception("Erreur traitement requete")


async def handle_renouvellement(handler, correlation_appareil, commande: dict, enveloppe):
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
            return  # Skip

        routage = commande['routage']
        try:
            if routage['action'] != 'signerAppareil' or routage['domaine'] != 'SenseursPassifs':
                logger.info("handle_renouvellement Action/domaine certificat renouvellement invalide")
                return  # Skip
        except KeyError:
            logger.info("handle_renouvellement Action/domaine certificat renouvellement invalide")
            return  # Skip

        # Faire le relai de la commande - CorePki/certissuer s'occupent des renouvellements de certs actifs
        producer = etat.producer

        try:
            reponse = await producer.executer_commande(
                commande, 'SenseursPassifs', 'signerAppareil', Constantes.SECURITE_PRIVE, noformat=True)
            reponse = reponse.parsed['__original']

            # Injecter _action (en-tete de reponse ne contient pas d'action)
            reponse['attachements'] = {'action': 'signerAppareil'}

            attacher_reponse_chiffree(correlation_appareil, reponse, enveloppe=None)

            reponse_bytes = json.dumps(reponse).encode('utf-8')

            await websocket.send(reponse_bytes)
        except asyncio.TimeoutError:
            logger.info("handle_renouvellement Erreur commande signerAppareil (timeout)")

    except Exception as e:
        logger.error("handle_renouvellement Erreur %s" % str(e))


async def handle_get_fiche(handler, correlation_appareil, commande: dict, enveloppe):
    server = handler.server
    websocket = handler.websocket
    etat = server.etat_senseurspassifs

    fiche = dict(etat.fiche_publique)
    if fiche is not None:
        reponse_bytes = json.dumps(fiche).encode('utf-8')
        await websocket.send(reponse_bytes)


async def handle_echanger_cles_chiffrage(handler, correlation_appareil, commande: dict, enveloppe):
    server = handler.server
    websocket = handler.websocket
    etat = server.etat_senseurspassifs

    user_id = enveloppe.get_user_id

    # S'assurer d'avoir un appareil de role senseurspassifs
    if user_id is None or 'senseurspassifs' not in enveloppe.get_roles:
        logger.info("Mauvais role certificat (%s) pour etat appareil" % enveloppe.get_roles)
        return
    correlation = await server.message_handler.enregistrer_appareil(enveloppe, emettre_lectures=False)
    await handler.set_correlation(correlation)

    contenu = json.loads(commande['contenu'])

    try:
        version = contenu['version']
        handler.set_version(version)
    except (AttributeError, KeyError):
        logger.debug("Version non disponible")

    # Valider enveloppe, doit correspondre a l'appareil authentifie
    logger.debug("handle_echanger_cles_chiffrage commande : %s" % commande)
    cle_peer = contenu['peer']
    cle_publique_locale = await server.message_handler.echanger_cle_chiffrage(enveloppe, cle_peer)

    reponse = {'peer': cle_publique_locale}
    reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(
        Constantes.KIND_COMMANDE, reponse, action='echangerSecret')

    reponse_bytes = json.dumps(reponse).encode('utf-8')
    await websocket.send(reponse_bytes)


async def handle_confirmer_relai(handler, correlation_appareil, commande: dict, enveloppe):
    # Verifier que la commande est bien pour le certificat local
    server = handler.server
    websocket = handler.websocket
    etat = server.etat_senseurspassifs
    fingerprint = enveloppe.fingerprint

    try:
        # Transmettre la commande de confirmation vers le domaine SenseursPassifs
        # Va permettre de faire le relai de l'etat du senseur via signature locale
        if commande['routage']['action'] != 'confirmerRelai' or commande['routage']['domaine'] != 'SenseursPassifs':
            raise Exception('handle_confirmer_relai: mauvais domaine/action pour commande confirmation : %s' % commande['routage'])

        producer = etat.producer
        await asyncio.wait_for(producer.producer_pret().wait(), 1)
        await producer.executer_commande(commande, 'SenseursPassifs', 'confirmerRelai', Constantes.SECURITE_PRIVE,
                                         noformat=True, timeout=5)

        # Tout est pret, le relai peut maintenant signer le contenu du client
        server.message_handler.activer_relai_messages(fingerprint)

    except:
        logger.exception("Erreur confirmation relai avec domaine, desactiver chiffrage avec microcontrolleur")
        server.message_handler.clear_chiffrage(fingerprint)
        # Desactiver le chiffrage avec le client
        reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(
            Constantes.KIND_COMMANDE, dict(), action='resetSecret')
        reponse_bytes = json.dumps(reponse).encode('utf-8')
        await websocket.send(reponse_bytes)

    # reponse, _ = server.etat_senseurspassifs.formatteur_message.signer_message(
    #     Constantes.KIND_COMMANDE, reponse, action='echangerSecret')

    pass
