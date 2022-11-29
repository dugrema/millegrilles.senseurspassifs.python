import os

from typing import Optional

from millegrilles_messages.messages import Constantes
from millegrilles_senseurspassifs import Constantes as ConstantesSenseursPassifs

CONST_SENSEURSPASSIFS_PARAMS = [
    Constantes.ENV_CERT_PEM,
    Constantes.ENV_KEY_PEM,
    Constantes.ENV_CA_PEM,
    Constantes.ENV_MQ_HOSTNAME,
    Constantes.ENV_MQ_PORT,
]


class ConfigurationSenseursPassifs:

    def __init__(self):
        self.config_path = '/var/opt/millegrilles/configuration/config.json'
        self.ca_pem_path = '/var/opt/millegrilles/configuration/pki.millegrille.cert'
        self.cert_pem_path = '/var/opt/millegrilles/secrets_partages/pki.certificat_senseurspassifs_hub.cert'
        self.key_pem_path = '/var/opt/millegrilles/secrets_partages/pki.certificat_senseurspassifs_hub.cle'

        self.senseurspassifs_path = '/var/opt/millegrilles/senseurspassifs'
        self.lecture_log_directory = '/var/opt/millegrilles/senseurspassifs/log'

        self.mq_host: Optional[str] = None
        self.mq_port: Optional[int] = None

    def get_env(self) -> dict:
        """
        Extrait l'information pertinente pour pika de os.environ
        :return: Configuration dict
        """
        config = dict()
        for opt_param in CONST_SENSEURSPASSIFS_PARAMS:
            value = os.environ.get(opt_param)
            if value is not None:
                config[opt_param] = value

        return config

    def parse_config(self, configuration: Optional[dict] = None):
        """
        Conserver l'information de configuration
        :param configuration:
        :return:
        """
        dict_params = self.get_env()
        if configuration is not None:
            dict_params.update(configuration)

        self.config_path = dict_params.get(ConstantesSenseursPassifs.PARAM_CONFIG_INSTANCE) or self.config_path
        self.ca_pem_path = dict_params.get(Constantes.ENV_CA_PEM) or self.ca_pem_path
        self.cert_pem_path = dict_params.get(Constantes.ENV_CERT_PEM) or self.cert_pem_path
        self.key_pem_path = dict_params.get(Constantes.ENV_KEY_PEM) or self.key_pem_path
        self.mq_host = dict_params.get(Constantes.ENV_MQ_HOSTNAME) or self.mq_host
        try:
            self.mq_port = int(dict_params.get(Constantes.ENV_MQ_PORT) or self.mq_port)
        except TypeError:
            self.mq_port = None
