import asyncio
import logging

from asyncio import TaskGroup

from typing import Optional

from millegrilles_messages.bus.BusContext import MilleGrillesBusContext, ForceTerminateExecution
from millegrilles_messages.bus.PikaConnector import MilleGrillesPikaConnector
from millegrilles_messages.bus.PikaMessageProducer import MilleGrillesPikaMessageProducer
from senseurspassifs_relai_web.Configuration import SenseurspassifsRelaiWebConfiguration

LOGGER = logging.getLogger(__name__)


class SenseurspassifsRelaiWebContext(MilleGrillesBusContext):

    CONST_RUNLEVEL_INIT = 0  # Nothing finished loading yet
    CONST_RUNLEVEL_INSTALLING = 1  # No configuration (idmg, securite), waiting for admin
    CONST_RUNLEVEL_EXPIRED = 2  # Instance certificate is expired, auto-renewal not possible
    CONST_RUNLEVEL_LOCAL = 3  # Preparing what can be done locally (e.g. certificates on 3.protege) before going to NORMAL
    CONST_RUNLEVEL_NORMAL = 4  # Everything is ok, do checkup and then run until stopped

    def __init__(self, configuration: SenseurspassifsRelaiWebConfiguration):
        super().__init__(configuration)
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__bus_connector: Optional[MilleGrillesPikaConnector] = None
        self.__fiche_publique: Optional[dict] = None
        self.__shutting_down = asyncio.Event()
        self.__loop = asyncio.get_event_loop()

    def stop(self):
        """
        Override stop, allows trying to send a all devices disconnected message to server before shutting down.
        :return:
        """
        self.__loop.call_soon_threadsafe(self.__shutting_down.set)

    @property
    def shutting_down(self):
        return self.__shutting_down

    def do_stop(self):
        """
        Continue stopping the application
        :return:
        """
        super().stop()

    @property
    def configuration(self) -> SenseurspassifsRelaiWebConfiguration:
        return super().configuration

    @property
    def fiche_publique(self) -> Optional[dict]:
        return self.__fiche_publique

    @fiche_publique.setter
    def fiche_publique(self, value: dict):
        self.__fiche_publique = value

    async def run(self):
        self.__logger.debug("InstanceContext thread started")
        try:
            async with TaskGroup() as group:
                group.create_task(super().run())
                group.create_task(self.__stop_thread())
        except *Exception:  # Stop on any thread exception
            self.__logger.exception("InstanceContext Error")
            if self.stopping is False:
                self.__logger.exception("Context Unhandled error, closing")
                self.stop()
                await asyncio.sleep(1)
                raise ForceTerminateExecution()
        self.__logger.debug("InstanceContext thread done")

    async def __stop_thread(self):
        await self.wait()
        raise ForceTerminateExecution()  # Kick out the __presence_thread thread if stuck on get_producer

    @property
    def bus_connector(self) -> MilleGrillesPikaConnector:
        if self.__bus_connector is None:
            raise Exception('not initialized')
        return self.__bus_connector

    @bus_connector.setter
    def bus_connector(self, value: MilleGrillesPikaConnector):
        self.__bus_connector = value

    async def get_producer(self) -> MilleGrillesPikaMessageProducer:
        return await self.__bus_connector.get_producer()
