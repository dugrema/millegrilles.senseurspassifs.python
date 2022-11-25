import asyncio

from aiohttp import web


async def handle_post_inscrire(server, request):
    return web.json_response(status=403)


async def handle_post_poll(server, request):
    await asyncio.sleep(1)
    return web.json_response({"text": "Allo, c'est ma reponse"})


async def handle_post_commande(server, request):
    print("Commande recue")
    return web.Response(status=202)
