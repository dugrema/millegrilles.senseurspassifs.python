# SenseursPassifs

## Application relai web pour SenseursPassifs

module : senseurspassifs_relai_web

Variables d'environnement
<pre>
CA_PEM=/var/opt/millegrilles/configuration/pki.millegrille.cert
CERT_PEM=/var/opt/millegrilles/secrets/pki.senseurspassifs_relai.cert
KEY_PEM=/var/opt/millegrilles/secrets/pki.senseurspassifs_relai.cle
REDIS_HOSTNAME=localhost
REDIS_PASSWORD_PATH=/var/opt/millegrilles/secrets/passwd.redis.txt
WEB_PORT=4443
WEBSOCKET_PORT=4444
</pre>

Utiliser l'application web senseurspassifs pour generer un fichier de configuration json.

Exemple : 
{
  "idmg": "zZgJ8CG9YKqpYg7V3Fm3k9DHzxqytR4hbA58YxTLr7QrpB22DiQgebsx",
  "user_id": "z2i3Xjx9ovNcu1reixSkeyWqSCS98pMFJtfwBo8iEHa8RUSpjjf"
}

Installer le contenu sous : /var/opt/millegrilles/configuration/senseurspassifs_relai.json

Installer application senseurspassifs_relai avec Coupdoeil.

cd /var/opt/millegrilles/secrets_partages
cp -l ../secrets/pki.certificat_senseurspassifs_relai.c* .

