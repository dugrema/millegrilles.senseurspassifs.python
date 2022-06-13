#!/bin/bash

sudo cp -r millegrilles_senseurspassifs senseurspassifs_rpi /var/opt/millegrilles/python
sudo chown -R mginstance:millegrilles /var/opt/millegrilles/python/millegrilles_senseurspassifs
sudo chown -R mginstance:millegrilles /var/opt/millegrilles/python/senseurspassifs_rpi

