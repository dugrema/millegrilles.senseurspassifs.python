import binascii

from senseurspassifs_relai_web.Chiffrage import chiffrer_message_chacha20poly1305, dechiffrer_message_chacha20poly1305

KEY_1 = b"01234567890123456789012345678901"
NONCE_1 = b"0123456789ad"
MESSAGE_1 = b"ABCD12345678EFGHABRAdada"
TAG_1 = binascii.unhexlify('05444836ffefd952ac2bba737f30a72c')
CIPHERTEXT_1 = binascii.unhexlify('5a35ac89771b09a632e25345cf8cd266c31541e3bfb2a57a')


def test_chiffrer():
    print("----\nChiffrer et dechiffrer")
    resultat = chiffrer_message_chacha20poly1305(KEY_1, MESSAGE_1)
    print("Resultat chiffrage : %s" % resultat)

    plaintext = dechiffrer_message_chacha20poly1305(KEY_1, resultat['nonce'], resultat['tag'], resultat['ciphertext'])
    print("Plaintext dechiffre : %s" % plaintext)


def test_dechiffrer():
    print("----\nDechiffrer valeurs externes")
    plaintext = dechiffrer_message_chacha20poly1305(KEY_1, NONCE_1, TAG_1, CIPHERTEXT_1)
    print("Plaintext dechiffre : %s" % plaintext)


def main():
    test_chiffrer()
    test_dechiffrer()


if __name__ == '__main__':
    main()