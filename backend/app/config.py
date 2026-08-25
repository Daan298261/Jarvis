from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    path = repo_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = repo_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = repo_root() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir() -> Path:
    return repo_root() / "runtime" / "llama.cpp"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def default_config_path() -> Path:
    return repo_root() / "config" / "default.json"


class InferenceSettings(BaseModel):
    backend: str = "llama.cpp"
    host: str = "127.0.0.1"
    port: int = 8088
    base_url: str = ""
    model: str = "Qwen3.5-9B-Abliterated"
    profile: str = "abliterated-balanced"
    context_size: int = 32768
    flash_attn: str = "auto"
    fit: bool = True
    fit_target_mib: int = 1024
    cache_type_k: str = "q8_0"
    cache_type_v: str = "q8_0"
    threads: int = 0
    auto_load: bool = True


class BrowserSettings(BaseModel):
    headless: bool = False
    timeout_ms: int = 30000


class VoiceSettings(BaseModel):
    stt_model: str = "tiny.en"
    speak_results: bool = False


class AppSettings(BaseModel):
    bind_host: str = "127.0.0.1"
    bind_port: int = 4780
    lan_access: bool = False
    auth_required: bool = False
    auth_token: str = ""
    inference: InferenceSettings = Field(default_factory=InferenceSettings)
    autonomy: str = "trusted"
    execution_mode: str = "balanced"
    default_timeout_seconds: int = 1800
    retry_limit: int = 4
    logging_level: str = "INFO"
    backup_enabled: bool = True
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    allowed_directories: list[str] = Field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    disabled_tools: list[str] = Field(default_factory=list)
    disabled_workers: list[str] = Field(default_factory=list)


LOG_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR}


def apply_logging_level(level: str | None = None) -> str:
    key = (level or "INFO").strip().upper()
    if key not in LOG_LEVELS:
        key = "INFO"
    numeric = LOG_LEVELS[key]
    root = logging.getLogger()
    root.setLevel(numeric)
    for handler in root.handlers:
        handler.setLevel(numeric)
    return key


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings() -> AppSettings:
    payload: dict[str, Any] = {}
    if default_config_path().exists():
        payload = json.loads(default_config_path().read_text(encoding="utf-8"))
    if settings_path().exists():
        payload = _deep_merge(payload, json.loads(settings_path().read_text(encoding="utf-8")))

    from .security import apply_listen_policy

    payload = apply_listen_policy(payload)
    port = os.environ.get("JARVIS_BIND_PORT")
    if port:
        payload["bind_port"] = int(port)
    return AppSettings.model_validate(payload)


_MCP_ENV_REF = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$|^\$([A-Z_][A-Z0-9_]*)$")


def _scrub_mcp_servers(servers: list[Any] | None) -> list[dict[str, Any]]:
    """Drop raw MCP secrets without importing the tool registry."""
    cleaned: list[dict[str, Any]] = []
    for server in servers or []:
        if not isinstance(server, dict):
            continue
        item = dict(server)
        env: dict[str, str] = {}
        for key, raw in (item.get("env") or {}).items():
            value = str(raw or "").strip()
            if _MCP_ENV_REF.match(value):
                env[str(key)] = value
        item["env"] = env
        cleaned.append(item)
    return cleaned


def save_settings(settings: AppSettings) -> None:
    dump = settings.model_dump()
    dump.pop("auth_token", None)
    inference = dump.get("inference")
    if isinstance(inference, dict):
        inference.pop("api_key", None)
    dump["mcp_servers"] = _scrub_mcp_servers(dump.get("mcp_servers") or [])
    try:
        from .backup import snapshot

        snapshot(reason="settings_save")
    except Exception:
        pass
    settings_path().write_text(json.dumps(dump, indent=2), encoding="utf-8")


def default_allowed_directories() -> list[str]:
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        repo_root(),
        data_dir(),
    ]
    return [str(path) for path in candidates if path.exists()]
