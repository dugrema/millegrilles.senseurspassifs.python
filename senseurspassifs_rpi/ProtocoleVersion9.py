import binascii
import datetime
import logging

from struct import pack, unpack
from zlib import crc32

# from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from CryptoLW import Acorn128

VERSION_PROTOCOLE = 9

class TypesMessages:
    
    TYPE_PAQUET0      = 0x0000
    TYPE_PAQUET_IV    = 0xFFFE
    TYPE_PAQUET_FIN   = 0xFFFF
    TYPE_REQUETE_DHCP = 0x0001
    TYPE_REPONSE_DHCP = 0x0002
    TYPE_BEACON_DHCP  = 0x0003
    MSG_TYPE_REPONSE_ACK  = 0x0009
    MSG_TYPE_ECHANGE_IV   = 0x000A

    MSG_TYPE_CLE_APPAREIL_1 = 0x0004
    MSG_TYPE_CLE_APPAREIL_2 = 0x0005
    MSG_TYPE_CLE_SERVEUR_1  = 0x0006
    MSG_TYPE_CLE_SERVEUR_2  = 0x0007
    MSG_TYPE_NOUVELLE_CLE   = 0x0008
    MSG_TYPE_REPONSE_ACK    = 0x0009
        
    MSG_TYPE_LECTURES_COMBINEES = 0x101
    MSG_TYPE_LECTURE_TH         = 0x102
    MSG_TYPE_LECTURE_TP         = 0x103
    MSG_TYPE_LECTURE_POWER      = 0x104
    MSG_TYPE_LECTURE_ONEWIRE    = 0x105
    MSG_TYPE_LECTURE_ANTENNE    = 0x106
    
    MSG_TYPE_LECTURE_TH_ANTENNE_POWER = 0x0202
    MSG_TYPE_LECTURE_TP_ANTENNE_POWER = 0x0203
    MSG_TYPE_LECTURE_ONEWIRE          = 0x0204
    MSG_TYPE_IV                       = 0x0205
    
    @staticmethod
    def map_type_message(type_message: int):
        if type_message == TypesMessages.MSG_TYPE_LECTURE_TH_ANTENNE_POWER:
            return MessageTemperatureHumiditeAntennePower
        elif type_message == TypesMessages.MSG_TYPE_LECTURE_TP_ANTENNE_POWER:
            return MessageTemperaturePressionAntennePower
        elif type_message == TypesMessages.MSG_TYPE_LECTURE_ONEWIRE:
            return MessageOnewireTemperature
        elif type_message == TypesMessages.MSG_TYPE_IV:
            return MessageIv
        else:
            raise Exception("Type inconnu : %d" % type_message)


class Paquet:
    """
    Paque de donnees recues
    """

    def __init__(self, data: bytes):
        self.__data = data

        self.version = None
        self.type_message = None

        self._parse()

    def _parse(self):
        self.version = self.data[0]
        self.type_message = self.data[4:6]

    def assembler(self):
        raise NotImplementedError()

    @property
    def data(self):
        return self.__data

    @property
    def from_node(self):
        return self.data[1]


class Paquet0(Paquet):

    def __init__(self, data: bytes):
        self.uuid = None
        self.type_transmission = None
        self.type_message = None
        super().__init__(data)
        
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

    def _parse(self):
        super()._parse()
        self.type_message = unpack('H', self.data[4:6])[0]
        self.type_transmission = unpack('H', self.data[6:8])[0]
        self.uuid = self.data[8:24]

    def __str__(self):
        return 'Paquet0 UUID: %s, type: %s' % (
            binascii.hexlify(self.uuid).decode('utf-8'),
            binascii.hexlify(self.type_message).decode('utf-8')
        )
        
    def is_multi_paquets(self):
        """
        :return: True si le message requiert plusieurs paquets, False si le message est complet.
        """
        classe_message = self.type_message >> 8
        self.__logger.debug("Classe de message recu : %d = classe %d" % (self.type_message, classe_message))
        return classe_message not in [0x02]
        
    def assembler(self):
        return dict()


class PaquetDemandeDHCP(Paquet):

    def __init__(self, data: bytes):
        self.uuid = None
        super().__init__(data)
        self.cle_publique_debut = None

    def _parse(self):
        super()._parse()
        self.uuid = bytes(self.data[6:22])

    def assembler(self):
        return dict()


class PaquetPayload(Paquet):

    def __init__(self, data: bytes):
        self.__no_paquet = None
        super().__init__(data)

    def _parse(self):
        super()._parse()
        self.__no_paquet = unpack('H', self.data[2:4])[0]

    @property
    def no_paquet(self):
        return self.__no_paquet


class PaquetIv(PaquetPayload):

    def __init__(self, data: bytes):
        self.iv = None
        super().__init__(data)

    def _parse(self):
        super()._parse()
        self.iv = self.data[6:22]

    def __str__(self):
        return 'Paquet IV : %s, no paquet: %d' % (
            binascii.hexlify(self.iv).decode('utf-8'),
            self.no_paquet
        )
        
    def assembler(self):
        return dict()
        

class PaquetFin(PaquetPayload):

    def __init__(self, data: bytes):
        self.tag = None
        self.nb_paquets = None
        super().__init__(data)

    @property
    def no_paquet(self):
        return self.nb_paquets

    def _parse(self):
        super()._parse()
        self.nb_paquets = unpack('H', self.data[6:8])[0]
        self.tag = self.data[8:24]

    def __str__(self):
        # binascii.hexlify(self.tag).decode('utf-8'),
        return 'Paquet Fin tag: %s, nb paquets: %d' % (
            binascii.hexlify(self.tag),
            self.nb_paquets
        )
        
    def assembler(self):
        return dict()


class PaquetCleAppareil1(PaquetPayload):
    
    def __init__(self, data: bytes):
        self.cle_publique_debut = None
        super().__init__(data)

    def _parse(self):
        super()._parse()
        self.cle_publique_debut = self.data[6:32]

    def __str__(self):
        return 'Paquet cle appareil debut: %s' % binascii.hexlify(self.cle_publique_debut)
        
    def assembler(self):
        return [{
            'cle_publique_debut': self.cle_publique_debut,
        }]
        

class PaquetCleAppareil2(PaquetPayload):
    
    def __init__(self, data: bytes):
        self.cle_publique_fin = None
        self.crc32 = None
        super().__init__(data)

    def _parse(self):
        super()._parse()
        self.cle_publique_fin = self.data[6:12]
        self.crc32 = self.data[12:16]

    def __str__(self):
        return 'Paquet cle appareil fin: %s' % (
            str(binascii.hexlify(self.cle_publique_fin)),
        )
        
    def assembler(self):
        return [{
            'cle_publique_fin': self.cle_publique_fin,
            'crc32': self.crc32,
        }] 
        
        
class PaquetTP(PaquetPayload):
    def __init__(self, data: bytes):
        self.temperature = None
        self.pression = None
        super().__init__(data)

    def _parse(self):
        super()._parse()
        th_values = unpack('hH', self.data[6:10])
        temperature = th_values[0]
        pression = th_values[1]

        if temperature == -32768:
            self.temperature = None
        else:
            self.temperature = float(temperature) / 10.0
        if pression == 0xFF:
            self.pression = None
        else:
            self.pression = float(pression) / 100.0

    def assembler(self):
        return [
            {
                'nom': 'tp/temperature',
                'valeur': self.temperature,
                'type': 'temperature',
            },
            {
                'nom': 'tp/pression',
                'valeur': self.pression,
                'type': 'pression',
            }
        ]

    def __str__(self):
        return 'Temperature {}, Pression {}'.format(self.temperature, self.pression)


class PaquetTH(PaquetPayload):
    def __init__(self, data: bytes):
        self.temperature = None
        self.pression = None
        super().__init__(data)

    def _parse(self):
        super()._parse()
        th_values = unpack('hH', self.data[6:10])
        temperature = th_values[0]
        humidite = th_values[1]

        if temperature == -32768:
            self.temperature = None
        else:
            self.temperature = float(temperature) / 10.0
        if humidite == 0xFF:
            self.humidite = None
        else:
            self.humidite = float(humidite) / 10.0

    def assembler(self):
        return [
            {
                'nom': 'th/temperature',
                'valeur': self.temperature,
                'type': 'temperature',
            },
            {
                'nom': 'th/humidite',
                'valeur': self.humidite,
                'type': 'humidite',
            }
        ]

    def __str__(self):
        return 'Temperature {}, Humidite {}'.format(self.temperature, self.humidite)


class PaquetPower(PaquetPayload):
    def __init__(self, data: bytes):
        self.millivolt = None
        self.reserve = None
        self.alerte = None
        super().__init__(data)

    def _parse(self):
        super()._parse()
        th_values = unpack('IBB', self.data[6:12])
        millivolt = th_values[0]
        reserve = th_values[1]
        self.alerte = th_values[2]

        if millivolt == 0xFFFFFFFF:
            self.millivolt = None
        else:
            self.millivolt = millivolt
        if reserve == 0xFF:
            self.reserve = None
        else:
            self.reserve = reserve

    def assembler(self):
        return [
            {
                'nom': 'batterie/millivolt',
                'valeur': self.millivolt,
                'type': 'millivolt',
            },
            {
                'nom': 'batterie/reserve',
                'valeur': self.reserve,
                'type': 'pct',
            },
            {
                'nom': 'batterie/alerte',
                'valeur': self.alerte,
                'type': 'bool',
            }
        ]

    def __str__(self):
        return 'Millivolt {}, Reserve {}, Alerte {}'.format(self.millivolt, self.reserve, self.alerte)


class PaquetOneWire(PaquetPayload):

    def __init__(self, data: bytes):
        self.adresse_onewire = None
        self.data_onewire = None
        super().__init__(data)

    def _parse(self):
        super()._parse()
        adresse_onewire, data_onewire = PaquetOneWire.decoder_onewire(self.data[6:26])
        self.adresse_onewire = adresse_onewire
        self.data_onewire = data_onewire

    @staticmethod
    def decoder_onewire(data):
        adresse_onewire = data[0:8]
        data_onewire = data[8:20]
        return adresse_onewire, data_onewire

    def assembler(self):
        return [{
            'nom': 'onewire/' + binascii.hexlify(self.adresse_onewire).decode('utf-8'),
            'valeur': binascii.hexlify(self.data_onewire).decode('utf-8'),
            'type': 'hex'
        }]

    def __str__(self):
        return 'OneWire adresse {}, data {}'.format(
            binascii.hexlify(self.adresse_onewire).decode('utf-8'),
            binascii.hexlify(self.data_onewire).decode('utf-8')
        )


class PaquetOneWireTemperature(PaquetOneWire):

    def __init__(self, data: bytes):
        self.temperature = None
        super().__init__(data)

    def _parse(self):
        super()._parse()
        self.__decoder_temperature()

    def assembler(self):
        return [{
            'nom': 'onewire/' + binascii.hexlify(self.adresse_onewire).decode('utf-8'),
            'valeur': self.temperature,
            'type': 'temperature'
        }]

    def __decoder_temperature(self):
        self.temperature = PaquetOneWireTemperature.decoder_temperature(self.data_onewire)
    
    @staticmethod
    def decoder_temperature(data):
        val = data[0:2]
        if bytes(val) == bytes([0xFF, 0xFF]):
            return None  # Lecture nulle
        else:
            temp_val = unpack('h', val)[0]
            return temp_val / 16

    def __str__(self):
        return 'OneWire adresse {}, temperature {}, data {}'.format(
            binascii.hexlify(self.adresse_onewire).decode('utf-8'),
            self.temperature,
            binascii.hexlify(self.data_onewire).decode('utf-8'),
        )


class PaquetAntenne(PaquetPayload):

    def __init__(self, data: bytes):
        self.pct_signal = None
        self.force_emetteur = None
        self.canal = None
        super().__init__(data)

    def _parse(self):
        super()._parse()
        values = unpack('BBB', self.data[6:9])
        self.pct_signal = values[0]
        self.force_emetteur = values[1]
        self.canal = values[2]

    def assembler(self):
        return [
            {
                'nom': 'antenne/signal',
                'type': 'pct',
                'valeur': self.pct_signal,
            },
            {
                'nom': 'antenne/force',
                'type': 'int',
                'valeur': self.force_emetteur,
            },
            {
                'nom': 'antenne/canal',
                'type': 'int',
                'valeur': self.canal,
            },
        ]

    def __str__(self):
        return 'Antenne  pctSignal {}%, forceEmetteur {}, canal {}'.format(
            self.pct_signal,
            self.force_emetteur,
            hex(self.canal),
        )


class AssembleurPaquets:

    def __init__(self, paquet0: Paquet0, info_appareil = None):
        self.__paquet0 = paquet0
        self.__info_appareil = info_appareil
        self.__timestamp_debut = datetime.datetime.now()
        self.__tag = None
        self.__tag_calcule = None
        self.__iv = None
        self.__iv_confirme = False

        self.__paquets = dict()
        self.__paquets[0] = paquet0
        
        self.__cipher = None
        self.__message_crypte = False
        
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)

    @property
    def uuid_appareil(self):
        return binascii.hexlify(self.__paquet0.uuid).decode('utf-8')
        
    @property
    def node_id(self):
        return self.__paquet0.from_node

    def recevoir(self, data: bytes):
        """
        Recoit un nouveau paquet de payload. Retourne True quand tous les paquets sont recus.
        :param data:
        :return: True si tous les paquets ont ete recus
        """
        paquet = self.map(data)
        if paquet is not None:
            self.__logger.debug("Paquet: %s" % str(paquet))
            self.__paquets[paquet.no_paquet] = paquet

            if isinstance(paquet, PaquetIv):
                self.__iv = paquet.iv
                self.__message_crypte = True
                
                if self.__info_appareil is not None:
                    cle_partagee = self.__info_appareil.get('cle_partagee')
                    if cle_partagee is not None:
                        # Activer cipher
                        # self.__cipher = AES.new(cle_partagee, AES.MODE_EAX, nonce=self.__iv)
                        self.__cipher = Acorn128()
                        self.__cipher.setKey(cle_partagee[0:16])
                        self.__cipher.setIV(self.__iv)
                    
                        # Ajouter donnees auth (paquet 0, 22 bytes)
                        # self.__cipher.update(self.__paquets[0].data[0:22])
                        self.__cipher.addAuthData(self.__paquets[0].data[0:22])
                    else:
                        self.__logger.warning("Cle partagee non disponible, message va etre ignore")
                else:
                    self.__logger.warning("Cle partage non disponible - aucune info appareil")

            if isinstance(paquet, PaquetFin):
                self.__tag = paquet.tag
                return True

        else:
            self.__logger.error("Paquet non decodable : %s" % binascii.hexlify(data).decode('utf-8'))

        return False

    def assembler(self, info_appareil: dict = None):
        if self.__paquet0.is_multi_paquets():
            return self.assembler_multi_paquets()
        else:
            return self.assembler_paquet0(info_appareil)

    def assembler_multi_paquets(self):
    
        """
        :throws ValueError: Si tag ne correspond pas
        """
        liste_ordonnee = list()
        
        if self.__message_crypte:
            if self.__cipher is not None:
                # Verifier le tag (hash)
                try:
                    self.__cipher.checkTag(self.__tag)
                except ValueError:
                    raise ValueError("%s: Message tag invalide" % self.uuid_appareil)
            else:
                raise ValueError("%s: Message crypte mais cle non disponible" % self.uuid_appareil)

        try:
            for idx in range(1, len(self.__paquets)):
                liste_ordonnee.append(self.__paquets[idx])
        except KeyError:
            raise ValueError("%s: Transmission incomplete, paquet manquant sur message" % self.uuid_appareil)

        timestamp_message = int(self.__timestamp_debut.timestamp())

        # Preparer lecture senseurs
        senseurs = dict()
        cle_publique = list()
        crc32_cle_publique = None
        for paquets_assembles in [s.assembler() for s in liste_ordonnee]:
            if self.__iv_confirme is False and self.__iv is not None:
                # On a recu un paquet apres le IV, l'appareil sait qu'on l'a recu
                self.__iv_confirme = True

            for lecture in paquets_assembles:
                self.__logger.debug("Lecture RF24 : %s" % lecture)
                try:
                    if lecture.get('cle_publique_debut'):
                        cle_publique.append(lecture['cle_publique_debut'])
                        
                    if lecture.get('cle_publique_fin'):
                        cle_publique.append(lecture['cle_publique_fin'])
                        crc32_cle_publique = lecture['crc32']

                    if lecture.get('type') and lecture.get('nom'):
                        # Ajouter timestamp
                        nom_senseur = lecture.get('nom')
                        del lecture['nom']
                        lecture['timestamp'] = timestamp_message
                        senseurs[nom_senseur] = lecture

                except IndexError:
                    self.__logger.exception("Erreur traitement lecture")
                except KeyError:
                    self.__logger.exception("Erreur traitement lecture")

        dict_message = {
            'mesh_address': self.__paquet0.from_node,
            'uuid_senseur': self.uuid_appareil,
            'senseurs': senseurs,
        }

        if len(cle_publique) == 2:
            cle_combinee = bytes(cle_publique[0] + cle_publique[1])
            self.__logger.debug("Cle publique senseur : %s" % cle_combinee)
            
            # # Valider la cle avec le CRC32
            # calcul_crc32 = crc32(cle_combinee) & 0xffffffff
            # crc32_recu_int = unpack('I', crc32_cle_publique)[0]
            # self.__logger.debug(
            #     "CRC32 cle calcule %s, recu %s" % (
            #         hex(calcul_crc32),
            #         hex(crc32_recu_int)
            #     )
            # )
            # if calcul_crc32 != crc32_recu_int:
            #     raise Exception("CRC32 cle different de celui recu")

            dict_message['cle_publique'] = cle_combinee
            dict_message['crc32'] = crc32_cle_publique

        paquet_ack = PaquetACKTransmission(self.__paquet0.from_node, self.__tag)

        return dict_message, paquet_ack
    
    def assembler_paquet0(self, info_appareil: dict):
        """
        Utilise pour assemble un message complet en un paquet
        """
        type_message = self.__paquet0.type_message
        classe_message = TypesMessages.map_type_message(type_message)
        paquet = classe_message(self.__paquet0.data, info_appareil)

        senseurs, ack_NA = paquet.assembler()

        try:
            self.__iv = paquet.iv
            self.__iv_confirme = True
        except AttributeError:
            pass  # Ok, IV present sur message IV seulement
        
        if senseurs is None:
            return None, None  # Rien a faire
            
        dict_message = {
            'mesh_address': self.__paquet0.from_node,
            'uuid_senseur': info_appareil['uuid'],
            'senseurs': senseurs,
        }

        return dict_message, None
    
    @property
    def doit_decrypter(self):
        return self.__iv is not None
        
    @property
    def type_transmission(self):
        return self.__paquet0.type_transmission

    @property
    def iv(self):
        return self.__iv

    @property
    def iv_confirme(self):
        return self.__iv_confirme

    def map(self, data: bytes):
        no_paquet, type_message = unpack('HH', data[2:6])
        self.__logger.debug("Mapping node_id %d noPaquet : %d, type paquet : %d" % (self.node_id, no_paquet, type_message))
        
        paquet = None
        if no_paquet == TypesMessages.TYPE_PAQUET_FIN:
            paquet = PaquetFin(data)
        elif self.doit_decrypter:
            # Decrypter data avant le mapping
            # S'assurer de decrypter en ordre et une seule fois
            if self.__cipher is not None:
                if self.__paquets.get(no_paquet-1) is not None and self.__paquets.get(no_paquet) is None:
                    self.__logger.debug("Contenu crypte recu : %s" % binascii.hexlify(data[6:]))
                    # Les 4 premiers bytes ne sont pas cryptes
                    data = data[0:4] + self.__cipher.decrypt(data[4:])
                    type_message = unpack('H', data[4:6])[0]
                    self.__logger.debug("Decrypte noPaquet : %d, type paquet : %d" % (no_paquet, type_message))
            else:
                self.__logger.info("Cipher non disponible pour donnees cryptees")
                raise ExceptionCipherNonDisponible("UUID: %s, paquet %d" % (self.uuid_appareil, no_paquet))

        if type_message == TypesMessages.TYPE_PAQUET_FIN:
            paquet = PaquetFin(data)
        elif type_message == TypesMessages.TYPE_PAQUET_IV:
            paquet = PaquetIv(data)

        elif type_message == TypesMessages.MSG_TYPE_CLE_APPAREIL_1:
            paquet = PaquetCleAppareil1(data)
        elif type_message == TypesMessages.MSG_TYPE_CLE_APPAREIL_2:
            paquet = PaquetCleAppareil2(data)

        elif type_message == TypesMessages.MSG_TYPE_LECTURE_TH:
            paquet = PaquetTH(data)
        elif type_message == TypesMessages.MSG_TYPE_LECTURE_TP:
            paquet = PaquetTP(data)
        elif type_message == TypesMessages.MSG_TYPE_LECTURE_POWER:
            paquet = PaquetPower(data)
        elif type_message == TypesMessages.MSG_TYPE_LECTURE_ONEWIRE:
            paquet = PaquetOneWireTemperature(data)
        elif type_message == TypesMessages.MSG_TYPE_LECTURE_ANTENNE:
            paquet = PaquetAntenne(data)

        return paquet


class MessageIv(Paquet):
    """
    Message self-contained avec IV
    """
    
    def __init__(self, data: bytes, info_appareil: dict):
        self.info_appareil = info_appareil
        self.compute_tag = None
        self.iv = None
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        super().__init__(data)

    def _parse(self):
        super()._parse()

        cle_partagee = self.info_appareil['cle_partagee']
        
        self.iv = self.data[6:22]
        self.compute_tag = self.data[22:32]
        self.__logger.debug("Compute tag (len: %d) = %s" % (len(self.compute_tag), binascii.hexlify(self.compute_tag)))
        
        # Creer cipher pour dechiffrer
        cipher = Acorn128()
        cipher.setKey(cle_partagee[0:16])
        cipher.setIV(self.iv)
        
        # Ajouter donnees auth, pas de donnees chiffrees
        cipher.addAuthData(self.data[0:22])
        
        # Lance une exception si tag invalide
        cipher.checkTag(self.compute_tag)

    def assembler(self):
        return None, None


class MessageChiffre(Paquet):
    
    def __init__(self, data: bytes, info_appareil: dict):
        self.info_appareil = info_appareil
        self.data_dechiffre = None
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        super().__init__(data)
   
    def _parse(self):
        super()._parse()

        # Dechiffrer le contenu
        
        # Recuperer cle, iv de l'appareil
        # self.__logger.debug('Info appareil pour paquet 0 complet : %s' % str(self.info_appareil))
        cle_partagee = self.info_appareil['cle_partagee']

        taille_payload = self._get_taille_payload()
        
        position_data_chiffree = 6
        position_tag = 6 + taille_payload
        fin_tag = min(position_tag + 16, 32)  # Le tag a 16 bytes max, mais le paquet a 32 bytes max
        
        data_chiffre = self.data[position_data_chiffree:position_tag]
        self.compute_tag = self.data[position_tag:fin_tag]
        
        self.__logger.debug("Compute tag. Debut tag : %d, fin tag : %d. Recu taille %d : %s" % 
            (position_tag, fin_tag, len(self.compute_tag), binascii.hexlify(self.compute_tag))
        )

        # Creer cipher pour dechiffrer
        iv_list = [self.info_appareil['iv']]
        try:
            iv_list.insert(0, self.info_appareil['iv_candidat'])
        except KeyError:
            pass  # Pas de IV candidat
        
        data_dechiffre = None
        for iv in iv_list:
            self.__logger.debug("Tenter de dechiffrer avec iv %s" % binascii.hexlify(iv))
            try:
                data_dechiffre = MessageChiffre.dechiffrer(cle_partagee[0:16], iv, self.data[0:6], data_chiffre, self.compute_tag)
                break
            except ValueError:
                # Tester tous les IV candidats
                pass
        
        if data_dechiffre is None:
            raise ValueError("%s: Message tag invalide" % self.info_appareil['node_id'])
        else:
            self.data_dechiffre = data_dechiffre
            
            self.info_appareil['iv'] = iv
            try:
                del self.info_appareil['iv_candidat']
                self.__logger.debug("Conserver iv %s, iv_candidat supprime : %s" % (binascii.hexlify(iv), str(self.info_appareil)))
            except KeyError:
                pass  # Candidat n'existe pas

    def _get_taille_payload(self):
        """
        :return: Nombre de bytes de payload
        """
        raise NotImplementedError()

    @staticmethod
    def dechiffrer(cle_partagee, iv, auth_data, data_chiffre, compute_tag):
        # Creer cipher pour dechiffrer
        cipher = Acorn128()
        cipher.setKey(cle_partagee)
        cipher.setIV(iv)
        
        # Ajouter donnees auth
        cipher.addAuthData(auth_data)
        data_dechiffre = cipher.decrypt(data_chiffre)
        
        # Lance une exception si tag invalide
        cipher.checkTag(compute_tag)
        
        return data_dechiffre


class MessageTemperatureHumiditeAntennePower(MessageChiffre):
    
    def __init__(self, data: bytes, info_appareil: dict):
        self.info_appareil = info_appareil
        
        self.temperature = None
        self.humidite = None
        self.pct_signal = None
        self.force_emetteur = None
        self.canal = None
        self.batterie = None

        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        super().__init__(data, info_appareil)
    
    def _get_taille_payload(self):
        return 9
        
    def _parse(self):
        super()._parse()
        
        # temperature   - 2 bytes
        # humidite      - 2 bytes
        # batterie      - 2 bytes
        # pctSignal     - 1 byte
        # forceEmetteur - 1 byte
        # canal         - 1 byte

        temperature, humidite, batterie, pct_signal, force_emetteur, canal  = \
            unpack('hHHBBB', self.data_dechiffre)
            
        self.__logger.debug("Data dechiffree : temperature %s, humidite %s, pct_signal %s, force_emetteur %s, canal %s, batterie %s" % 
            (temperature, humidite, pct_signal, force_emetteur, canal, batterie)
        )

        if temperature == -32768:
            self.temperature = None
        else:
            self.temperature = float(temperature) / 10.0

        if humidite == 0xFF:
            self.humidite = None
        else:
            self.humidite = float(humidite) / 10.0

        if batterie == 0xFFFF:
            self.batterie = None
        else:
            self.batterie = batterie

        self.pct_signal = pct_signal
        self.force_emetteur = force_emetteur
        self.canal = canal

    def assembler(self):
        message = {
            'th/temperature': {
                'valeur': self.temperature,
                'type': 'temperature',
            },
            'th/humidite': {
                'valeur': self.humidite,
                'type': 'humidite',
            },
            'batterie/millivolt': {
                'valeur': self.batterie,
                'type': 'millivolt',
            },
            'antenne/signal': {
                'valeur': self.pct_signal,
                'type': 'pct',
            },
            'antenne/force': {
                'valeur': self.force_emetteur,
                'type': 'int',
            },
            'antenne/canal': {
                'valeur': self.canal,
                'type': 'int',
            }
        }
        
        # Ajouter timestamp a tous les messages
        timestamp_message = int(datetime.datetime.utcnow().timestamp())
        for lecture in message.values():
            lecture['timestamp'] = timestamp_message
        
        return message, None


class MessageTemperaturePressionAntennePower(MessageChiffre):
    
    def __init__(self, data: bytes, info_appareil: dict):
        self.info_appareil = info_appareil
        
        self.temperature = None
        self.pression = None
        self.pct_signal = None
        self.force_emetteur = None
        self.canal = None
        self.batterie = None

        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        super().__init__(data, info_appareil)
    
    def _get_taille_payload(self):
        return 9
        
    def _parse(self):
        super()._parse()
        
        # temperature   - 2 bytes
        # pression      - 2 bytes
        # batterie      - 2 bytes
        # pctSignal     - 1 byte
        # forceEmetteur - 1 byte
        # canal         - 1 byte

        temperature, pression, batterie, pct_signal, force_emetteur, canal  = \
            unpack('hHHBBB', self.data_dechiffre)
            
        self.__logger.debug("Data dechiffree : temperature %s, pression %s, pct_signal %s, force_emetteur %s, canal %s, batterie %s" % 
            (temperature, pression, pct_signal, force_emetteur, canal, batterie)
        )

        if temperature == -32768:
            self.temperature = None
        else:
            self.temperature = float(temperature) / 10.0

        if pression == 0xFF:
            self.pression = None
        else:
            self.pression = float(pression) / 100.0

        if batterie == 0xFFFF:
            self.batterie = None
        else:
            self.batterie = batterie

        self.pct_signal = pct_signal
        self.force_emetteur = force_emetteur
        self.canal = canal

    def assembler(self):
        message = {
            'th/temperature': {
                'valeur': self.temperature,
                'type': 'temperature',
            },
            'tp/pression': {
                'valeur': self.pression,
                'type': 'pression',
            },
            'batterie/millivolt': {
                'valeur': self.batterie,
                'type': 'millivolt',
            },
            'antenne/signal': {
                'valeur': self.pct_signal,
                'type': 'pct',
            },
            'antenne/force': {
                'valeur': self.force_emetteur,
                'type': 'int',
            },
            'antenne/canal': {
                'valeur': self.canal,
                'type': 'int',
            }
        }
        
        # Ajouter timestamp a tous les messages
        timestamp_message = int(datetime.datetime.utcnow().timestamp())
        for lecture in message.values():
            lecture['timestamp'] = timestamp_message
        
        return message, None


class MessageOneWire(MessageChiffre):
    
    def __init__(self, data: bytes, info_appareil: dict):
        self.info_appareil = info_appareil
        
        self.adresse_onewire = None
        self.data_onewire = None

        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        super().__init__(data, info_appareil)
    
    def _get_taille_payload(self):
        return 20
        
    def _parse(self):
        super()._parse()
        
        # adresse - 8 bytes
        # data 1W - 12 bytes

        adresse_onewire, data_onewire = PaquetOneWire.decoder_onewire(self.data_dechiffre)
        self.adresse_onewire = adresse_onewire
        self.data_onewire = data_onewire

class MessageOnewireTemperature(MessageOneWire):
    
    def __init__(self, data: bytes, info_appareil: dict):
        self.info_appareil = info_appareil
        
        self.temperature = None

        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        super().__init__(data, info_appareil)
    
    def _parse(self):
        super()._parse()
        self.temperature = PaquetOneWireTemperature.decoder_temperature(self.data_onewire)

    def assembler(self):
        label = 'onewire/' + binascii.hexlify(self.adresse_onewire).decode('utf-8')
        message = {
            label: {
                'valeur': self.temperature,
                'type': 'temperature'
            }
        }

        # Ajouter timestamp a tous les messages
        timestamp_message = int(datetime.datetime.utcnow().timestamp())
        for lecture in message.values():
            lecture['timestamp'] = timestamp_message
        
        return message, None


class PaquetTransmission:

    def __init__(self, type_message: int):
        self.type_message = type_message

    def encoder(self):
        """
        Genere le message en bytes. Override dans sous-classe pour 
        ajouter le contenu apres le prefixe.
        """
        prefixe = pack('=BHB', VERSION_PROTOCOLE, self.type_message, self.node_id)
        
        return prefixe


class PaquetBeaconDHCP(PaquetTransmission):
    """
    Paquet transmis a intervalle reguliers sur une adresse de broadcast
    Contient l'information du serveur (adresse pipe, IDMG)
    """

    def __init__(self, adresse_serveur: bytes):
        super().__init__(TypesMessages.TYPE_BEACON_DHCP)
        self.adresse_serveur = adresse_serveur

    def encoder(self):
        message = pack('=BH', VERSION_PROTOCOLE, TypesMessages.TYPE_BEACON_DHCP) + self.adresse_serveur  # Ajouter idmg plus tard
        message = message + bytes(32-len(message))  # Padding a 32
        return message


class PaquetACKTransmission(PaquetTransmission):
    """
    Paquet utilise pour confirmer la reception correcte (ou non)
    d'une transmission.
    :param node_id: Id du noeud
    :param tag: Compute tag (hash) recu, permet de confirmer le message de maniere unique
    :param commande: Commande transmise en piggy-back.
    """

    def __init__(self, node_id: int, tag: bytes, commande: bytes = None):
        super().__init__(TypesMessages.MSG_TYPE_REPONSE_ACK)
        self.node_id = node_id
        self.tag = tag
        self.commande = commande

    def encoder(self):
        message = super().encoder()
        if self.tag is not None:
            message = message + self.tag
        if self.commande is not None:
            message = message + self.commande
        message = message + bytes(32-len(message))  # Padding a 32
        return message


class PaquetReponseDHCP(PaquetTransmission):

    def __init__(self, reseau: bytes, node_id: int, node_uuid: bytes):
        super().__init__(TypesMessages.TYPE_REPONSE_DHCP)
        self.__reseau = reseau
        self.node_id = node_id
        self.node_uuid = node_uuid

    def encoder(self):
        prefixe = super().encoder()
        message = prefixe + self.__reseau
        message = message + bytes(32-len(message))  # Padding a 32
        return message


class PaquetReponseCleServeur1(PaquetTransmission):

    def __init__(self, node_id, clePubliqueServeur):
        super().__init__(TypesMessages.MSG_TYPE_CLE_SERVEUR_1)
        self.__clePubliqueServeur = clePubliqueServeur[0:28]
        self.node_id = node_id

    def encoder(self):
        prefixe = super().encoder()
        message = prefixe + self.__clePubliqueServeur
        
        return message


class PaquetReponseCleServeur2(PaquetTransmission):

    def __init__(self, node_id, clePubliqueServeur):
        super().__init__(TypesMessages.MSG_TYPE_CLE_SERVEUR_2)
        self.__clePubliqueServeur = clePubliqueServeur[28:32]
        self.__crc32 = self.__calculer_crc32_cle(clePubliqueServeur)
        self.node_id = node_id

    def __calculer_crc32_cle(self, clePubliqueServeur):
        # Valider la cle avec le CRC32
        # calcul_crc32 = crc32(self.__clePubliqueServeur) & 0xffffffff
        calcul_crc32 = crc32(clePubliqueServeur)
        return pack('I', calcul_crc32)

    def encoder(self):
        prefixe = super().encoder()
        message = prefixe + self.__clePubliqueServeur + self.__crc32
        padding = [0] * (32-len(message))
        message = message + bytes(padding)  # Padding a 32

        return message

class ExceptionCipherNonDisponible(Exception):
    
    pass
