# Project Overview – AGENTS

This repository hosts the **MilleGrilles Senseurs Passifs** – a Python‑based back‑end that collects data from a variety of passive sensors (Bluetooth, RF24, DHT, etc.) and exposes them through a web relay.  
The code is split into a set of logical modules, each responsible for a distinct feature set. Below is a quick reference to the main modules and their purpose.

## Core Application

| File | Description |
|------|-------------|
| `src/Application.py` | Root application class that loads configuration, initialises modules and runs the event loop. |
| `src/Configuration.py` | Parses environment variables and configuration files. |
| `src/EtatSenseursPassifs.py` | Holds runtime state (certificate, producer, configuration) and exposes helper methods. |
| `src/ModulesBase.py` | Base classes for modules that consume or produce sensor data. |
| `src/AppareilModule.py` | Abstract base for device handlers; concrete handlers are in `ModulesRpi.py`. |
| `src/Commandes.py` | Handles incoming commands from the broker (e.g. `inscrireAppareil`). |
| `src/RabbitMQDao.py` | Wrapper around the RabbitMQ connection and message handling. |

## Feature Modules

| Module | Path | Description |
|--------|------|-------------|
| **Bluetooth Client** | `src/bluetooth_client` | Scans for Bluetooth devices that expose the custom *SenseursPassifs* GATT services and reads their characteristics. |
| **Web Relay** | `src/senseurspassifs_relai_web` | Implements the HTTP/HTTPS API (`/inscrire`, `/poll`, `/timeinfo`, …) and a WebSocket endpoint for real‑time data. |
| **Raspberry‑Pi Runtime** | `src/senseurspassifs_rpi` | Provides concrete module implementations for the Pi: LCD display, DHT sensor, RF24 hub, etc. |
| **Utilities** | `src` | `MillegrillesIdb.py` (IndexedDB helper for the web side), `VersionInfo.py`, etc. |

## Utilities & Helpers

| File | Description |
|------|-------------|
| `src/MillegrillesIdb.py` | IndexedDB helper for storing collections, notes, and chat history. |
| `src/VersionInfo.py` | Displays current app version and build information. |
| `src/AGENTS.md` | This file – high‑level overview of the project’s modules. |

## Development Notes

* **Installation**  
  ```bash
  pip install -r requirements.txt
  ```
* **Run**  
  ```bash
  python -m senseurspassifs_rpi.SenseursPassifsRpi
  ```
* **Build Docker**  
  ```bash
  docker build -t millegrilles_senseurspassifs_python .
  ```
* **Testing**  
  Tests are located in `test/` and run with `pytest`.

## Nomenclature

* `uuid_senseur` – unique identifier for a physical sensor.  
* `tuuid` – filesystem unique identifier (file or directory).  
* `cle_id` – decryption key identifier.  
* `instance_id` – unique identifier for the running instance.
