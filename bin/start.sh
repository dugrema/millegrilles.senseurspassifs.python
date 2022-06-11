#!/bin/bash

source /var/opt/millegrilles/venv/bin/activate
PYTHONPATH="${PYTHONPATH}:/home/mathieu/git/millegrilles.senseurspassifs.python"

# python3 -m millegrilles_senseurspassifs $@
python3 -m senseurspassifs_rpi $@
