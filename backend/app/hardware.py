from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil

_CACHE: tuple[float, "HardwareInfo"] | None = None
_CACHE_TTL_SECONDS = 30.0

_GPU_ARCH = {
    "12.0": "Blackwell",
    "10.0": "Blackwell",
    "9.0": "Hopper",
    "8.9": "Ada Lovelace",
    "8.6": "Ampere",
    "8.0": "Ampere",
    "7.5": "Turing",
    "7.0": "Volta",
}


@dataclass
class HardwareInfo:
    os_name: str
    os_version: str
    os_caption: str
    architecture: str
    cpu_name: str
    cpu_cores: int
    cpu_threads: int
    ram_total_gb: float
    ram_available_gb: float
    gpu_name: str | None
    gpu_architecture: str | None
    gpu_compute_cap: str | None
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


def _run_stdout(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=12, check=False)
        if result.returncode != 0:
            return ""
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _windows_os() -> tuple[str, str]:
    caption = _last_line(_run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_OperatingSystem).Caption"]))
    version = _last_line(_run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_OperatingSystem).Version"]))
    return caption, version or platform.version()


def _nvidia() -> dict[str, Any]:
    query = _run_stdout(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.free,driver_version,compute_cap",
            "--format=csv,noheader,nounits",
        ]
    )
    if not query:
        query = _run_stdout(
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
    empty = {
        "gpu_name": None,
        "vram_total_mib": None,
        "vram_free_mib": None,
        "nvidia_driver": None,
        "cuda_version": cuda or None,
        "gpu_compute_cap": None,
        "gpu_architecture": None,
    }
    if not query:
        return empty
    parts = [part.strip() for part in query.split(",")]
    if len(parts) < 4:
        return empty
    name, total, free, driver = parts[0], parts[1], parts[2], parts[3]
    cap = parts[4] if len(parts) > 4 else None
    return {
        "gpu_name": name,
        "vram_total_mib": int(float(total)),
        "vram_free_mib": int(float(free)),
        "nvidia_driver": driver,
        "cuda_version": cuda or None,
        "gpu_compute_cap": cap,
        "gpu_architecture": _GPU_ARCH.get(cap or "", None),
    }


def _office_installed() -> bool:
    """Detect Office without launching Word/Excel/PowerPoint COM servers."""
    if platform.system() != "Windows":
        return False
    try:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WINWORD.EXE",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\EXCEL.EXE",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\POWERPNT.EXE",
            ):
                try:
                    with winreg.OpenKey(hive, sub):
                        return True
                except OSError:
                    continue
    except Exception:
        pass
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if not base:
            continue
        word = Path(base) / "Microsoft Office" / "root" / "Office16" / "WINWORD.EXE"
        if word.is_file():
            return True
    return False


def _detect() -> HardwareInfo:
    vm = psutil.virtual_memory()
    disk = shutil.disk_usage(str(Path.home().anchor or "C:\\"))
    cpu = platform.processor() or "Unknown CPU"
    try:
        import cpuinfo  # type: ignore

        cpu = cpuinfo.get_cpu_info().get("brand_raw", cpu)
    except Exception:
        pass
    os_caption = f"{platform.system()} {platform.release()}".strip()
    os_version = platform.version()
    if platform.system() == "Windows":
        cpu_ps = _last_line(_run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"]))
        if cpu_ps:
            cpu = cpu_ps
        caption, version = _windows_os()
        if caption:
            os_caption = caption
        if version:
            os_version = version
    nvidia = _nvidia()
    return HardwareInfo(
        os_name=platform.system(),
        os_version=os_version,
        os_caption=os_caption,
        architecture=platform.machine(),
        cpu_name=cpu,
        cpu_cores=psutil.cpu_count(logical=False) or 1,
        cpu_threads=psutil.cpu_count(logical=True) or 1,
        ram_total_gb=round(vm.total / (1024**3), 2),
        ram_available_gb=round(vm.available / (1024**3), 2),
        gpu_name=nvidia["gpu_name"],
        gpu_architecture=nvidia["gpu_architecture"],
        gpu_compute_cap=nvidia["gpu_compute_cap"],
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


def detect_hardware(force: bool = False) -> HardwareInfo:
    global _CACHE
    now = time.monotonic()
    if not force and _CACHE and (now - _CACHE[0]) < _CACHE_TTL_SECONDS:
        return _CACHE[1]
    info = _detect()
    _CACHE = (now, info)
    return info


def hardware_dict(force: bool = False) -> dict[str, Any]:
    return asdict(detect_hardware(force=force))


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _gb(value: float) -> str:
    return f"{value:.1f} GB"


def _mib(value: int | None) -> str:
    if value is None:
        return "n/a"
    gb = value / 1024
    if gb >= 1:
        return f"{value} MiB ({gb:.1f} GB)"
    return f"{value} MiB"


def recommend_inference(info: HardwareInfo) -> str:
    vram = info.vram_total_mib
    if not info.gpu_name or not vram:
        return "No NVIDIA GPU reported. Local 27B inference will be slow on CPU."
    if vram < 8000:
        return "Under 8 GB VRAM. Prefer a smaller quant or heavy CPU offload."
    if vram <= 18000:
        return "16 GB-class GPU. Q4_K_M with llama.cpp --fit on is the working profile; Quality Q5_K_M will spill more to RAM."
    return "VRAM is large enough that Quality Q5_K_M can stay mostly on GPU."


def hardware_summary(info: HardwareInfo | None = None) -> str:
    info = info or detect_hardware()
    gpu = info.gpu_name or "no NVIDIA GPU"
    vram = _mib(info.vram_total_mib) if info.vram_total_mib else "n/a"
    return (
        f"{info.os_caption} · {info.cpu_name} · {_gb(info.ram_total_gb)} RAM · "
        f"{gpu} {vram}"
    ).strip()


def hardware_view(info: HardwareInfo | None = None) -> dict[str, Any]:
    info = info or detect_hardware()
    raw = asdict(info)
    groups = [
        {
            "id": "machine",
            "label": "Machine",
            "items": [
                {"label": "OS", "value": info.os_caption},
                {"label": "Version", "value": info.os_version},
                {"label": "Architecture", "value": info.architecture},
                {"label": "CPU", "value": info.cpu_name},
                {"label": "Cores / threads", "value": f"{info.cpu_cores} / {info.cpu_threads}"},
            ],
        },
        {
            "id": "memory",
            "label": "Memory",
            "items": [
                {"label": "RAM total", "value": _gb(info.ram_total_gb)},
                {"label": "RAM available", "value": _gb(info.ram_available_gb)},
            ],
        },
        {
            "id": "gpu",
            "label": "GPU",
            "items": [
                {"label": "GPU", "value": info.gpu_name or "not detected"},
                {"label": "Architecture", "value": info.gpu_architecture or "n/a"},
                {"label": "Compute capability", "value": info.gpu_compute_cap or "n/a"},
                {"label": "VRAM total", "value": _mib(info.vram_total_mib)},
                {"label": "VRAM free", "value": _mib(info.vram_free_mib)},
                {"label": "NVIDIA driver", "value": info.nvidia_driver or "n/a"},
                {"label": "CUDA", "value": info.cuda_version or "n/a"},
            ],
        },
        {
            "id": "storage",
            "label": "Storage",
            "items": [
                {"label": "Disk free", "value": _gb(info.disk_free_gb)},
                {"label": "Disk total", "value": _gb(info.disk_total_gb)},
            ],
        },
        {
            "id": "software",
            "label": "Software",
            "items": [
                {"label": "Python", "value": info.python_version},
                {"label": "Node", "value": _yes_no(info.node_installed)},
                {"label": "Git", "value": _yes_no(info.git_installed)},
                {"label": "Docker", "value": _yes_no(info.docker_installed)},
                {"label": "Microsoft Office", "value": _yes_no(info.office_installed)},
                {"label": "WSL", "value": _yes_no(info.wsl_available)},
            ],
        },
    ]
    return {
        "summary": hardware_summary(info),
        "recommendation": recommend_inference(info),
        "groups": groups,
        "raw": raw,
    }
