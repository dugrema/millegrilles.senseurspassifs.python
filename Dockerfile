FROM docker.maple.maceroc.com:5000/millegrilles_messages_python:2024.7.43

ENV BUILD_FOLDER=/opt/millegrilles/build \
    BUNDLE_FOLDER=/opt/millegrilles/dist \
    PYTHONPATH=/opt/millegrilles/dist \
    SRC_FOLDER=/opt/millegrilles/build/src \
    WEB_PORT=1443 \
    WEBSOCKET_PORT=1444

COPY . $BUILD_FOLDER

WORKDIR /opt/millegrilles/build

RUN pip3 install --no-cache-dir -r $BUILD_FOLDER/requirements.txt && \
    python3 ./setup.py install

# UID fichiers = 984
# GID millegrilles = 980
USER 984:980

WORKDIR /opt/millegrilles/dist

CMD ["-m", "senseurspassifs_relai_web", "--verbose"]
