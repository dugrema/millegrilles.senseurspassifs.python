import argparse
import os

from typing import Optional

from senseurspassifs_relai_web import Constantes

CONST_WEB_PARAMS = [
    Constantes.ENV_WEB_PORT,
]


class ConfigurationWeb:

    def __init__(self):
        self.port = '4443'

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
