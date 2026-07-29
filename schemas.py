"""
ITAM - Schemas Pydantic (RF016: validação dos dados recebidos)
"""
from datetime import datetime
from pydantic import BaseModel, Field


# ---------- Payloads enviados pelo AGENTE ----------

class AgentMeta(BaseModel):
    """RF025 - o agente informa sua versão em toda comunicação."""
    agent_name: str = Field(..., examples=["IT Asset Agent"])
    agent_version: str = Field(..., examples=["1.0.0"])
    build_date: str | None = None
    os_target: str | None = None
    agent_id: str | None = None


class DiskIn(BaseModel):
    model: str | None = None
    disk_type: str | None = None
    device: str | None = None
    total_gb: float | None = None
    free_gb: float | None = None


class SoftwareIn(BaseModel):
    name: str
    version: str | None = None
    publisher: str | None = None
    install_date: str | None = None


class RamModuleIn(BaseModel):
    slot: str | None = None
    capacity_mb: int | None = None
    speed: str | None = None


class InventoryIn(BaseModel):
    """Payload completo de inventário enviado pelo agente."""
    # Identidade (obrigatória)
    machine_uuid: str = Field(..., min_length=8)
    serial_number: str | None = None

    # Identificação
    hostname: str | None = None
    manufacturer: str | None = None
    model: str | None = None

    # CPU
    cpu_model: str | None = None
    cpu_cores: int | None = None
    cpu_threads: int | None = None

    # RAM
    ram_total_mb: int | None = None
    ram_modules: list[RamModuleIn] | None = None

    # SO
    os_name: str | None = None
    os_version: str | None = None
    os_build: str | None = None
    os_arch: str | None = None

    # Rede
    ip_address: str | None = None
    mac_address: str | None = None
    gateway: str | None = None
    dns_servers: list[str] | None = None

    # Contexto
    logged_user: str | None = None
    windows_domain: str | None = None

    # Office
    office_info: dict | None = None

    # Coleções
    disks: list[DiskIn] = []
    software: list[SoftwareIn] = []

    # Metadados do agente (RF025)
    agent: AgentMeta


class HeartbeatIn(BaseModel):
    machine_uuid: str
    agent: AgentMeta


class AgentLogIn(BaseModel):
    machine_uuid: str | None = None
    level: str = "ERROR"
    message: str
    agent: AgentMeta | None = None


# ---------- Respostas da API ----------

class InventoryResult(BaseModel):
    status: str            # created | updated
    computer_id: int
    changes_recorded: int


class ComputerOut(BaseModel):
    id: int
    machine_uuid: str
    serial_number: str | None
    hostname: str | None
    manufacturer: str | None
    model: str | None
    cpu_model: str | None
    cpu_cores: int | None
    cpu_threads: int | None
    ram_total_mb: int | None
    os_name: str | None
    os_version: str | None
    os_build: str | None
    os_arch: str | None
    ip_address: str | None
    mac_address: str | None
    logged_user: str | None
    windows_domain: str | None
    is_active: bool
    first_seen: datetime
    last_seen: datetime

    class Config:
        from_attributes = True


class HistoryOut(BaseModel):
    field: str
    old_value: str | None
    new_value: str | None
    changed_at: datetime

    class Config:
        from_attributes = True
