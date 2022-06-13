#!/bin/bash

sudo cp -rv bin/start_senseurspassifs_hub.sh /var/opt/millegrilles/bin/start_senseurspassifs_hub.sh

sudo cp -rv millegrilles_senseurspassifs senseurspassifs_rpi /var/opt/millegrilles/python
sudo chown -R mginstance:millegrilles /var/opt/millegrilles/python/millegrilles_senseurspassifs
sudo chown -R mginstance:millegrilles /var/opt/millegrilles/python/senseurspassifs_rpi

