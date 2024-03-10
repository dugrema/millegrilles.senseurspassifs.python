import asyncio
import json
import logging
import struct
import ipaddress

from bleak import BleakScanner, BleakClient, BleakError, BleakGATTServiceCollection

from bluetooth_client.bluetooth_services import CONST_SERVICES

LOGGER = logging.getLogger('__main__')


async def main():
    devices = await scan()

    for device in devices:
        try:
            await parse_device(device)
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


async def parse_device(device):
    meta_services = CONST_SERVICES['services']
    async with BleakClient(device) as client:
        LOGGER.info("Connecte a %s", device)

        services = client.services
        for gatt_service in services:
            LOGGER.debug("Service %s", gatt_service)
            try:
                if gatt_service.uuid == meta_services['etat']['uuid']:
                    await afficher_etat(client, gatt_service)
            except BleakError:
                LOGGER.exception("Device retire %s", device)


async def afficher_etat(client, gatt_service: BleakGATTServiceCollection):
    uuid_characteristics = CONST_SERVICES['services']['etat']['characteristics']
    for characteristic in gatt_service.characteristics:
        # LOGGER.debug("Characteristic %s", characteristic)
        if characteristic.uuid == uuid_characteristics['getUserId']:
            await get_user_id(client, characteristic)
        elif characteristic.uuid == uuid_characteristics['getIdmg']:
            await get_idmg(client, characteristic)
        elif characteristic.uuid == uuid_characteristics['getWifi']:
            await get_wifi(client, characteristic)
        else:
            LOGGER.warning("Characteristic non geree %s", characteristic.uuid)


async def get_idmg(client, characteristic):
    resultat = await client.read_gatt_char(characteristic)
    resultat = resultat.decode('utf-8')
    LOGGER.debug("IDMG : %s" % resultat)
    return resultat


async def get_user_id(client, characteristic):
    resultat = await client.read_gatt_char(characteristic)
    resultat = resultat.decode('utf-8')
    LOGGER.debug("user_id : %s" % resultat)
    return resultat


async def get_wifi(client, characteristic):
    resultat = await client.read_gatt_char(characteristic)

    #     const connected = value.getUint8(0) === 1,
    #           status = value.getUint8(1),
    #           channel = value.getUint8(2)
    #     const adressesSlice = value.buffer.slice(3, 19)
    #     const adressesList = new Uint8Array(adressesSlice)
    #     const ip = convertirBytesIp(adressesList.slice(0, 4))
    #     const subnet = convertirBytesIp(adressesList.slice(4, 8))
    #     const gateway = convertirBytesIp(adressesList.slice(8, 12))
    #     const dns = convertirBytesIp(adressesList.slice(12, 16))
    #
    #     const ssidBytes = value.buffer.slice(19)
    CHAMP_PACK_WIFI = '<BBB4s4s4s4s'  # 19 bytes
    valeurs = struct.unpack(CHAMP_PACK_WIFI, resultat[:19])
    wifi_ap = resultat[19:].decode('utf-8')
    LOGGER.debug("WIFI : AP \"%s\", connected %s, status %s, channel %s", wifi_ap, *valeurs[0:3])
    ip_client = ipaddress.IPv4Address(valeurs[3])
    ip_netmask = ipaddress.IPv4Address(valeurs[4])
    ip_gateway = ipaddress.IPv4Address(valeurs[5])
    LOGGER.debug("WIFI : ip client %s, netmask %s, gateway %s", ip_client, ip_netmask, ip_gateway)
    return resultat


async def get_wifi2(client, characteristic):
    resultat = await client.read_gatt_char(characteristic)


if __name__ == '__main__':
    logging.basicConfig()
    logging.getLogger('__main__').setLevel(logging.DEBUG)
    asyncio.run(main())

