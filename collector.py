"""
ITAM Agent - Coletor de informações (Windows)

Usa WMI (via subprocess PowerShell/CIM) + psutil + registro do Windows.
Sem dependência do pacote pywin32 — funciona com PowerShell nativo,
o que facilita empacotar com PyInstaller.
"""
import json
import logging
import platform
import socket
import subprocess
import winreg

import psutil

logger = logging.getLogger("itam.agent.collector")


def _ps(command: str):
    """Executa PowerShell e retorna JSON parseado (ou None)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"{command} | ConvertTo-Json -Depth 3 -Compress"],
            capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = result.stdout.strip()
        if not out:
            return None
        return json.loads(out)
    except Exception:
        logger.exception("Falha ao executar PowerShell: %s", command)
        return None


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ---------------- Identidade ----------------

def get_machine_uuid() -> str | None:
    """RF003: Machine UUID (SMBIOS)."""
    data = _ps("Get-CimInstance Win32_ComputerSystemProduct | Select-Object UUID")
    return (data or {}).get("UUID")


def get_serial_number() -> str | None:
    """RF004: número de série do fabricante."""
    data = _ps("Get-CimInstance Win32_BIOS | Select-Object SerialNumber")
    return (data or {}).get("SerialNumber")


# ---------------- Hardware ----------------

def get_system_info() -> dict:
    """RF002, RF005, RF011, RF012."""
    data = _ps(
        "Get-CimInstance Win32_ComputerSystem | "
        "Select-Object Name, Manufacturer, Model, UserName, Domain, PartOfDomain"
    ) or {}
    return {
        "hostname": data.get("Name") or socket.gethostname(),
        "manufacturer": data.get("Manufacturer"),
        "model": data.get("Model"),
        "logged_user": data.get("UserName"),
        "windows_domain": data.get("Domain") if data.get("PartOfDomain") else None,
    }


def get_cpu_info() -> dict:
    """RF006."""
    data = _ps(
        "Get-CimInstance Win32_Processor | "
        "Select-Object Name, NumberOfCores, NumberOfLogicalProcessors"
    )
    cpu = _as_list(data)[0] if data else {}
    return {
        "cpu_model": (cpu.get("Name") or "").strip() or platform.processor(),
        "cpu_cores": cpu.get("NumberOfCores") or psutil.cpu_count(logical=False),
        "cpu_threads": cpu.get("NumberOfLogicalProcessors") or psutil.cpu_count(logical=True),
    }


def get_ram_info() -> dict:
    """RF007."""
    modules = []
    data = _ps(
        "Get-CimInstance Win32_PhysicalMemory | "
        "Select-Object DeviceLocator, Capacity, Speed"
    )
    for m in _as_list(data):
        capacity = m.get("Capacity")
        modules.append({
            "slot": m.get("DeviceLocator"),
            "capacity_mb": int(int(capacity) / (1024 * 1024)) if capacity else None,
            "speed": str(m.get("Speed") or ""),
        })
    return {
        "ram_total_mb": int(psutil.virtual_memory().total / (1024 * 1024)),
        "ram_modules": modules or None,
    }


def get_disks_info() -> list[dict]:
    """RF008: modelo/tipo via Get-PhysicalDisk, espaço via psutil."""
    disks = []

    physical = _as_list(_ps(
        "Get-PhysicalDisk | Select-Object FriendlyName, MediaType, Size"
    ))
    for p in physical:
        size = p.get("Size")
        disks.append({
            "model": p.get("FriendlyName"),
            "disk_type": str(p.get("MediaType") or "Desconhecido"),
            "device": None,
            "total_gb": round(int(size) / (1024 ** 3), 1) if size else None,
            "free_gb": None,
        })

    # Volumes lógicos com espaço livre
    for part in psutil.disk_partitions(all=False):
        if "fixed" not in part.opts and part.fstype == "":
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "model": None,
                "disk_type": "Volume",
                "device": part.device.rstrip("\\"),
                "total_gb": round(usage.total / (1024 ** 3), 1),
                "free_gb": round(usage.free / (1024 ** 3), 1),
            })
        except (PermissionError, OSError):
            continue

    return disks


# ---------------- Sistema Operacional ----------------

def get_os_info() -> dict:
    """RF009."""
    data = _ps(
        "Get-CimInstance Win32_OperatingSystem | "
        "Select-Object Caption, Version, BuildNumber, OSArchitecture"
    ) or {}
    return {
        "os_name": data.get("Caption") or platform.system(),
        "os_version": data.get("Version") or platform.version(),
        "os_build": str(data.get("BuildNumber") or ""),
        "os_arch": data.get("OSArchitecture") or platform.machine(),
    }


# ---------------- Rede ----------------

def get_network_info() -> dict:
    """RF010: IP, MAC, gateway e DNS da interface ativa."""
    data = _ps(
        "Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True' | "
        "Select-Object IPAddress, MACAddress, DefaultIPGateway, DNSServerSearchOrder"
    )
    adapters = _as_list(data)

    # Prioriza adaptador com gateway (interface principal)
    main = next((a for a in adapters if a.get("DefaultIPGateway")), adapters[0] if adapters else {})

    ips = _as_list(main.get("IPAddress"))
    ipv4 = next((ip for ip in ips if "." in str(ip)), None)

    return {
        "ip_address": ipv4,
        "mac_address": main.get("MACAddress"),
        "gateway": _as_list(main.get("DefaultIPGateway"))[0] if main.get("DefaultIPGateway") else None,
        "dns_servers": _as_list(main.get("DNSServerSearchOrder")) or None,
    }


# ---------------- Softwares ----------------

UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]


def get_installed_software() -> list[dict]:
    """RF013: softwares via registro do Windows (mais rápido que Win32_Product)."""
    seen = set()
    software = []

    for hive, path in UNINSTALL_KEYS:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue

        for i in range(winreg.QueryInfoKey(key)[0]):
            try:
                sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
                name = _reg_value(sub, "DisplayName")
                if not name or name in seen:
                    continue
                system_component = _reg_value(sub, "SystemComponent")
                if system_component == 1:
                    continue
                seen.add(name)
                software.append({
                    "name": name,
                    "version": str(_reg_value(sub, "DisplayVersion") or ""),
                    "publisher": _reg_value(sub, "Publisher"),
                    "install_date": _reg_value(sub, "InstallDate"),
                })
            except OSError:
                continue

    return sorted(software, key=lambda s: s["name"].lower())


def _reg_value(key, name):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def get_office_info() -> dict | None:
    """RF014: detecta Microsoft Office instalado."""
    for s in get_installed_software():
        name = s["name"].lower()
        if "microsoft office" in name or "microsoft 365" in name:
            return {"name": s["name"], "version": s["version"], "publisher": s["publisher"]}
    return None


# ---------------- Inventário completo ----------------

def collect_full_inventory() -> dict:
    """Monta o payload completo de inventário."""
    inventory = {
        "machine_uuid": get_machine_uuid(),
        "serial_number": get_serial_number(),
    }
    inventory.update(get_system_info())
    inventory.update(get_cpu_info())
    inventory.update(get_ram_info())
    inventory.update(get_os_info())
    inventory.update(get_network_info())
    inventory["disks"] = get_disks_info()

    software = get_installed_software()
    inventory["software"] = software
    inventory["office_info"] = get_office_info()

    return inventory
