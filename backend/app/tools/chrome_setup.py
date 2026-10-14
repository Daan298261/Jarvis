"""Package and register the optional Chrome connector for the current Windows user."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

from ..config import repo_root
from .chrome_connector import connector_dir, read_json

FILES = ("manifest.json", "background.js", "ad-rules.js", "page.js", "popup.html", "popup.js", "native_host.py", "install-host.ps1", "filters/easylist-domains.json", "filters/NOTICE.md")


def source_dir() -> Path:
    source = repo_root() / "extensions" / "chrome"
    return source if (source / "manifest.json").is_file() else Path(__file__).with_name("chrome_assets")


def extension_id() -> str:
    manifest = read_json(source_dir() / "manifest.json")
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    return "".join(chr(ord("a") + int(nibble, 16)) for nibble in digest)


def setup_status() -> dict:
    install_dir = connector_dir().parent / "chrome-extension"
    registered = False
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\NativeMessagingHosts\com.anzu.website_connector") as key:
                manifest_path = winreg.QueryValue(key, None)
                host = read_json(Path(manifest_path))
                registered = host.get("allowed_origins") == [f"chrome-extension://{extension_id()}/"] and Path(host.get("path") or "").is_file()
        except OSError:
            pass
    return {"registered": registered, "install_dir": str(install_dir), "extension_id": extension_id(), "extension_loaded": "unknown", "instructions": "Open chrome://extensions, enable Developer mode, click Load unpacked and select the prepared folder. Then share a website tab."}


def prepare_connector() -> dict:
    if sys.platform != "win32":
        raise RuntimeError("Native-host registration is currently supported on Windows")
    import winreg
    root = connector_dir()
    root.mkdir(parents=True, exist_ok=True)
    install_dir = root.parent / "chrome-extension"
    for name in FILES:
        source = source_dir() / name
        target = install_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    packaged = source_dir() / "native" / "anzu-chrome-host.exe"
    built = repo_root() / "runtime" / "chrome-native-host" / "anzu-chrome-host.exe"
    executable = packaged if packaged.is_file() else built
    if executable.is_file():
        target = root / "anzu-chrome-host.exe"
        shutil.copy2(executable, target)
    else:
        from ..workers.isolated_runtime import host_python
        python = host_python()
        if any(char in python + str(root) for char in ('"', '%', '\r', '\n')):
            raise ValueError("Unsupported native-host launcher path")
        target = root / "host.cmd"
        shutil.copy2(install_dir / "native_host.py", root / "native_host.py")
        target.write_text(f'@echo off\n"{python}" -u "{root / "native_host.py"}" %*\n', encoding="utf-8")
    manifest_path = root / "host-manifest.json"
    manifest_path.write_text(json.dumps({"name": "com.anzu.website_connector", "description": "ANZU owner-shared Chrome connector", "path": str(target), "type": "stdio", "allowed_origins": [f"chrome-extension://{extension_id()}/"]}), encoding="utf-8")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\NativeMessagingHosts\com.anzu.website_connector") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
    return setup_status()


def connector_package() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(source_dir() / name, "chrome/" + name)
        executable = source_dir() / "native" / "anzu-chrome-host.exe"
        if not executable.is_file():
            executable = repo_root() / "runtime" / "chrome-native-host" / "anzu-chrome-host.exe"
        if executable.is_file():
            archive.write(executable, "chrome/native/anzu-chrome-host.exe")
    return output.getvalue()
