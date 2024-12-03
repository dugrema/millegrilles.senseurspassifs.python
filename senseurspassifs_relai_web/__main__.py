import asyncio
import logging
import sys

from asyncio import TaskGroup
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Awaitable

from millegrilles_messages.bus.BusContext import ForceTerminateExecution, StopListener
from millegrilles_messages.bus.BusExceptions import ConfigurationFileError
from millegrilles_messages.bus.PikaConnector import MilleGrillesPikaConnector
from senseurspassifs_relai_web.Configuration import SenseurspassifsRelaiWebConfiguration
from senseurspassifs_relai_web.Context import SenseurspassifsRelaiWebContext
from senseurspassifs_relai_web.MessagesHandler import AppareilMessageHandler
from senseurspassifs_relai_web.MgbusHandler import MgbusHandler
from senseurspassifs_relai_web.ReadingsFormatter import ReadingsSender
from senseurspassifs_relai_web.SenseurspassifsRelaiWebManager import SenseurspassifsRelaiWebManager
from senseurspassifs_relai_web.WebServer import WebServer, ServeurWebSocket

LOGGER = logging.getLogger(__name__)


async def force_terminate_task_group():
    """Used to force termination of a task group."""
    raise ForceTerminateExecution()


async def main():
    config = SenseurspassifsRelaiWebConfiguration.load()
    try:
        context = SenseurspassifsRelaiWebContext(config)
    except ConfigurationFileError as e:
        LOGGER.error("Error loading configuration files %s, quitting" % str(e))
        sys.exit(1)  # Quit

    LOGGER.setLevel(logging.INFO)
    LOGGER.info("Starting")

    # Wire classes together, gets awaitables to run
    try:
        coros = await wiring(context)
    except PermissionError as e:
        LOGGER.error("Permission denied on loading configuration and preparing folders : %s" % str(e))
        sys.exit(2)  # Quit

    try:
        # Use taskgroup to run all threads
        async with TaskGroup() as group:
            # Create a listener that fires a task to cancel all other tasks
            async def stop_group():
                group.create_task(force_terminate_task_group())

            stop_listener = StopListener(stop_group)
            context.register_stop_listener(stop_listener)

            for coro in coros:
                group.create_task(coro)

        return  # All done, quitting with no errors
    except* (ForceTerminateExecution, asyncio.CancelledError):
        # Result of the termination task
        LOGGER.error("__main__ Force termination exception")
        context.stop()

    sys.exit(3)


async def wiring(context: SenseurspassifsRelaiWebContext) -> list[Awaitable]:
    # Some executor threads get used to handle threading.Event triggers for the duration of the execution.
    # Ensure there are enough.
    loop = asyncio.get_event_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=6))

    # Handlers (services)
    bus_connector = MilleGrillesPikaConnector(context)
    context.bus_connector = bus_connector
    device_message_handler = AppareilMessageHandler(context)
    readings_sender = ReadingsSender(context)

    # Facade
    manager = SenseurspassifsRelaiWebManager(context, device_message_handler, readings_sender)

    # Access modules
    bus_handler = MgbusHandler(manager)
    web_server = WebServer(manager)
    websocket_server = ServeurWebSocket(manager)

    # Setup / injecting dependencies
    await web_server.setup()

    # Create tasks
    coros = [
        context.run(),
        manager.run(),
        bus_handler.run(),
        web_server.run(),
        websocket_server.run(),
    ]

    return coros


if __name__ == '__main__':
    asyncio.run(main())
    LOGGER.info("Stopped")
