import binascii
import json
import logging
import multibase

from cryptography.hazmat.primitives import hashes, asymmetric
from typing import Union, Optional

from millegrilles_messages.messages.EnveloppeCertificat import EnveloppeCertificat
from millegrilles_messages.messages.ValidateurMessage import ValidateurMessage, preparer_message


logger = logging.getLogger(__name__)


class ValidateurMessageControleur(ValidateurMessage):

    def __init__(self, validateur_certificats):
        super().__init__(validateur_certificats)

    async def verifier(self, message: Union[bytes, str, dict], utiliser_date_message=False,
                       utiliser_idmg_message=False, verifier_certificat=True) -> Optional[EnveloppeCertificat]:
        return await super().verifier(message, utiliser_date_message, utiliser_idmg_message, verifier_certificat)


async def verifier_signature_cle_publique(message: dict, cle_publique: str, signature: str):
    # Le certificat est valide. Valider la signature du message.
    signature_enveloppe = multibase.decode(signature.encode('utf-8'))
    version_signature = signature_enveloppe[0]
    signature_bytes = signature_enveloppe[1:]

    if isinstance(signature_bytes, str):
        signature_bytes = signature_bytes.encode('utf-8')

    message_bytes = json.dumps(
        message,
        ensure_ascii=False,   # S'assurer de supporter tous le range UTF-8
        sort_keys=True,
        separators=(',', ':')
    ).encode('utf-8')

    if isinstance(cle_publique, str):
        cle_publique = bytes(multibase.decode(cle_publique))

    if len(cle_publique) != 32:
        raise ValueError("Taille de cle publique incorrecte")

    cle_publique = asymmetric.ed25519.Ed25519PublicKey.from_public_bytes(cle_publique)

    if version_signature == 2:
        hash = hashes.Hash(hashes.BLAKE2b(64))
        logger.debug("Message a hacher\n%s" % message_bytes)
        hash.update(message_bytes)
        hash_value = hash.finalize()
        logger.debug("Message hash value : %s" % binascii.hexlify(hash_value))
        cle_publique.verify(signature_bytes, hash_value)
    else:
        raise ValueError("Version de signature non supportee : %s" % version_signature)

    # Signature OK, aucune exception n'a ete lancee
