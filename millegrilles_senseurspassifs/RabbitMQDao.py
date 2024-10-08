import asyncio
import logging

from asyncio import Event, TimeoutError
from typing import Optional

from millegrilles_messages.messages import Constantes
from millegrilles_messages.messages.MessagesModule import RessourcesConsommation, MessageProducerFormatteur
from millegrilles_messages.messages.MessagesThread import MessagesThread
from millegrilles_senseurspassifs.Commandes import CommandHandler
from millegrilles_messages.messages.MessagesModule import MessageWrapper
# from millegrilles_senseurspassifs.EtatSenseursPassifs import EtatSenseursPassifs
from millegrilles_senseurspassifs import Constantes as ConstantesInstance


class MqThread:

    def __init__(self, event_stop: Event, etat_senseurspassifs, command_handler: CommandHandler, routing_keys_consumers: list):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__event_stop = event_stop
        self.__etat_senseurspassifs = etat_senseurspassifs
        self.__command_handler = command_handler
        self.__routing_key_consumers = routing_keys_consumers

        self.__mq_host: Optional[str] = None
        self.__mq_port: Optional[str] = None
        self.__messages_thread: Optional[MessagesThread] = None
        self.__event_producer: Optional[Event] = None

    async def configurer(self):
        self.__mq_host = self.__etat_senseurspassifs.mq_host
        self.__mq_port = self.__etat_senseurspassifs.mq_port

        env_configuration = {
            Constantes.ENV_CA_PEM: self.__etat_senseurspassifs.configuration.ca_pem_path,
            Constantes.ENV_CERT_PEM: self.__etat_senseurspassifs.configuration.cert_pem_path,
            Constantes.ENV_KEY_PEM: self.__etat_senseurspassifs.configuration.key_pem_path,
            Constantes.ENV_MQ_HOSTNAME: self.__mq_host,
            Constantes.ENV_MQ_PORT: self.__mq_port,
        }

        messages_thread = MessagesThread(self.__event_stop)
        messages_thread.set_env_configuration(env_configuration)
        self.creer_ressources_consommation(messages_thread)
        await messages_thread.start_async()  # Preparer le reste de l'environnement

        self.__messages_thread = messages_thread

    def creer_ressources_consommation(self, messages_thread: MessagesThread):
        reply_res = RessourcesConsommation(self.callback_reply_q)

        # RK Public pour toutes les instances
        for rk in self.__routing_key_consumers:
            if isinstance(rk, str):
                reply_res.ajouter_rk(Constantes.SECURITE_PRIVE, rk)
            elif isinstance(rk, tuple):
                securite, rk_str = rk
                reply_res.ajouter_rk(securite, rk_str)

        messages_thread.set_reply_ressources(reply_res)

    async def run(self):
        # coroutine principale d'execution MQ
        await self.__messages_thread.run_async()

    async def callback_reply_q(self, message: MessageWrapper, module_messages):
        self.__logger.debug("RabbitMQ nessage recu : %s" % message)
        producer = self.__messages_thread.get_producer()
        reponse = await self.__command_handler.executer_commande(producer, message)

        if reponse is not None:
            reply_to = message.reply_to
            correlation_id = message.correlation_id
            producer = self.__messages_thread.get_producer()
            await producer.repondre(reponse, reply_to, correlation_id)

    def get_producer(self) -> Optional[MessageProducerFormatteur]:
        try:
            return self.__messages_thread.get_producer()
        except AttributeError:
            # Thread inactive
            return None

    async def attendre_pret(self, timeout=30):
        if self.__messages_thread is not None:
            await self.__messages_thread.attendre_pret(timeout)
            return True
        else:
            return False


class RabbitMQDao:

    def __init__(self, event_stop: Event, etat_senseurspassifs, modules_handler):
        self.__logger = logging.getLogger(__name__ + '.' + self.__class__.__name__)
        self.__event_stop = event_stop
        self.__etat_senseurspassifs = etat_senseurspassifs
        self.__modules_handler = modules_handler

        self.__command_handler = CommandHandler(etat_senseurspassifs, modules_handler)

        self.__producer: Optional[MessageProducerFormatteur] = None
        self.__mq_thread: Optional[MqThread] = None

    async def creer_thread(self):
        routing_keys = self.__modules_handler.get_routing_key_consumers()
        return MqThread(self.__event_stop, self.__etat_senseurspassifs, self.__command_handler, routing_keys)

    def get_producer(self) -> Optional[MessageProducerFormatteur]:
        return self.__producer

    async def run(self):

        while not self.__event_stop.is_set():
            self.__logger.info("Debut thread asyncio MessagesThread")

            try:
                # Toujours tenter de creer le compte sur MQ - la detection n'est pas au point a l'interne
                resultat_creer_compte = await self.creer_compte_mq()
                self.__logger.info("Resultat creer compte MQ : %s" % resultat_creer_compte)

                # coroutine principale d'execution MQ
                self.__mq_thread = await self.creer_thread()
                await self.__mq_thread.configurer()
                self.__producer = self.__mq_thread.get_producer()
                self.__etat_senseurspassifs.set_producer(self.__producer)  # Hook producer globalement

                await self.__mq_thread.run()
            except Exception as e:
                self.__logger.exception("Erreur connexion MQ")
            finally:
                self.__mq_thread = None
                self.__producer = None
                self.__etat_senseurspassifs.set_producer(None)  # Cleanup hook producer globalement

            # Attendre pour redemarrer execution module
            self.__logger.info("Fin thread asyncio MessagesThread, attendre 30 secondes pour redemarrer")
            try:
                await asyncio.wait_for(self.__event_stop.wait(), 30)
            except TimeoutError:
                pass

        self.__logger.info("Fin thread MessagesThread")

    async def creer_compte_mq(self):
        """
        Creer un compte sur MQ via https (monitor).
        :return:
        """
        mq_host = self.__etat_senseurspassifs.mq_host
        self.__logger.info("Creation compte MQ avec %s" % mq_host)

        # Le monitor peut etre trouve via quelques hostnames :
        #  nginx : de l'interne, est le proxy web qui est mappe vers le monitor
        #  mq_host : de l'exterieur, est le serveur mq qui est sur le meme swarm docker que nginx
        hosts = ['nginx', self.__etat_senseurspassifs.mq_host]
        port = 444  # 443
        path = 'administration/ajouterCompte'

        mq_cafile = self.__etat_senseurspassifs.configuration.ca_pem_path
        mq_certfile = self.__etat_senseurspassifs.configuration.cert_pem_path
        mq_keyfile = self.__etat_senseurspassifs.configuration.key_pem_path

        with open(mq_certfile, 'r') as fichier:
            chaine_cert = {'certificat': fichier.read()}

        cle_cert = (mq_certfile, mq_keyfile)
        self.__logger.debug("Creation compte MQ avec fichiers %s" % str(cle_cert))
        try:
            import requests
            for host in hosts:
                path_complet = 'https://%s:%d/%s' % (host, port, path)
                try:
                    self.__logger.debug("Creation compte avec path %s" % path_complet)
                    reponse = requests.post(path_complet, json=chaine_cert, cert=cle_cert, verify=mq_cafile)
                    if reponse.status_code in [200, 201]:
                        return True
                    else:
                        self.__logger.error("Erreur creation compte MQ via https, code : %d", reponse.status_code)
                except requests.exceptions.SSLError as e:
                    self.__logger.exception("Erreur connexion https pour compte MQ")
                except requests.exceptions.ConnectionError:
                    # Erreur connexion au serveur, tenter le prochain host
                    self.__logger.info("Echec creation compte MQ avec %s" % path_complet)
        except ImportError:
            self.__logger.warning("requests non disponible, on ne peut pas tenter d'ajouter le compte MQ")

        return False

    async def attendre_pret(self, timeout=30) -> bool:
        if self.__mq_thread is not None:
            return await self.__mq_thread.attendre_pret(timeout)
        else:
            return False
