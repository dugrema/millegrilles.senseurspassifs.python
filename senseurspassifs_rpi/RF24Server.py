"""
Serveur RF24
Parametres configurables : 
  command line :
    --rf24master : Active ce module
    --dev : Active mode dev, channel 0x0c
    --int : Active mode int, channel 0x24
  environ 
    - RF24_PA : Force du power amplifier. Nombre de 1 a 3  (MIN, HIGH, MAX). Par defaut MIN.
    - RF24_RADIO_PIN : No de PIN (BCM, RPI_V2), par defaut 25
    - RF24_RADIO_IRQ : No de PIN du IRQ (BCM, RPI_V2), par defaut 24
    - RF24_DHCP_CONF : Path du fichier de configuraiton dhcp. 
                       Par defaut /var/opt/millegrilles/data/senseurspassifs.dhcp.conf
    - FICHIER_RESEAU_CONF : Path du fichier de configuraiton de reseau RF24.
                            Par defaut /var/opt/millegrilles/data/senseurspassifs.reseau.conf
"""
import asyncio
import RF24
import donna25519
import RPi.GPIO as GPIO

from threading import Event, Lock
from os import path, urandom, environ, makedirs
from zlib import crc32
from struct import unpack

import binascii
import json
import datetime
import struct

import logging

from senseurspassifs_rpi import Constantes as ConstantesRPi
from senseurspassifs_rpi import ProtocoleVersion9
from senseurspassifs_rpi.ProtocoleVersion9 import VERSION_PROTOCOLE, \
    AssembleurPaquets, Paquet0, PaquetDemandeDHCP, PaquetBeaconDHCP, PaquetReponseDHCP, TypesMessages


class Constantes(ConstantesRPi):
    MG_CHANNEL_PROD = 0x5e
    MG_CHANNEL_INT = 0x24
    MG_CHANNEL_DEV = 0x0c

    # ADDR_BROADCAST_DHCP = bytes([0x29, 0x0E, 0x92, 0x54, 0x8B])  # Adresse de broadcast du beacon
    ADDR_BROADCAST_DHCP = bytes([0x8B, 0x54, 0x92, 0x0E, 0x29])  # Adresse de broadcast du beacon

    INTERVALLE_BEACON = 0.25

    TRANSMISSION_NB_ESSAIS = 3

    RPI_V2_GPIO_P1_22 = 25
    PIN_IRQ = 24
    BCM2835_SPI_CS0 = 0
    BCM2835_SPI_SPEED_8MHZ = 8000000
    
    FICHIER_CONFIG_RESEAU = 'senseurspassifs.reseau.conf'
    FICHIER_CONFIG_DHCP = 'senseurspassifs.dhcp.json'


class RadioThread:
    """
    Thread pour la radio. 
    Agit comme iter sur les messages recu.
    """

    def __init__(self, stop_event: asyncio.Event, type_env='prod'):
        """
        Environnements
        :param stop_event: IDMG de la MilleGrille
        :param type_env: prod, int ou dev
        """
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        
        # Event pour indiquer a la thread de processing qu'on a un message
        self.__event_reception = asyncio.Event()
        self.__stop_event = stop_event

        self.__fifo_payload = list()   # FIFO traitement messages
        self.__fifo_transmit = list()  # FIFO d'evenements a transmettre
        
        self.__event_action = asyncio.Event()
        self.__lock_radio = Lock()
        self.__lock_reception = Lock()
        # self.__thread = None

        self.__radio_PA_level = int(environ.get('RF24_PA') or RF24.RF24_PA_MIN)
        self.__logger.info("Radio PA level : %d" % self.__radio_PA_level)
        
        self.__radio_pin = int(environ.get('RF24_RADIO_PIN') or Constantes.RPI_V2_GPIO_P1_22)
        self.__radio_irq = int(environ.get('RF24_RADIO_IRQ') or 24)

        if type_env == 'prod':
            self.__channel = Constantes.MG_CHANNEL_PROD
        elif type_env == 'int':
            self.__logger.info("Mode INT")
            self.__channel = Constantes.MG_CHANNEL_INT
        else:
            self.__logger.info("Mode DEV")
            self.__channel = Constantes.MG_CHANNEL_DEV

        self.irq_gpio_pin = None
        self.__radio = None
        self.__event_reception = asyncio.Event()

        self.__information_appareils_par_uuid = dict()

        self.__intervalle_beacon = datetime.timedelta(seconds=Constantes.INTERVALLE_BEACON)
        self.__prochain_beacon = datetime.datetime.utcnow()
        
        self.__message_beacon = None

    # def start(self):
    #     self.open_radio()
    #     self.thread = Thread(name="RF24Radio", target=self.run, daemon=True)
    #     self.thread.start()

    async def run(self):
        self.open_radio()

        self.__logger.info("RF24Radio: thread started successfully")

        try:
            while not self.__stop_event.is_set():
                await asyncio.to_thread(self.__transmettre_beacon)
                await asyncio.to_thread(self.__transmettre_paquets)
                try:
                    await asyncio.wait_for(self.__event_action.wait(), 0.25)
                except asyncio.TimeoutError:
                    pass
        finally:
            self.__logger.info("Arret de la radio")
            try:
                self.__radio.stopListening()
            except:
                pass
            GPIO.cleanup()

    def recevoir(self, message):
        # Ajouter payload sur liste FIFO
        if len(self.__fifo_payload) < 100:
            with self.__lock_reception:
                self.__fifo_payload.append(message)
        else:
            self.__logger.warning("FIFO reception message plein, message perdu")
        
        self.__event_reception.set()
    
    def transmettre(self, paquet: ProtocoleVersion9.PaquetTransmission):
        self.__fifo_transmit.append(paquet)
        self.__event_action.set()
        
    def __transmettre_paquets(self):
        # Clear flag de transmission
        self.__event_action.clear()

        event_attente = Event()

        while len(self.__fifo_transmit) > 0:
            event_attente.wait(0.05)  # Throttling, wait 50ms to receive data

            paquet = self.__fifo_transmit.pop(0)
            
            # Determiner adresse de transmission
            node_id = paquet.node_id
            if node_id is None or isinstance(paquet, ProtocoleVersion9.PaquetReponseDHCP):
                adresse = bytes(Constantes.ADDR_BROADCAST_DHCP)
            else:
                # Le premier byte de l'adresse est le node_id
                adresse = bytes([node_id]) + self.__adresse_reseau

            adresse_str = str(binascii.hexlify(adresse))
                
            # reponse = True
            try:
                self.__radio.openWritingPipe(adresse)

                # if not reponse:
                #     self.__logger.error("Erreur transmission vers : %s" % binascii.hexlify(adresse))
                #     break
                
                message = paquet.encoder()
                self.__logger.debug("Transmission paquet nodeId:%d, adresse:%s\n%s" % (
                    paquet.node_id, adresse_str, binascii.hexlify(message).decode('utf8')))

                # for essai in range(0, Constantes.TRANSMISSION_NB_ESSAIS):
                with self.__lock_radio:
                    self.__radio.stopListening()
                    # self.__logger.debug("Transmission paquet en cours")
                    reponse = self.__radio.write(message)
                    if reponse:
                        # Transmission reussie
                        self.__logger.debug("Transmission paquet OK (node_id: %s, adresse: %s)" % (node_id, adresse_str))
                        # break
                    self.__radio.startListening()
                # self.__stop_event.wait(0.002)  # Wait 2ms between attemps

                if not reponse:
                    self.__logger.debug("Transmission paquet ECHEC (node_id: %s, adresse: %s)" % (node_id, adresse_str))
                            
            except Exception:
                self.__logger.exception("Erreur tranmission message vers %s" % adresse_str)
            finally:
                # S'assurer de redemarrer l'ecoute de la radio
                self.__radio.startListening()

    def open_radio(self):
        self.__logger.info("Ouverture radio sur canal %s" % hex(self.__channel))
        self.__radio = RF24.RF24(self.__radio_pin, Constantes.BCM2835_SPI_CS0, Constantes.BCM2835_SPI_SPEED_8MHZ)

        if not self.__radio.begin():
            raise Exception("Erreur demarrage radio")

        self.__radio.setChannel(self.__channel)
        self.__radio.setDataRate(RF24.RF24_250KBPS)
        self.__radio.setPALevel(self.__radio_PA_level, False)  # Power Amplifier
        self.__radio.setRetries(1, 15)
        self.__radio.setAutoAck(1)
        self.__radio.setCRCLength(RF24.RF24_CRC_16)

        addresse_serveur = bytes(b'\x00\x00') + self.__adresse_serveur
        addresse_serveur = self.__formatAdresse(addresse_serveur)
        self.__radio.openReadingPipe(1, addresse_serveur)
        self.__logger.info("Address reading pipe 1: %s" % hex(addresse_serveur))

        # print("Radio details")
        # print( self.__radio.printDetails() )
        # print("Fin radio details")
        
        self.__logger.info("Radio ouverte")

        # Connecter IRQ pour reception paquets
        # Masquer TX OK et fail sur IRQ, juste garder payload ready
        self.__radio.maskIRQ(True, True, False)
        GPIO.setup(Constantes.PIN_IRQ, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(self.__radio_irq, GPIO.FALLING, callback=self.__process_network_messages)
    
    def __transmettre_beacon(self):
        if datetime.datetime.utcnow() > self.__prochain_beacon:
            # self.__logger.debug("Beacon")

            self.__prochain_beacon = datetime.datetime.utcnow() + self.__intervalle_beacon
            try:
                self.__radio.stopListening()
                self.__radio.openWritingPipe(Constantes.ADDR_BROADCAST_DHCP)
                self.__radio.write(self.__message_beacon, True)
            finally:
                self.__radio.startListening()
    
    def __process_network_messages(self, channel):
        if channel is not None and self.__logger.isEnabledFor(logging.DEBUG):
            self.__logger.debug("Message sur channel %d" % channel)

        with self.__lock_radio:
            while self.__radio.available():
                try:
                    payload = self.__radio.read(32)  # taille_buffer
                    self.recevoir(payload)
                except Exception as e:
                    self.__logger.exception("NRF24MeshServer: Error processing radio message")
    
    def __formatAdresse(self, adresse: bytes):
        adresse_paddee = adresse + bytes(8-len(adresse))
        adresse_no = struct.unpack('Q', adresse_paddee)[0]
        return adresse_no
        
    def set_adresse_serveur(self, adresse_serveur):
        self.__logger.info("Adresse serveur : %s" % binascii.hexlify(adresse_serveur).decode('utf-8'))
        self.__adresse_serveur = adresse_serveur
        # Preparer le paque beacon (il change uniquement si l'adresse du serveur change)
        self.__message_beacon = PaquetBeaconDHCP(self.__adresse_serveur).encoder()

    def set_adresse_reseau(self, adresse_reseau):
        self.__logger.info("Adresse reseau : %s" % binascii.hexlify(adresse_reseau).decode('utf-8'))
        self.__adresse_reseau = adresse_reseau
        
    @property
    def adresse_reseau(self):
        return self.__adresse_reseau
    
    def __iter__(self):
        return self

    def __next__(self):
        return self.next()

    def next(self):
        try:
            with self.__lock_reception:
                return self.__fifo_payload.pop(0)
        except IndexError:
            raise StopIteration()

    def wait_reception(self, timeout=None):
        """
        Attend qu'un evenement soit ajoute dans la FIFO
        :param timeout:
        :return: True si evenment set
        """
        self.__event_reception.wait(timeout)
        evenement_produit = self.__event_reception.is_set()
        self.__event_reception.clear()
        return evenement_produit


class NRF24Server:

    def __init__(self, idmg: str, type_env='prod'):
        """
        Environnements
        :param idmg: IDMG de la MilleGrille
        :param type_env: prod, int ou dev
        """

        self.__logger = logging.getLogger('%s.%s' % (__name__, self.__class__.__name__))
        self.__idmg = idmg
        self.__type_env = type_env

        self.__stop_event = asyncio.Event()
        self.reception_par_nodeId = dict()
        self.__assembleur_par_nodeId = dict()

        # Conserver le canal de communication
        if type_env == 'prod':
            pass
        elif type_env == 'int':
            pass
            # self.__logger.setLevel(logging.DEBUG)
            # logging.getLogger('mgraspberry').setLevel(logging.DEBUG)
        else:
            pass
            # self.__logger.setLevel(logging.DEBUG)
            # logging.getLogger('mgraspberry').setLevel(logging.DEBUG)

        self._callback_soumettre = None
        self.thread = None

        # Path et fichiers de configuration
        path_configuration = environ.get('RF24_CONFIG_PATH') or Constantes.PATH_CONFIGURATION
        makedirs(path_configuration, exist_ok=True)

        self.__path_configuration_reseau = environ.get('RF24_RESEAU_CONF') or \
            path.join(path_configuration, Constantes.FICHIER_CONFIG_RESEAU)
        self.__configuration = None
        
        path_configuration_dhcp = environ.get('RF24_DHCP_CONF') or \
            path.join(path_configuration, Constantes.FICHIER_CONFIG_DHCP)
        self.__reserve_dhcp = ReserveDHCP(path_configuration_dhcp)
        
        self.__information_appareils_par_uuid = dict()

        self.__traitement_radio = RadioThread(self.__stop_event, type_env)

        self.__cle_privee = None
        self.__adresse_serveur = None

        self.initialiser_configuration()

    def set_callback_lecture(self, callback):
        self._callback_soumettre = callback

    def initialiser_configuration(self):
        # Charger les fichiers de configuration
        try:
            self.__reserve_dhcp.charger_fichier_dhcp()
        except FileNotFoundError:
            self.__logger.info("Initialiser fichier DHCP")
            self.__reserve_dhcp.sauvegarder_fichier_dhcp()

        try:
            with open(path.join(self.__path_configuration_reseau), 'r') as fichier:
                self.__configuration = json.load(fichier)
            self.__logger.info("Charge configuration:\n%s" % json.dumps(self.__configuration, indent=4))

            adresses = self.__configuration['adresses']
            
            adresse_serveur = binascii.unhexlify(adresses['serveur'].encode('utf8'))
            adresse_reseau = binascii.unhexlify(adresses['reseau'].encode('utf8'))
            cle_privee_bytes = binascii.unhexlify(self.__configuration['cle_privee'].encode('utf8'))
            self.__cle_privee = donna25519.PrivateKey.load(cle_privee_bytes)

        except FileNotFoundError:
            self.__logger.info("Creation d'une nouvelle configuration pour le serveur")

            adresse_serveur = urandom(3)  # Generer 3 bytes pour l'adresse serveur receiving pipe
            adresse_reseau = urandom(4)   # Generer 4 bytes pour l'adresse du reseau
            
            self.__cle_privee = donna25519.PrivateKey()
            
            configuration = {
                'adresses': {
                    'serveur': binascii.hexlify(adresse_serveur).decode('utf8'),
                    'reseau': binascii.hexlify(adresse_reseau).decode('utf8'),
                },
                'cle_privee': binascii.hexlify(self.__cle_privee.private).decode('utf-8'),
            }
            self.__logger.debug("Configuration: %s" % str(configuration))
            with open(self.__path_configuration_reseau, 'w') as fichier:
                json.dump(configuration, fichier)
            self.__configuration = configuration

        self.__traitement_radio.set_adresse_serveur(adresse_serveur)
        self.__traitement_radio.set_adresse_reseau(adresse_reseau)

    # # Starts thread and runs the process
    # def start(self, callback_soumettre):
    #     self.__traitement_radio.start()
    #     self._callback_soumettre = callback_soumettre
    #     self.thread = Thread(name="RF24Server", target=self.run, daemon=True)
    #     self.thread.start()

    async def __process_paquets(self):
        for payload in self.__traitement_radio:
            self.__logger.debug("Payload %s bytes\n%s" % (len(payload), binascii.hexlify(payload).decode('utf-8')))
            await asyncio.to_thread(self.process_paquet_payload, payload)
                
    async def __executer_cycle(self):
        # Traiter paquets dans FIFO
        await self.__process_paquets()

    async def run(self):
        self.__logger.info("RF24Server: thread started successfully")

        # self.__traitement_radio.start()
        # self._callback_soumettre = callback_soumettre
        #
        # # Boucle principale d'execution
        # while not self.__stop_event.is_set():
        #     try:
        #         self.__executer_cycle()
        #         # Throttle le service
        #         self.__traitement_radio.wait_reception(2.0)
        #     except Exception as e:
        #         self.__logger.exception("NRF24Server: Error processing update ou DHCP")
        #         self.__stop_event.wait(5)  # Attendre 5 secondes avant de poursuivre

        tasks = [
            asyncio.create_task(self.__traitement_radio.run()),
            asyncio.create_task(self.__executer_cycle()),
        ]

        await asyncio.tasks.wait(tasks, return_when=asyncio.tasks.FIRST_COMPLETED)

        self.__logger.info("RF24Server: Fin Run Thread RF24Server")

    def process_dhcp_request(self, payload):
        paquet = PaquetDemandeDHCP(payload)

        # On utilise le node id actuel (pour repondre) comme suggestion
        node_id_reserve = self.__reserve_dhcp.reserver(paquet.uuid)
        self.__logger.debug("Transmission DHCP reponse nodeId: %d (reponse vers %s)" % (node_id_reserve, str(paquet.uuid)))

        # On transmet la reponse
        self.transmettre_response_dhcp(node_id_reserve, paquet.uuid)

    def process_paquet0(self, node_id, payload):
        self.__logger.debug("Paquet 0 recu")
        paquet0 = Paquet0(payload)
        self.__logger.debug("Paquet 0 info : %s, %s" % (paquet0.from_node, paquet0.is_multi_paquets()))
        
        if paquet0.is_multi_paquets():
            self.__logger.debug("Paquet 0 - multi paquets")
            uuid_senseur = binascii.hexlify(paquet0.uuid).decode('utf-8')
            info_appareil = self.__information_appareils_par_uuid.get(uuid_senseur)
            message = AssembleurPaquets(paquet0, info_appareil)
            self.__assembleur_par_nodeId[node_id] = message
        else:
            # Traiter le contenu immediatement - 1 seul paquet pour ce type
            self.__logger.debug("Paquet 0 - Traiter message complet")
            info_appareil = self.get_infoappareil_par_nodeid(paquet0.from_node)
            message = AssembleurPaquets(paquet0, info_appareil)
            try:
                self._assembler_message(message)
            except TypeError as te:
                self.__logger.warning("Erreur lecture paquet0 node id:%s, probablement cle invalide: %s" % (paquet0.from_node, str(te)))
            except KeyError as ke:
                self.__logger.warning("Erreur lecture paquet0 node id:%s, probablement iv manquant: %s" % (paquet0.from_node, str(ke)))

    def process_paquet_payload(self, payload):
        
        # Extraire premier bytes pour routing / traitement
        # Noter que pour les paquets cryptes, type_paquet n'est pas utilisable
        version, from_node_id, no_paquet, type_paquet = struct.unpack('BBHH', payload[0:6])
        
        if version == VERSION_PROTOCOLE:
            self.__logger.debug("Node Id: %d Type paquet: %d, no: %d" % (from_node_id, type_paquet, no_paquet))

            if no_paquet == 0:
                if type_paquet == TypesMessages.TYPE_REQUETE_DHCP:
                    self.process_dhcp_request(payload)
                else:
                    # Paquet0
                    self.process_paquet0(from_node_id, payload)
            else:
                assembleur = self.__assembleur_par_nodeId.get(from_node_id)
                if assembleur is not None:
                    try:
                        complet = assembleur.recevoir(payload)
                        if complet:
                            try:
                                self._assembler_message(assembleur)
                            except ValueError as ve:
                                self.__logger.error("%s" % str(ve))
                            finally:
                                del self.__assembleur_par_nodeId[from_node_id]
                    except ProtocoleVersion9.ExceptionCipherNonDisponible as e:
                        self.__logger.warning("Cipher non disponible %s:" % str(e))
                else:
                    self.__logger.info("Message dropped, paquet 0 inconnu pour nodeId:%d" % from_node_id)
        else:
            self.__logger.warning("Message version non supportee : %d" % version)

    def _assembler_message(self, assembleur):
        self.__logger.debug("Assembler message")
        node_id = assembleur.node_id
        
        # Recuperer information appareil, utilise pour messages a 1 paquet
        info_appareil = self.get_infoappareil_par_nodeid(node_id)
        
        message, paquet_ack = assembleur.assembler(info_appareil)
        # message_json = json.dumps(message, indent=2)
        # self.__logger.debug("Message complet: \n%s" % message_json)

        if assembleur.iv is not None:
            # Conserver le nouveau IV candidat pour l'appareil
            self.__ajouter_iv_appareil(info_appareil, assembleur.iv)

        # Transmettre message recu a MQ
        if assembleur.type_transmission == TypesMessages.MSG_TYPE_LECTURES_COMBINEES:
            self.transmettre_ack(paquet_ack)
            self._callback_soumettre(message)
        elif assembleur.type_transmission == TypesMessages.MSG_TYPE_NOUVELLE_CLE:
            self.__logger.debug("Nouvelle cle : %s" % message)
            self.__ajouter_cle_appareil(assembleur.node_id, message)
        elif assembleur.type_transmission == TypesMessages.MSG_TYPE_ECHANGE_IV:
            info_appareil = self.__information_appareils_par_uuid[assembleur.uuid_appareil]
            self.__logger.debug("Nouveau IV recu : %s" % binascii.hexlify(info_appareil['iv_candidat']))
            # Rien a faire, le IV est sauvegarde automatiquement sur chaque paquet IV confirme
        elif assembleur.type_transmission == TypesMessages.MSG_TYPE_IV:
            # self.__ajouter_iv_appareil(assembleur.uuid_appareil, message['iv'])
            self.__logger.debug("Nouveau IV recu : %s" % binascii.hexlify(info_appareil['iv_candidat']))
        else:
            if message is not None:
                self._callback_soumettre(message)
            if paquet_ack:
                self.transmettre_ack(paquet_ack)

    def transmettre_ack(self, paquet_ack):
        self.__logger.debug("Transmettre ACK vers Id: %s" % str(paquet_ack.node_id))
        self.transmettre_paquets([paquet_ack], paquet_ack.node_id)

    def transmettre_response_dhcp(self, node_id_assigne, node_uuid):
        """
        Repond a une demande DHCP d'un appareil.
        """
        paquet = PaquetReponseDHCP(self.__traitement_radio.adresse_reseau, node_id_assigne, node_uuid)
        self.__logger.debug("Transmettre reponse DHCP vers: %s" % binascii.hexlify(node_uuid).decode('utf-8'))
        self.transmettre_paquets([paquet])

    def transmettre_paquets(self, paquets: list, node_id = None):
        """
        Transmet une sequence de paquets relies. Si un paquet echoue,
        le reste des paquets ne seront pas transmis.
        """
        for paquet in paquets:
            self.__traitement_radio.transmettre(paquet)

    # Close all connections and the radio
    def fermer(self):
        self.__stop_event.set()
        try:
            self.__radio.stopListening()
            self.__radio = None
        except Exception as e:
            self.__logger.warning("NRF24MeshServer: Error closing radio: %s" % str(e))

    def __ajouter_iv_appareil(self, info_appareil, iv):
        # info_appareil = self.__information_appareils_par_uuid.get(uuid_senseur)
        self.__logger.debug("Nouveau IV pour appareil %s : %s" % (info_appareil['uuid'], binascii.hexlify(iv)))
        if info_appareil is not None:
            info_appareil['iv'] = info_appareil.get('iv') or iv  # Ne pas remplacer IV existant
            info_appareil['iv_candidat'] = iv

    def __ajouter_cle_appareil(self, node_id, message):
        self.__logger.debug("Messages : %s" % str(message))
        uuid_senseur = message['uuid_senseur']
        uuid_senseur_bytes = binascii.unhexlify(uuid_senseur.encode('utf-8'))
        cle = message['cle_publique']
        crc32_recu = message['crc32']
        self.__logger.debug("Recu cle publique appareil : %s" % binascii.hexlify(cle))

        # Valider la cle avec le CRC32
        calcul_crc32 = crc32(uuid_senseur_bytes + cle) & 0xffffffff
        crc32_recu_int = unpack('I', crc32_recu)[0]
        self.__logger.debug(
            "CRC32 cle calcule %s, recu %s" % (
                hex(calcul_crc32),
                hex(crc32_recu_int)
            )
        )
        if calcul_crc32 != crc32_recu_int:
            raise Exception("CRC32 cle different de celui recu")

        # Conserver la cle publique de l'appareil pour reference future
        self.__reserve_dhcp.conserver_cle(uuid_senseur_bytes, cle)
        
        # Generer nouvelle cle ed25519 pour identifier cle partagee
        appareil_side = donna25519.PublicKey(cle)
        # serveur_side = donna25519.PrivateKey()
        shared_key = self.__cle_privee.do_exchange(appareil_side)
        # self.__logger.debug("Cle shared %s : %s" % (uuid_senseur, binascii.hexlify(shared_key)))
        
        # Transmettre serveur side public
        serveur_side_public = bytes(self.__cle_privee.get_public().public)
        self.__logger.debug("Cle publique serveur : %s" % binascii.hexlify(serveur_side_public))
        # self.__logger.debug("Cle privee serveur : %s" % binascii.hexlify(bytes(serveur_side)))
        
        paquets = [
            ProtocoleVersion9.PaquetReponseCleServeur1(node_id, serveur_side_public),
            ProtocoleVersion9.PaquetReponseCleServeur2(node_id, serveur_side_public),
        ]
        self.__logger.debug("Transmission paquet cle publique vers reponse nodeId:%d" % node_id)
        self.transmettre_paquets(paquets, node_id)
        
        info_appareil = self.__information_appareils_par_uuid.get(uuid_senseur)
        if info_appareil is None:
            info_appareil = {'uuid': uuid_senseur}
            self.__information_appareils_par_uuid[uuid_senseur] = info_appareil
        info_appareil['cle_partagee'] = shared_key
        info_appareil['node_id'] = node_id

    def get_infoappareil_par_nodeid(self, node_id: int):
        for uuid_appareil, info_app in self.__information_appareils_par_uuid.items():
            if info_app['node_id'] == node_id:
                self.__logger.debug("get_infoappareil_par_nodeid: Info app : %s" % str(info_app))
                # info_complete['uuid'] = uuid_appareil
                return info_app
        
        # On n'a pas l'information par uuid, tenter de charger avec info
        # connue dans le DHCP
        info_appareil = self.__reserve_dhcp.get_info_par_nodeid(node_id)
        if info_appareil is not None:
            self.__logger.debug("Recharger appareil connu : %s" % str(info_appareil))
            # On a trouve, charger la base de l'information
            info_mappee = {
                'uuid': info_appareil['uuid'],
                'node_id': info_appareil['node_id']
            }

            # Recalculer la cle partagee
            try:
                cle_publique = binascii.unhexlify(info_appareil.get('cle_publique'))
                appareil_side = donna25519.PublicKey(cle_publique)
                shared_key = self.__cle_privee.do_exchange(appareil_side)

                info_mappee['cle_publique'] = cle_publique
                info_mappee['cle_partagee'] = shared_key
            except TypeError:
                self.__logger.exception("Erreur chargement cle publique")
            
            # Note : la cle (uuid) est en format hex str, pas en bytes
            self.__information_appareils_par_uuid[info_appareil['uuid']] = info_mappee
            
            return info_appareil
        
        return None


class ReserveDHCP:
    """
    Gestionnaire DHCP des appareils RF24
    """

    def __init__(self, fichier_dhcp: str):
        self.__node_id_by_uuid = dict()
        self.__fichier_dhcp = fichier_dhcp

        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

    def charger_fichier_dhcp(self):
        with open(self.__fichier_dhcp, 'r') as fichier:
            node_id_str_by_uuid = json.load(fichier)

        for uuid_str, value in node_id_str_by_uuid.items():
            uuid_bytes = binascii.unhexlify(uuid_str.encode('utf8'))
            self.__node_id_by_uuid[uuid_bytes] = value

    def sauvegarder_fichier_dhcp(self):

        # Changer la cle de bytes a str
        node_id_str_by_uuid = dict()
        for uuid_bytes, value in self.__node_id_by_uuid.items():
            uuid_str = binascii.hexlify(uuid_bytes).decode('utf8')
            node_id_str_by_uuid[uuid_str] = value

        with open(self.__fichier_dhcp, 'w') as fichier:
            json.dump(node_id_str_by_uuid, fichier)

    def conserver_cle(self, uuid: bytes, cle_publique: bytes):
        """
        Conserver la cle publique d'un appareil
        """
        try:
            config_appareil = self.__node_id_by_uuid[uuid]
        except KeyError:
            config_appareil = dict()
            self.__node_id_by_uuid[uuid] = config_appareil

        config_appareil['cle_publique'] = binascii.hexlify(cle_publique).decode('utf8')

        self.__logger.debug("UUID %s, cle publique = %s" % (binascii.hexlify(uuid), config_appareil['cle_publique']))
        self.sauvegarder_fichier_dhcp()

    def get_node_id(self, uuid: bytes):
        node_config = self.__node_id_by_uuid.get(uuid)
        if node_config is not None:
            return node_config['node_id']
        return None

    def get_info_par_uuid(self, uuid: bytes):
        return self.__node_id_by_uuid.get(uuid)

    def get_info_par_nodeid(self, node_id: int):
        for uuid_app, info in self.__node_id_by_uuid.items():
            if info.get('node_id') == node_id:
                info_complete = info.copy()
                info_complete['uuid'] = binascii.hexlify(uuid_app).decode('utf8')
                return info_complete
        return None

    def reserver(self, uuid: bytes):
        try:
            info_node = self.__node_id_by_uuid[uuid]
        except KeyError:
            info_node = dict()
            self.__node_id_by_uuid[uuid] = info_node

        try:
            node_id = info_node['node_id']
        except KeyError:
            node_id = self.__identifier_nouvelle_adresse()
            info_node['node_id'] = node_id

            self.__logger.debug("UUID %s, reservation node id = %s" % (binascii.hexlify(uuid), node_id))
            self.sauvegarder_fichier_dhcp()

        return node_id

    def __identifier_nouvelle_adresse(self):
        """
        Donne la prochaine adresse disponible entre 2 et 254
        Adresse 0xff (255) est pour broadcast, tous les noeuds ecoutent
        :return:
        """

        node_id_list = list()
        for config in self.__node_id_by_uuid.values():
            try:
                node_id_list.append(config['node_id'])
            except KeyError:
                pass

        # node_id_list = [config['node_id'] for config in self.__node_id_by_uuid.values()]
        for node_id in range(2, 254):
            if node_id not in node_id_list:
                return node_id

        return None

