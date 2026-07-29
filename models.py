"""
ITAM - Modelos de banco de dados

Identidade única do computador (RN001-RN005):
    A identidade é resolvida por machine_uuid + serial_number,
    NUNCA por hostname, usuário ou IP.

Soft delete (RN007): máquinas nunca são removidas fisicamente.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String, Integer, BigInteger, Boolean, DateTime, ForeignKey, Text, JSON,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Computer(Base):
    """Ativo de TI (estação de trabalho / servidor)."""
    __tablename__ = "computers"
    __table_args__ = (
        UniqueConstraint("machine_uuid", name="uq_computers_machine_uuid"),
        Index("ix_computers_hostname", "hostname"),
        Index("ix_computers_serial", "serial_number"),
        Index("ix_computers_logged_user", "logged_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # ------ Identidade (RF001, RF003, RF004) ------
    machine_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(128))
    asset_tag: Mapped[str | None] = mapped_column(String(64))  # patrimônio (futuro, RF021)

    # ------ Identificação geral (RF002, RF005) ------
    hostname: Mapped[str | None] = mapped_column(String(255))
    manufacturer: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(128))

    # ------ CPU (RF006) ------
    cpu_model: Mapped[str | None] = mapped_column(String(255))
    cpu_cores: Mapped[int | None] = mapped_column(Integer)
    cpu_threads: Mapped[int | None] = mapped_column(Integer)

    # ------ RAM (RF007) ------
    ram_total_mb: Mapped[int | None] = mapped_column(BigInteger)
    ram_modules: Mapped[list | None] = mapped_column(JSON)  # [{slot, capacity_mb, speed}]

    # ------ SO (RF009) ------
    os_name: Mapped[str | None] = mapped_column(String(128))
    os_version: Mapped[str | None] = mapped_column(String(64))
    os_build: Mapped[str | None] = mapped_column(String(64))
    os_arch: Mapped[str | None] = mapped_column(String(16))

    # ------ Rede (RF010) ------
    ip_address: Mapped[str | None] = mapped_column(String(64))
    mac_address: Mapped[str | None] = mapped_column(String(32))
    gateway: Mapped[str | None] = mapped_column(String(64))
    dns_servers: Mapped[list | None] = mapped_column(JSON)

    # ------ Contexto (RF011, RF012) ------
    logged_user: Mapped[str | None] = mapped_column(String(128))
    windows_domain: Mapped[str | None] = mapped_column(String(128))

    # ------ Office (RF014) ------
    office_info: Mapped[dict | None] = mapped_column(JSON)  # {name, version, license_type}

    # ------ Controle ------
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # RN007 soft delete
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # RF020

    disks: Mapped[list["Disk"]] = relationship(back_populates="computer", cascade="all, delete-orphan")
    software: Mapped[list["Software"]] = relationship(back_populates="computer", cascade="all, delete-orphan")
    history: Mapped[list["AssetHistory"]] = relationship(back_populates="computer", cascade="all, delete-orphan")
    agent_info: Mapped["AgentInfo | None"] = relationship(back_populates="computer", uselist=False, cascade="all, delete-orphan")


class Disk(Base):
    """Discos do computador (RF008)."""
    __tablename__ = "disks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    computer_id: Mapped[int] = mapped_column(ForeignKey("computers.id"), index=True)
    model: Mapped[str | None] = mapped_column(String(255))
    disk_type: Mapped[str | None] = mapped_column(String(32))  # SSD / HDD / NVMe
    device: Mapped[str | None] = mapped_column(String(64))     # C:, D:...
    total_gb: Mapped[float | None] = mapped_column()
    free_gb: Mapped[float | None] = mapped_column()

    computer: Mapped["Computer"] = relationship(back_populates="disks")


class Software(Base):
    """Softwares instalados (RF013)."""
    __tablename__ = "software"
    __table_args__ = (
        Index("ix_software_name", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    computer_id: Mapped[int] = mapped_column(ForeignKey("computers.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(64))
    publisher: Mapped[str | None] = mapped_column(String(255))
    install_date: Mapped[str | None] = mapped_column(String(32))

    computer: Mapped["Computer"] = relationship(back_populates="software")


class AssetHistory(Base):
    """Histórico de alterações relevantes (RF019, RF023, RN006)."""
    __tablename__ = "asset_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    computer_id: Mapped[int] = mapped_column(ForeignKey("computers.id"), index=True)
    field: Mapped[str] = mapped_column(String(64))       # ex: hostname, ip_address, ram_total_mb
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    computer: Mapped["Computer"] = relationship(back_populates="history")


class AgentInfo(Base):
    """Versão do agente por máquina (RF025)."""
    __tablename__ = "agent_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    computer_id: Mapped[int] = mapped_column(ForeignKey("computers.id"), unique=True)
    agent_id: Mapped[str] = mapped_column(String(64), default=lambda: str(uuid.uuid4()))
    agent_name: Mapped[str | None] = mapped_column(String(128))
    agent_version: Mapped[str | None] = mapped_column(String(32))
    build_date: Mapped[str | None] = mapped_column(String(32))
    os_target: Mapped[str | None] = mapped_column(String(64))
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    computer: Mapped["Computer"] = relationship(back_populates="agent_info")


class AgentVersionHistory(Base):
    """Histórico de versões do agente (RF025 - critério de aceitação)."""
    __tablename__ = "agent_version_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    computer_id: Mapped[int] = mapped_column(ForeignKey("computers.id"), index=True)
    agent_version: Mapped[str] = mapped_column(String(32))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentLog(Base):
    """Logs de execução do agente (RF024)."""
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    computer_id: Mapped[int | None] = mapped_column(ForeignKey("computers.id"), index=True, nullable=True)
    machine_uuid: Mapped[str | None] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
