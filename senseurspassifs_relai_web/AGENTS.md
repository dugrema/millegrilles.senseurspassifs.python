# Project Overview – AGENTS

This repository hosts the **MilleGrilles Senseurs Passifs – Web Relay** – a Python‑based back‑end that exposes passive sensor data through a secure HTTP/HTTPS API and a WebSocket endpoint.  
The code is split into a set of logical modules, each responsible for a distinct feature set. Below is a quick reference to the main modules and their purpose.

## Core Application

| File | Description |
|------|-------------|
| `Configuration.py` | Parses environment variables and command‑line options for the web relay (ports, logging). |
| `Context.py` | Extends the generic `MilleGrillesBusContext` to manage the lifecycle of the relay, load the public fiche, and handle graceful shutdown. |
| `SenseurspassifsRelaiWebManager.py` | Orchestrates the main relay logic: handles incoming messages, device registration, and reading distribution. |
| `WebServer.py` | Sets up the `aiohttp` web application, registers HTTP routes (`/inscrire`, `/poll`, `/timeinfo`, …) and starts the HTTP/TLS server. |
| `WebSocketCommands.py` | Implements the WebSocket protocol used by passive sensors to push real‑time data. |
| `MessagesHandler.py` | Contains `AppareilMessageHandler` and `CorrelationAppareil` for processing messages from the broker and correlating them with device registrations. |
| `ReadingsFormatter.py` | Formats and forwards sensor readings to connected clients. |
| `MgbusHandler.py` | Helper for interacting with the message‑bus (Pika) and sending commands such as `disconnectRelay`. |
| `Chiffrage.py` | Utility functions for encryption/decryption of sensor data (currently a placeholder for future use). |
| `__main__.py` | Entry point that creates the context, manager, and starts the event loop. |

## Feature Modules

| Module | Path | Description |
|--------|------|-------------|
| **HTTP API** | `WebServer.py` | Implements the REST endpoints used by sensors to register (`/inscrire`), poll for commands (`/poll`), renew certificates (`/renouveler`), and request data (`/requete`). |
| **WebSocket API** | `WebSocketCommands.py` | Provides a real‑time channel for sensors to push readings and receive commands without polling. |
| **Message Handling** | `MessagesHandler.py` | Decodes and verifies incoming broker messages, manages device correlations, and ensures message integrity. |
| **Reading Distribution** | `ReadingsFormatter.py` | Serialises sensor readings into the expected format and sends them to connected clients or the broker. |
| **Bus Interaction** | `MgbusHandler.py` | Wraps Pika interactions for sending commands and handling shutdown notifications. |

## Utilities & Helpers

| File | Description |
|------|-------------|
| `Constantes.py` | Shared constants (e.g., environment variable names, default port values). |
| `Chiffrage.py` | Placeholder for future encryption utilities. |
| `__init__.py` | Package initialisation. |

## Development Notes

* **Installation**  
  ```bash
  pip install -r requirements.txt
  ```
* **Run**  
  ```bash
  python -m senseurspassifs_relai_web
  ```
* **Configuration**  
  Environment variables:  
  - `SENSEURSPASSIFS_RELAI_WEB_PORT` – HTTP/HTTPS port (default 443).  
  - `SENSEURSPASSIFS_RELAI_WEBSOCKET_PORT` – WebSocket port (default 444).  
  Logging can be enabled with `--verbose` and timestamps with `--logtime`.
* **Testing**  
  Tests are located in `tests/` and can be run with `pytest`.

## Nomenclature

* `uuid_appareil` – unique identifier for a physical sensor device.  
* `tuuid` – filesystem unique identifier (file or directory).  
* `cle_id` – decryption key identifier.  
* `instance_id` – unique identifier for the running instance of the relay.
