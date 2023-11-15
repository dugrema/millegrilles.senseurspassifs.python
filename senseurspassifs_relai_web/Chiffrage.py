import base64
import binascii
import json
import secrets

from typing import Union, Optional

from base64 import b64encode
from Crypto.Cipher import ChaCha20_Poly1305
from Crypto.Random import get_random_bytes

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import serialization


def preparer_cle_chiffrage(cle_peer: str) -> (bytes, str):
    cle_peer = binascii.unhexlify(cle_peer.encode('utf-8'))

    x25519_public_key = X25519PublicKey.from_public_bytes(cle_peer)
    cle_privee = X25519PrivateKey.generate()
    cle_handshake = cle_privee.exchange(x25519_public_key)
    # self.__cle_chiffrage = cle_handshake
    # self.__logger.error(" !!! CLE SECRETE !!! : %s" % binascii.hexlify(self.__cle_chiffrage))

    cle_peer_bytes = cle_privee.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    return cle_handshake, binascii.hexlify(cle_peer_bytes).decode('utf-8')


def chiffrer_message_chacha20poly1305(key: bytes, plaintext: Union[str, bytes]):

    if isinstance(plaintext, str):
        plaintext = plaintext.encode('utf-8')

    #nonce = secrets.token_bytes(12)
    cipher = ChaCha20_Poly1305.new(key=key)
    #cipher.update(nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)

    print('Ciphertext binascii : %s' % binascii.hexlify(ciphertext))
    print('Nonce binascii : %s' % binascii.hexlify(cipher.nonce))

    return {
        'ciphertext': base64.b64encode(ciphertext).decode('utf-8'),
        'nonce': base64.b64encode(cipher.nonce).decode('utf-8'),
        'tag': base64.b64encode(tag).decode('utf-8'),
    }


def dechiffrer_message_chacha20poly1305(key: bytes, nonce: Union[str, bytes], tag: Union[str, bytes], ciphertext: Union[str, bytes]):

    if isinstance(nonce, str):
        nonce = base64.b64decode(nonce)

    if isinstance(tag, str):
        tag = base64.b64decode(tag)

    if isinstance(ciphertext, str):
        ciphertext = base64.b64decode(ciphertext)

    cipher = ChaCha20_Poly1305.new(key=key, nonce=nonce)
    # cipher.update(nonce)
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)

    return plaintext


def attacher_reponse_chiffree(correlation=None, reponse: Optional[dict] = None, enveloppe=None):
    if correlation is None or reponse is None:
        return

    if correlation.chiffrage_disponible:
        cle_dechiffrage = correlation.cle_dechiffrage

        if enveloppe is not None:
            info_enveloppe = None  # todo
        else:
            info_enveloppe = None

        message_chiffre = json.dumps({'contenu': reponse['contenu'], 'enveloppe': info_enveloppe})

        # Chiffrer le contenu
        message_chiffre = chiffrer_message_chacha20poly1305(cle_dechiffrage, message_chiffre)
        try:
            attachements = reponse['attachements']
        except KeyError:
            attachements = dict()
            reponse['attachements'] = attachements

        attachements['relai_chiffre'] = message_chiffre
