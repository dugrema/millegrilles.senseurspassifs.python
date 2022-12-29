import argparse
import os

from typing import Optional

from senseurspassifs_relai_web import Constantes

CONST_WEB_PARAMS = [
    Constantes.ENV_WEB_PORT,
    Constantes.ENV_WEBSOCKET_PORT,
    Constantes.PARAM_CERT_PATH,
    Constantes.PARAM_KEY_PATH,
    Constantes.PARAM_CA_PATH,
]


class ConfigurationWeb:

    def __init__(self):
        self.port = '443'
        self.websocket_port = '444'
        self.cert_pem_path = '/run/secrets/pki.senseurspassifs_relai_web.cert'
        self.key_pem_path = '/run/secrets/pki.senseurspassifs_relai_web.key'
        self.ca_pem_path = '/run/secrets/pki.millegrille'

    def get_env(self) -> dict:
        """
        Extrait l'information pertinente pour pika de os.environ
        :return: Configuration dict
        """
        config = dict()
        for opt_param in CONST_WEB_PARAMS:
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

        self.port = int(dict_params.get(Constantes.ENV_WEB_PORT) or self.port)
        self.websocket_port = int(dict_params.get(Constantes.ENV_WEBSOCKET_PORT) or self.websocket_port)
        self.cert_pem_path = dict_params.get(Constantes.PARAM_CERT_PATH) or self.cert_pem_path
        self.key_pem_path = dict_params.get(Constantes.PARAM_KEY_PATH) or self.key_pem_path
        self.ca_pem_path = dict_params.get(Constantes.PARAM_CA_PATH) or self.ca_pem_path
