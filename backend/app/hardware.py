from __future__ import annotations

import os
import platform
import shutil
import subprocess
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil


@dataclass
class HardwareInfo:
    os_name: str
    os_version: str
    architecture: str
    cpu_name: str
    cpu_cores: int
    cpu_threads: int
    ram_total_gb: float
    ram_available_gb: float
    gpu_name: str | None
    vram_total_mib: int | None
    vram_free_mib: int | None
    nvidia_driver: str | None
    cuda_version: str | None
    disk_free_gb: float
    disk_total_gb: float
    python_version: str
    node_installed: bool
    git_installed: bool
    docker_installed: bool
    office_installed: bool
    wsl_available: bool


def _run(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=12, check=False)
        return (result.stdout or result.stderr or "").strip()
    except Exception:
        return ""


def _nvidia() -> dict[str, Any]:
    query = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    cuda = ""
    full = _run(["nvidia-smi"])
    for line in full.splitlines():
        if "CUDA Version" in line:
            parts = line.split("CUDA Version:")
            if len(parts) > 1:
                cuda = parts[1].split()[0]
                break
    if not query:
        return {
            "gpu_name": None,
            "vram_total_mib": None,
            "vram_free_mib": None,
            "nvidia_driver": None,
            "cuda_version": cuda or None,
        }
    name, total, free, driver = [part.strip() for part in query.split(",", 3)]
    return {
        "gpu_name": name,
        "vram_total_mib": int(float(total)),
        "vram_free_mib": int(float(free)),
        "nvidia_driver": driver,
        "cuda_version": cuda or None,
    }


def _office_installed() -> bool:
    if platform.system() != "Windows":
        return False
    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft Office",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Office",
    ]
    for root in roots:
        if root.exists():
            return True
    return shutil.which("WINWORD.EXE") is not None or shutil.which("winword") is not None


def detect_hardware() -> HardwareInfo:
    vm = psutil.virtual_memory()
    disk = shutil.disk_usage(str(Path.home().anchor or "C:\\"))
    cpu = platform.processor() or "Unknown CPU"
    try:
        import cpuinfo  # type: ignore

        cpu = cpuinfo.get_cpu_info().get("brand_raw", cpu)
    except Exception:
        pass
    if platform.system() == "Windows":
        cpu_ps = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
        if cpu_ps:
            cpu = cpu_ps.splitlines()[-1].strip() or cpu
    nvidia = _nvidia()
    return HardwareInfo(
        os_name=platform.system(),
        os_version=platform.version(),
        architecture=platform.machine(),
        cpu_name=cpu,
        cpu_cores=psutil.cpu_count(logical=False) or 1,
        cpu_threads=psutil.cpu_count(logical=True) or 1,
        ram_total_gb=round(vm.total / (1024**3), 2),
        ram_available_gb=round(vm.available / (1024**3), 2),
        gpu_name=nvidia["gpu_name"],
        vram_total_mib=nvidia["vram_total_mib"],
        vram_free_mib=nvidia["vram_free_mib"],
        nvidia_driver=nvidia["nvidia_driver"],
        cuda_version=nvidia["cuda_version"],
        disk_free_gb=round(disk.free / (1024**3), 2),
        disk_total_gb=round(disk.total / (1024**3), 2),
        python_version=platform.python_version(),
        node_installed=shutil.which("node") is not None,
        git_installed=shutil.which("git") is not None,
        docker_installed=shutil.which("docker") is not None,
        office_installed=_office_installed(),
        wsl_available=shutil.which("wsl") is not None,
    )


def hardware_dict() -> dict[str, Any]:
    return asdict(detect_hardware())
