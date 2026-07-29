"""
ITAM - Regras de negócio do inventário

- Identidade única por machine_uuid (RN001-RN005)
- Upsert: cria ou atualiza (RF017, RF018)
- Diff campo a campo gera histórico (RF019, RF023, RN006)
- Atualiza last_seen (RF020)
- Registra versão do agente (RF025)
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api import models
from api.schemas import InventoryIn, AgentMeta

logger = logging.getLogger("itam.services")

# Campos monitorados para histórico de alterações
TRACKED_FIELDS = [
    "hostname", "serial_number", "manufacturer", "model",
    "cpu_model", "cpu_cores", "cpu_threads", "ram_total_mb",
    "os_name", "os_version", "os_build", "os_arch",
    "ip_address", "mac_address", "gateway",
    "logged_user", "windows_domain",
]


def utcnow():
    return datetime.now(timezone.utc)


def upsert_inventory(db: Session, data: InventoryIn) -> tuple[str, models.Computer, int]:
    """
    Cria ou atualiza um computador a partir do inventário do agente.
    Retorna (status, computador, qtd_alterações_registradas).
    """
    computer = (
        db.query(models.Computer)
        .filter(models.Computer.machine_uuid == data.machine_uuid)
        .first()
    )

    changes = 0

    if computer is None:
        # ---- Criação (RF017: evita duplicidade via unique constraint) ----
        computer = models.Computer(machine_uuid=data.machine_uuid)
        db.add(computer)
        _apply_fields(computer, data)
        computer.first_seen = utcnow()
        computer.last_seen = utcnow()
        db.flush()  # gera o ID
        status = "created"
        logger.info("Novo computador cadastrado: %s (%s)", data.hostname, data.machine_uuid)
    else:
        # ---- Atualização com diff (RF018, RF019) ----
        changes = _diff_and_apply(db, computer, data)
        computer.last_seen = utcnow()
        status = "updated"

    # Coleções: substitui snapshot atual (discos e softwares)
    _replace_disks(db, computer, data)
    _replace_software(db, computer, data)

    # RAM módulos / DNS / Office (JSON — sem diff granular)
    computer.ram_modules = [m.model_dump() for m in (data.ram_modules or [])] or None
    computer.dns_servers = data.dns_servers
    computer.office_info = data.office_info

    # Agente (RF025)
    _update_agent_info(db, computer, data.agent)

    db.commit()
    db.refresh(computer)
    return status, computer, changes


def _apply_fields(computer: models.Computer, data: InventoryIn):
    for field in TRACKED_FIELDS:
        setattr(computer, field, getattr(data, field, None))


def _diff_and_apply(db: Session, computer: models.Computer, data: InventoryIn) -> int:
    """Compara campo a campo e registra alterações no histórico (RN006)."""
    changes = 0
    for field in TRACKED_FIELDS:
        new_value = getattr(data, field, None)
        old_value = getattr(computer, field, None)
        if new_value is not None and str(new_value) != str(old_value or ""):
            if old_value is not None:  # só registra histórico se havia valor anterior
                db.add(models.AssetHistory(
                    computer_id=computer.id,
                    field=field,
                    old_value=str(old_value),
                    new_value=str(new_value),
                ))
                changes += 1
            setattr(computer, field, new_value)
    return changes


def _replace_disks(db: Session, computer: models.Computer, data: InventoryIn):
    db.query(models.Disk).filter(models.Disk.computer_id == computer.id).delete()
    for d in data.disks:
        db.add(models.Disk(computer_id=computer.id, **d.model_dump()))


def _replace_software(db: Session, computer: models.Computer, data: InventoryIn):
    db.query(models.Software).filter(models.Software.computer_id == computer.id).delete()
    for s in data.software:
        db.add(models.Software(computer_id=computer.id, **s.model_dump()))


def _update_agent_info(db: Session, computer: models.Computer, agent: AgentMeta):
    """RF025: armazena versão do agente e mantém histórico quando muda."""
    info = (
        db.query(models.AgentInfo)
        .filter(models.AgentInfo.computer_id == computer.id)
        .first()
    )
    if info is None:
        info = models.AgentInfo(computer_id=computer.id)
        db.add(info)
        db.add(models.AgentVersionHistory(
            computer_id=computer.id, agent_version=agent.agent_version,
        ))
    elif info.agent_version != agent.agent_version:
        db.add(models.AgentVersionHistory(
            computer_id=computer.id, agent_version=agent.agent_version,
        ))

    info.agent_name = agent.agent_name
    info.agent_version = agent.agent_version
    info.build_date = agent.build_date
    info.os_target = agent.os_target
    if agent.agent_id:
        info.agent_id = agent.agent_id
    info.last_heartbeat = utcnow()


def heartbeat(db: Session, machine_uuid: str, agent: AgentMeta) -> bool:
    """Atualiza last_seen + heartbeat do agente. Retorna False se máquina desconhecida."""
    computer = (
        db.query(models.Computer)
        .filter(models.Computer.machine_uuid == machine_uuid)
        .first()
    )
    if computer is None:
        return False
    computer.last_seen = utcnow()
    _update_agent_info(db, computer, agent)
    db.commit()
    return True
