import asyncio
import datetime
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
        if characteristic.uuid == uuid_characteristics['getUserId']:
            await get_user_id(client, characteristic)
        elif characteristic.uuid == uuid_characteristics['getIdmg']:
            await get_idmg(client, characteristic)
        elif characteristic.uuid == uuid_characteristics['getWifi']:
            await get_wifi(client, characteristic)
        elif characteristic.uuid == uuid_characteristics['getLectures']:
            await get_lectures(client, characteristic)
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
    CHAMP_PACK_WIFI = '<BBB4s4s4s4s'  # 19 bytes
    valeurs = struct.unpack(CHAMP_PACK_WIFI, resultat[:19])
    wifi_ap = resultat[19:].decode('utf-8')
    LOGGER.debug("WIFI : AP \"%s\", connected %s, status %s, channel %s", wifi_ap, *valeurs[0:3])
    ip_client = ipaddress.IPv4Address(valeurs[3])
    ip_netmask = ipaddress.IPv4Address(valeurs[4])
    ip_gateway = ipaddress.IPv4Address(valeurs[5])
    dns_gateway = ipaddress.IPv4Address(valeurs[6])
    LOGGER.debug("WIFI : ip client %s, netmask %s, gateway %s, dns %s", ip_client, ip_netmask, ip_gateway, dns_gateway)


async def get_lectures(client, characteristic):
    resultat = await client.read_gatt_char(characteristic)

    # encoded_lectures = struct.pack('<BIhhhB', rtc, time_val, temperature_1, temperature_2, humidite, switch_encoding)
    rtc, time_val, temperature_1, temperature_2, humidite, switch_encoding = struct.unpack('<BIhhhB', resultat)
    LOGGER.debug("Time %s (RTC: %s)", datetime.datetime.fromtimestamp(time_val), rtc)

    if temperature_2 is not None:
        temperature_2 = temperature_2 / 100
        temperature_1 = temperature_1 / 100
        LOGGER.debug("Temperatures 1: %sC, 2: %sC", temperature_1, temperature_2)
    elif temperature_1 is not None:
        temperature_1 = temperature_1 / 100
        LOGGER.debug("Temperature 1: %sC", temperature_1)

    if humidite is not None:
        humidite = humidite / 10
        LOGGER.debug("Humidite: %s%%", humidite)

    # Switch decoding - une switch est 2 bits
    bools_switch = unpack_bools(switch_encoding)
    # LOGGER.debug("Bools switch %s", bools_switch)
    for i in range(0, 4):
        if bools_switch[i*2] is True:
            LOGGER.debug("Switch %d = %s", i, bools_switch[i*2+1])


def unpack_bools(val) -> list[bool]:
    """
    Pack jusqu'a 8 bools dans un seul byte
    """

    bool_vals = list()

    for i in range(0, 8):
        masque = 1 << i
        val_masquee = val & masque
        courant = val_masquee > 0
        bool_vals.append(courant)

    return bool_vals


if __name__ == '__main__':
    logging.basicConfig()
    logging.getLogger('__main__').setLevel(logging.DEBUG)
    asyncio.run(main())

