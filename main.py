"""
ITAM Agent - Agente de inventário (Windows)

Uso:
    python -m agent.main               -> coleta e envia inventário completo
    python -m agent.main --heartbeat   -> envia apenas heartbeat

Agendar via Tarefas Agendadas do Windows ou GPO:
    - Inventário completo: 1x ao dia
    - Heartbeat: a cada 30 min
"""
import argparse
import logging
import os
import sys
import uuid

import requests

from agent.collector import collect_full_inventory, get_machine_uuid

# ------------- Identificação do agente (RF025) -------------
AGENT_NAME = "IT Asset Agent"
AGENT_VERSION = "1.0.0"
BUILD_DATE = "2026-07-16"
OS_TARGET = "Windows"

# ------------- Configuração -------------
API_URL = os.environ.get("ITAM_API_URL", "https://itam.suaempresa.com.br/api/v1")
API_KEY = os.environ.get("ITAM_API_KEY", "troque-esta-chave")
AGENT_ID_FILE = os.path.join(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "ITAMAgent", "agent_id.txt"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        # Log local do agente (RF024)
        logging.FileHandler(
            os.path.join(os.environ.get("PROGRAMDATA", "."), "ITAMAgent", "agent.log"),
            encoding="utf-8", delay=True,
        ) if os.path.isdir(os.environ.get("PROGRAMDATA", ".")) else logging.NullHandler(),
    ],
)
logger = logging.getLogger("itam.agent")


def get_agent_id() -> str:
    """Identificador único e persistente do agente."""
    os.makedirs(os.path.dirname(AGENT_ID_FILE), exist_ok=True)
    if os.path.isfile(AGENT_ID_FILE):
        with open(AGENT_ID_FILE) as f:
            return f.read().strip()
    agent_id = str(uuid.uuid4())
    with open(AGENT_ID_FILE, "w") as f:
        f.write(agent_id)
    return agent_id


def agent_meta() -> dict:
    return {
        "agent_name": AGENT_NAME,
        "agent_version": AGENT_VERSION,
        "build_date": BUILD_DATE,
        "os_target": OS_TARGET,
        "agent_id": get_agent_id(),
    }


def _post(endpoint: str, payload: dict) -> requests.Response:
    return requests.post(
        f"{API_URL}{endpoint}",
        json=payload,
        headers={"X-API-Key": API_KEY},
        timeout=120,
        verify=True,  # RNF005: HTTPS com certificado válido
    )


def send_error_log(message: str):
    """RF024: envia erro de execução para a API (best effort)."""
    try:
        _post("/logs", {
            "machine_uuid": get_machine_uuid(),
            "level": "ERROR",
            "message": message,
            "agent": agent_meta(),
        })
    except Exception:
        logger.warning("Não foi possível enviar log de erro para a API.")


def run_inventory():
    logger.info("Coletando inventário...")
    try:
        inventory = collect_full_inventory()
        inventory["agent"] = agent_meta()

        if not inventory.get("machine_uuid"):
            raise RuntimeError("Machine UUID não encontrado — inventário abortado.")

        logger.info("Enviando inventário para a API (%d softwares)...", len(inventory["software"]))
        resp = _post("/inventory", inventory)
        resp.raise_for_status()
        result = resp.json()
        logger.info("Sucesso: %s (computer_id=%s, alterações=%s)",
                    result["status"], result["computer_id"], result["changes_recorded"])
    except Exception as e:
        logger.exception("Falha ao executar inventário")
        send_error_log(f"Falha no inventário: {e}")
        sys.exit(1)


def run_heartbeat():
    try:
        resp = _post("/heartbeat", {
            "machine_uuid": get_machine_uuid(),
            "agent": agent_meta(),
        })
        if resp.status_code == 404:
            logger.info("Máquina não cadastrada — enviando inventário completo.")
            run_inventory()
            return
        resp.raise_for_status()
        logger.info("Heartbeat enviado.")
    except Exception as e:
        logger.exception("Falha no heartbeat")
        send_error_log(f"Falha no heartbeat: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ITAM Agent")
    parser.add_argument("--heartbeat", action="store_true", help="Envia apenas heartbeat")
    args = parser.parse_args()

    if args.heartbeat:
        run_heartbeat()
    else:
        run_inventory()
