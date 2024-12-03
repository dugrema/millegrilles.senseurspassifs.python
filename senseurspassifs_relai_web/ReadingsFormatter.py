import logging

from typing import Optional

from millegrilles_messages.messages import Constantes
from senseurspassifs_relai_web import Constantes as SenseurspassifsWebRelayConstants
from senseurspassifs_relai_web.Context import SenseurspassifsRelaiWebContext
from senseurspassifs_relai_web.MessagesHandler import CorrelationAppareil


class ReadingsSender:

    def __init__(self, context: SenseurspassifsRelaiWebContext):
        self.__logger = logging.getLogger(__name__+'.'+self.__class__.__name__)
        self.__context = context

    async def send_readings(self, readings: dict):
        await self.send_readings_correlation(readings, None)

    async def send_readings_correlation(self, readings: dict, correlation_appareil: Optional[CorrelationAppareil]):
        producer = await self.__context.get_producer()

        if correlation_appareil is not None:
            lecture_relayee = readings.copy()
            lecture_relayee['user_id'] = correlation_appareil.user_id
            lecture_relayee['uuid_appareil'] = correlation_appareil.uuid_appareil
            message_enveloppe = {
                'instance_id': self.__context.instance_id,
                'lecture_relayee': lecture_relayee,
            }
        else:
            message_enveloppe = {
                'instance_id': self.__context.instance_id,
                'lecture': readings,
            }

        await producer.event(
            message_enveloppe,
            SenseurspassifsWebRelayConstants.ROLE_SENSEURSPASSIFS_RELAI,
            SenseurspassifsWebRelayConstants.EVENEMENT_DOMAINE_LECTURE,
            exchange=Constantes.SECURITE_PRIVE
        )
