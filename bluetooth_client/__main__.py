import asyncio
import json
import logging

from bleak import BleakScanner, BleakClient, BleakError

from bluetooth_client.bluetooth_services import CONST_SERVICES

LOGGER = logging.getLogger('__main__')


async def main():
    devices = await scan()

    for device in devices:
        try:
            await get_etat(device)
        except (asyncio.TimeoutError, BleakError):
            LOGGER.exception("Timeout/Erreur sur device %s", device)


async def scan():
    services_metadata = CONST_SERVICES['services']
    commandes_uuid = services_metadata['commandes']['uuid']
    etat_uuid = services_metadata['etat']['uuid']
    service_uuids = [commandes_uuid, etat_uuid]

    devices = await BleakScanner.discover(service_uuids=service_uuids)

    for d in devices:
        LOGGER.debug("Device %s", d)

    return devices


async def get_etat(device):
    client = BleakClient(device)
    try:
        await client.connect()
        LOGGER.info("Connecte a %s", device)
    except Exception:
        LOGGER.exception("Erreur connexion BLE a %s", device)
        return

    services = await client.get_services()
    LOGGER.debug("Services %s", device)
    for service in services:
        LOGGER.debug("Service %s", service)


if __name__ == '__main__':
    logging.basicConfig()
    logging.getLogger('__main__').setLevel(logging.DEBUG)
    asyncio.run(main())

