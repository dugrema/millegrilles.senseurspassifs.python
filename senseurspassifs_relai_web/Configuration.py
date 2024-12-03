import asyncio
import argparse
import logging
import os

from typing import Optional

from millegrilles_messages.bus.BusConfiguration import MilleGrillesBusConfiguration
from senseurspassifs_relai_web import Constantes as RelayConstants

LOGGING_NAMES = [__name__, 'millegrilles_messages', 'senseurspassifs_relai_web']


def __adjust_logging(args: argparse.Namespace):
    logging_format = '%(levelname)s:%(name)s:%(message)s'

    if args.logtime:
        logging_format = f'%(asctime)s - {logging_format}'

    logging.basicConfig(format=logging_format)

    if args.verbose is True:
        asyncio.get_event_loop().set_debug(True)  # Asyncio warnings
        for log in LOGGING_NAMES:
            logging.getLogger(log).setLevel(logging.DEBUG)
    else:
        for log in LOGGING_NAMES:
            logging.getLogger(log).setLevel(logging.INFO)


def _parse_command_line():
    parser = argparse.ArgumentParser(description="Instance manager for MilleGrilles")
    parser.add_argument(
        '--verbose', action="store_true", required=False,
        help="More logging"
    )
    parser.add_argument(
        '--logtime', action="store_true", required=False,
        help="Add time to logging"
    )

    args = parser.parse_args()
    __adjust_logging(args)
    return args


class SenseurspassifsRelaiWebConfiguration(MilleGrillesBusConfiguration):

    def __init__(self):
        super().__init__()
        self.web_port = 443
        self.websocket_port = 444

    def parse_config(self, configuration: Optional[dict] = None):
        """
        Conserver l'information de configuration
        :param configuration:
        :return:
        """
        super().parse_config()

        web_port = os.environ.get(RelayConstants.ENV_WEB_PORT)
        if web_port:
            self.web_port = int(web_port)

        websocket_port = os.environ.get(RelayConstants.ENV_WEBSOCKET_PORT)
        if websocket_port:
            self.websocket_port = int(websocket_port)

    @staticmethod
    def load():
        # Override
        config = SenseurspassifsRelaiWebConfiguration()
        _parse_command_line()
        config.parse_config()
        config.reload()
        return config
