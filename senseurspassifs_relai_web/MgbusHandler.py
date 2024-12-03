import logging

from asyncio import TaskGroup
from typing import Optional, Callable, Coroutine, Any

from cryptography.x509 import ExtensionNotFound

from millegrilles_messages.bus.PikaChannel import MilleGrillesPikaChannel
from millegrilles_messages.bus.PikaQueue import MilleGrillesPikaQueueConsumer, RoutingKey
from millegrilles_messages.messages import Constantes
from millegrilles_messages.bus.BusContext import ForceTerminateExecution, MilleGrillesBusContext
from millegrilles_messages.messages.MessagesModule import MessageWrapper
from senseurspassifs_relai_web.SenseurspassifsRelaiWebManager import SenseurspassifsRelaiWebManager


class MgbusHandler:

    def __init__(self, manager: SenseurspassifsRelaiWebManager):
        super().__init__()
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__manager = manager
        self.__task_group: Optional[TaskGroup] = None

    async def run(self):
        self.__logger.debug("MgbusHandler thread started")
        try:
            async with TaskGroup() as group:
                self.__task_group = group
                group.create_task(self.__stop_thread())

                # Connect
                await self.register()
        except* Exception:  # Stop on any thread exception
            if self.__manager.context.stopping is False:
                self.__logger.exception("GenerateurCertificatsHandler Unhandled error, closing")
                self.__manager.context.stop()
                raise ForceTerminateExecution()
        self.__task_group = None
        self.__logger.debug("MgbusHandler thread done")

    async def __stop_thread(self):
        await self.__manager.context.wait()

    async def register(self):
        self.__logger.info("Register with the MQ Bus")

        context = self.__manager.context

        channel_command = create_command_q_channel(context, self.on_command_message)
        await self.__manager.context.bus_connector.add_channel(channel_command)

        channel_events = create_event_q_channel(context, self.on_event_message)
        await self.__manager.context.bus_connector.add_channel(channel_events)

        # Start mgbus connector thread
        self.__task_group.create_task(self.__manager.context.bus_connector.run())

    async def unregister(self):
        self.__logger.info("Unregister from the MQ Bus")
        # await self.__manager.context.bus_connector.()
        raise NotImplementedError('Stop mgbus thread / unregister all channels')

    async def on_command_message(self, message: MessageWrapper):
        action = message.routage['action']

        if action in ['challengeAppareil', 'commandeAppareil']:
            return await self.__manager.handle_message(message)

        self.__logger.info("on_exclusive_message Ignoring unknown action %s" % action)

    async def on_event_message(self, message: MessageWrapper):
        # Authorization check
        enveloppe = message.certificat
        try:
            domaines = enveloppe.get_domaines
        except ExtensionNotFound:
            domaines = list()
        try:
            exchanges = enveloppe.get_exchanges
        except ExtensionNotFound:
            exchanges = list()

        action = message.routage['action']

        if Constantes.SECURITE_PROTEGE in exchanges:
            if 'SenseursPassifs' in domaines:
                if action in ['evenementMajDisplays', 'evenementMajProgrammes', 'lectureConfirmee', 'majConfigurationAppareil']:
                    return await self.__manager.handle_message(message)
            elif 'CoreTopologie' in domaines:
                if action == 'fichePublique':
                    return await self.__manager.handle_message(message)

        self.__logger.info("on_exclusive_message Ignoring unknown action %s" % action)

def create_command_q_channel(context: MilleGrillesBusContext,
                             on_message: Callable[[MessageWrapper], Coroutine[Any, Any, None]]) -> MilleGrillesPikaChannel:
    q_channel = MilleGrillesPikaChannel(context, prefetch_count=20)
    q_instance = MilleGrillesPikaQueueConsumer(context, on_message, None, exclusive=True,
                                                arguments={'x-message-ttl': 60_000})

    instance_id = context.instance_id
    q_instance.add_routing_key(RoutingKey(Constantes.SECURITE_PRIVE, f'commande.senseurspassifs_relai.{instance_id}.challengeAppareil'))
    q_instance.add_routing_key(RoutingKey(Constantes.SECURITE_PRIVE, f'commande.senseurspassifs_relai.{instance_id}.commandeAppareil'))

    q_channel.add_queue(q_instance)

    return q_channel

def create_event_q_channel(context: MilleGrillesBusContext,
                          on_message: Callable[[MessageWrapper], Coroutine[Any, Any, None]]) -> MilleGrillesPikaChannel:
    q_channel = MilleGrillesPikaChannel(context, prefetch_count=20)
    q_instance = MilleGrillesPikaQueueConsumer(context, on_message, None, exclusive=True,
                                                arguments={'x-message-ttl': 30_000})

    q_instance.add_routing_key(RoutingKey(Constantes.SECURITE_PRIVE, 'evenement.SenseursPassifs.*.evenementMajDisplays'))
    q_instance.add_routing_key(RoutingKey(Constantes.SECURITE_PRIVE, 'evenement.SenseursPassifs.*.evenementMajProgrammes'))
    q_instance.add_routing_key(RoutingKey(Constantes.SECURITE_PRIVE, 'evenement.SenseursPassifs.*.lectureConfirmee'))
    q_instance.add_routing_key(RoutingKey(Constantes.SECURITE_PRIVE, 'evenement.SenseursPassifs.*.majConfigurationAppareil'))
    q_instance.add_routing_key(RoutingKey(Constantes.SECURITE_PUBLIC, 'evenement.CoreTopologie.fichePublique'))

    q_channel.add_queue(q_instance)

    return q_channel

# class ModuleSenseurWebServer:
#     """ Wrapper de module pour le web server """
#
#     def __init__(self, etat_senseurspassifs: EtatSenseursPassifs):
#         self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
#         self.__web_server = WebServer(etat_senseurspassifs)
#         self.__websocket_server = ServeurWebSocket(etat_senseurspassifs)
#
#     def setup(self, configuration: Optional[dict] = None):
#         self.__web_server.setup(configuration)
#         self.__websocket_server.setup(configuration)
#
#     def routing_keys(self) -> list:
#         instance_id = self.__web_server.etat_senseurspassifs.instance_id
#         return [
#             'commande.senseurspassifs_relai.%s.challengeAppareil' % instance_id,
#             'commande.senseurspassifs_relai.%s.commandeAppareil' % instance_id,
#             'evenement.SenseursPassifs.*.evenementMajDisplays',
#             'evenement.SenseursPassifs.*.evenementMajProgrammes',
#             'evenement.SenseursPassifs.*.lectureConfirmee',
#             'evenement.SenseursPassifs.*.majConfigurationAppareil',
#             (Constantes.SECURITE_PUBLIC, 'evenement.CoreTopologie.fichePublique'),
#         ]
#
#     async def recevoir_message_mq(self, message):
#         """ Traiter messages recus via routing keys """
#         self.__logger.debug("ModuleSenseurWebServer Traiter message %s" % message)
#         try:
#             await self.__web_server.message_handler.recevoir_message_mq(message)
#             await self.__websocket_server.message_handler.recevoir_message_mq(message)
#         except Exception as e:
#             self.__logger.exception("Erreur traitement message %s : %s" % (message.routing_key, e))
#
#     async def entretien(self):
#         await self.__web_server.entretien()
#
#     async def run(self, stop_event: Optional[Event] = None):
#         await asyncio.gather(
#             self.__web_server.run(stop_event),
#             self.__websocket_server.run(stop_event)
#         )
