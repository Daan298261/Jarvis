"""Owned, resumable WSL engine setup. Does not change other agent registrations."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path

from .store import atomic_json
from .privacy import private_directory

DISTRO = "ANZU-REA"
LOCK_PATH = Path(__file__).with_name("engine-lock.json")
_SETUP_LOCK = threading.Lock()


def runtime_root() -> Path:
    # MSIX callers can receive a redirected LOCALAPPDATA with very long paths.
    # Use one stable owner path shared with the installed desktop app.
    p = Path.home() / ".anzu" / "runtime" / "reverse-engineering"
    private_directory(p)
    return p


def host_node() -> str:
    bundled = runtime_root() / "node-windows/node-v24.14.0-win-x64/node.exe"
    if bundled.is_file():
        return str(bundled)
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js 22.19+ or 24.11+ is required for Windows browser observation")
    return node


def install_host() -> None:
    import zipfile
    spec = json.loads(LOCK_PATH.read_text())["node_windows"]
    archive = download("node-windows.zip", spec)
    destination = runtime_root() / "node-windows"
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if not (destination / name).resolve().is_relative_to(destination.resolve()):
                raise ValueError("Invalid Node package entry")
        z.extractall(destination)
    node = host_node()
    npm = Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if not npm.is_file():
        raise RuntimeError("The Node.js installation does not include npm")
    host = runtime_root() / "host"
    host.mkdir(exist_ok=True)
    (host / "package.json").write_text('{"name":"anzu-rea-host","private":true,"dependencies":{"rea-agents":"3.2.1"}}', encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("rea-package-lock.json"), host / "package-lock.json")
    subprocess.run([node, str(npm), "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                   cwd=host, capture_output=True, check=True, timeout=600,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lock = json.loads((host / "package-lock.json").read_text())
    expected = json.loads(LOCK_PATH.read_text())["rea"]["integrity"]
    if lock["packages"]["node_modules/rea-agents"]["integrity"] != expected:
        raise RuntimeError("Windows REA package integrity does not match the engine lock")


def state() -> dict:
    p = runtime_root() / "setup.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"status": "not_installed"}


def _state(**value) -> dict:
    atomic_json(runtime_root() / "setup.json", value)
    return value


def wsl(*args: str, timeout: int = 30) -> str:
    result = subprocess.run(["wsl.exe", "-d", DISTRO, "-u", "root", "--exec", *args],
                            capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = result.stdout.decode("utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError((result.stderr.decode("utf-8", errors="replace") or text)[-4000:])
    return text


def linux_path(path: str) -> str:
    # wslpath receives one argument; never interpolate user paths into shell code.
    return wsl("wslpath", "-a", "-u", Path(path).resolve().as_posix()).strip()


def download(name: str, spec: dict) -> Path:
    cache = runtime_root() / "downloads"
    cache.mkdir(exist_ok=True)
    p = cache / name
    algorithm = spec.get("algorithm", "sha256")
    expected = spec[algorithm]
    if p.exists():
        with p.open("rb") as cached:
            if hashlib.file_digest(cached, algorithm).hexdigest() == expected:
                return p
    tmp = p.with_suffix(p.suffix + ".partial")
    req = urllib.request.Request(spec["url"], headers={"User-Agent": "ANZU-REA/1"})
    with urllib.request.urlopen(req, timeout=90) as src, tmp.open("wb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
    with tmp.open("rb") as f:
        actual = hashlib.file_digest(f, algorithm).hexdigest()
    if actual != expected:
        tmp.unlink()
        raise ValueError(f"Checksum mismatch for {name}; installation stopped")
    os.replace(tmp, p)
    return p


def readiness() -> dict:
    out = state()
    out["versions"] = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    out["runtime_root"] = str(runtime_root())
    if out.get("status") != "ready":
        return out
    try:
        response = wsl("/opt/anzu/bin/rea", "capabilities", "--json", timeout=45)
        out["capabilities"] = json.loads(response)
        out["status"] = "ready"
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        out.update(status="needs_repair", error=str(exc))
    return out


def install() -> dict:
    if not _SETUP_LOCK.acquire(blocking=False):
        return state()
    try:
        if os.name != "nt" or not shutil.which("wsl.exe"):
            raise RuntimeError("This installer requires Windows x64 with WSL2 enabled")
        specs = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        _state(status="installing", stage="Downloading verified Ubuntu root filesystem")
        rootfs = download("ubuntu-rootfs.tar.gz", specs["ubuntu"])
        listing = subprocess.run(["wsl.exe", "--list", "--quiet"], capture_output=True, timeout=30)
        names = listing.stdout.decode("utf-16-le", errors="replace")
        if DISTRO not in names.split():
            _state(status="installing", stage="Importing dedicated ANZU-REA distribution")
            subprocess.run(["wsl.exe", "--import", DISTRO, str(runtime_root() / "wsl"), str(rootfs), "--version", "2"],
                           check=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # Dedicated distro root only; no user distribution or global Java changes.
        _state(status="installing", stage="Installing OS prerequisites")
        wsl("bash", "-lc", "export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y ca-certificates unzip xz-utils python3 gcc clang file", timeout=900)
        paths = {}
        for key, filename in [("node", "node.tar.xz"), ("jdk", "jdk.tar.gz"), ("ghidra", "ghidra.zip"), ("jadx", "jadx.zip")]:
            _state(status="installing", stage=f"Downloading verified {key} {specs[key]['version']}")
            paths[key] = linux_path(str(download(filename, specs[key])))
        script = Path(__file__).with_name("setup-engine.sh")
        _state(status="installing", stage="Installing pinned analysis tools")
        wsl("bash", linux_path(str(script)), paths["node"], paths["jdk"], paths["ghidra"], paths["jadx"],
            linux_path(str(Path(__file__).with_name("rea-package-lock.json"))), timeout=900)
        # npm lockfile records exact transitive artifacts; version/integrity checked separately.
        installed = json.loads(wsl("cat", "/opt/anzu/rea/node_modules/rea-agents/package.json"))
        if installed["version"] != specs["rea"]["version"]:
            raise RuntimeError("Installed REA version does not match the engine lock")
        _state(status="installing", stage="Installing pinned Windows browser adapter")
        install_host()
        return _state(status="ready", stage="Static analysis engine installed", versions={k:v.get("version") for k,v in specs.items()})
    except Exception as exc:
        _state(status="failed", stage="Setup stopped; repair retries verified steps", error=str(exc)[-4000:])
        raise
    finally:
        _SETUP_LOCK.release()
