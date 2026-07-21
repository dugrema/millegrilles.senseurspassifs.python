FROM registry.millegrilles.com/millegrilles/messages_python:2026.3.5 AS stage1

ENV BUILD_FOLDER=/opt/millegrilles/build \
    BUNDLE_FOLDER=/opt/millegrilles/dist \
    PYTHONPATH=/opt/millegrilles/dist \
    SRC_FOLDER=/opt/millegrilles/build/src

WORKDIR /opt/millegrilles/build

COPY requirements.txt $BUILD_FOLDER/requirements.txt

RUN pip3 install --no-cache-dir -r $BUILD_FOLDER/requirements.txt && \
    mkdir -p /var/opt/millegrilles/senseurspassifs && chown 1000:1000 /var/opt/millegrilles/senseurspassifs

FROM stage1

ENV WEB_PORT=1443 \
    WEBSOCKET_PORT=1444

COPY . $BUILD_FOLDER

RUN python3 ./setup.py install

USER 1000:1000

WORKDIR /opt/millegrilles/dist

CMD ["-m", "senseurspassifs_relai_web"]
