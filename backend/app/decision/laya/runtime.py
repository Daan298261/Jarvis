"""In-process / loopback-only Laya worker lifecycle (RFC-0171)."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ... import config as app_config
from .pins import LAYA_PINS, LAYA_SOURCE_URL, pin_for, pins_as_dicts, validate_apache_provenance

_LOCK = threading.Lock()
_WARM = False
_ENABLED = False
_INSTALLED = False
_LAST_ERROR = ""
_VERSION = "0.1.0"
_INFERENCE_FN: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
_BIND_HOST = "127.0.0.1"
_BIND_PORT = 0  # 0 = in-process only


class LayaError(RuntimeError):
    pass


def install_root() -> Path:
    path = app_config.data_dir() / "modules" / "laya"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path() -> Path:
    return install_root() / "manifest.json"


def _write_manifest(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "license": "Apache-2.0",
        "license_spdx": "Apache-2.0",
        "source_url": LAYA_SOURCE_URL,
        "version": _VERSION,
        "pins": pins_as_dicts(),
        "bind_host": _BIND_HOST,
        "bind_port": _BIND_PORT,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        payload.update(extra)
    ok, reason = validate_apache_provenance(payload)
    if not ok:
        raise LayaError(reason)
    _manifest_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def verify_pin_file(path: Path, expected_sha256: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise LayaError(f"Laya pin hash mismatch for {path.name}: got {digest}, expected {expected_sha256}")


def install_managed(*, fixture_empty_checkpoint: bool = True) -> dict[str, Any]:
    """Install managed pins.

    Until Capability Lab publishes measured checkpoint digests, the managed
    installer materializes empty pin files that match the documented empty SHA
    and records Apache-2.0 provenance in the manifest.
    """
    global _INSTALLED, _LAST_ERROR
    del fixture_empty_checkpoint  # always empty-pin until Lab refresh
    root = install_root()
    try:
        for pin in LAYA_PINS:
            target = root / pin.filename
            target.write_bytes(b"")
            verify_pin_file(target, pin.sha256)
        manifest = _write_manifest({"status": "installed"})
        with _LOCK:
            _INSTALLED = True
            _LAST_ERROR = ""
        return manifest
    except Exception as exc:
        with _LOCK:
            _INSTALLED = False
            _LAST_ERROR = str(exc)
        raise


def _disk_installed() -> bool:
    manifest = _manifest_path()
    if not manifest.is_file():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    ok, _reason = validate_apache_provenance(payload)
    if not ok:
        return False
    for pin in LAYA_PINS:
        path = install_root() / pin.filename
        if not path.is_file():
            return False
        try:
            verify_pin_file(path, pin.sha256)
        except LayaError:
            return False
    return True


def is_installed() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
    ok = _disk_installed()
    if ok:
        with _LOCK:
            _INSTALLED = True
    return ok


def set_enabled(enabled: bool) -> None:
    global _ENABLED, _WARM
    with _LOCK:
        _ENABLED = bool(enabled)
        if not _ENABLED:
            _WARM = False


def enable_and_warm() -> dict[str, Any]:
    """Keep hot checkpoint warm when resource governor permits (governor soft-OK here)."""
    global _ENABLED, _WARM, _LAST_ERROR
    if not is_installed():
        install_managed()
    with _LOCK:
        _ENABLED = True
        _WARM = True
        _LAST_ERROR = ""
    return status()


def cool_down() -> None:
    global _WARM
    with _LOCK:
        _WARM = False


def set_inference_fn(fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None) -> None:
    """Tests inject a labeled in-process encoder stand-in. Production uses local runtime."""
    global _INFERENCE_FN
    with _LOCK:
        _INFERENCE_FN = fn


def reset_runtime() -> None:
    global _WARM, _ENABLED, _INSTALLED, _LAST_ERROR, _INFERENCE_FN
    with _LOCK:
        _WARM = False
        _ENABLED = False
        _INSTALLED = False
        _LAST_ERROR = ""
        _INFERENCE_FN = None


def status() -> dict[str, Any]:
    installed = is_installed()
    with _LOCK:
        return {
            "installed": installed,
            "enabled": _ENABLED,
            "warm": _WARM,
            "version": _VERSION,
            "bind_host": _BIND_HOST,
            "bind_port": _BIND_PORT,
            "loopback_only": _BIND_HOST in {"127.0.0.1", "::1", "localhost"},
            "in_process": _BIND_PORT == 0,
            "last_error": _LAST_ERROR,
            "pins": pins_as_dicts(),
            "license": "Apache-2.0",
            "source_url": LAYA_SOURCE_URL,
        }


def ready() -> bool:
    installed = is_installed()
    with _LOCK:
        return bool(_ENABLED and _WARM and installed)


def _default_inference(state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
    """Deterministic local encoder stand-in for bounded choices/scores when checkpoint is empty fixture."""
    answers: dict[str, Any] = {}
    text = json.dumps(state, sort_keys=True, default=str).lower()
    for qid, spec in questions.items():
        qtype = str((spec or {}).get("type") or "").lower()
        if qtype == "choice":
            choices = [str(c) for c in (spec.get("choices") or []) if str(c)]
            pick = choices[0] if choices else ""
            for choice in choices:
                token = choice.lower().replace("_", " ")
                if token and token in text:
                    pick = choice
                    break
            answers[qid] = {"type": "choice", "choice": pick, "confidence": 0.72}
        elif qtype == "score":
            score = 0.55
            if "high" in text or "urgent" in text:
                score = 0.82
            elif "low" in text or "ignore" in text:
                score = 0.18
            answers[qid] = {"type": "score", "score": score, "confidence": 0.7}
        else:
            noul = 0.45
            if any(tok in text for tok in ("yes", "true", "approve", "relevant")):
                noul = 0.78
            if any(tok in text for tok in ("no", "false", "deny", "irrelevant")):
                noul = 0.15
            answers[qid] = {"type": "noul", "noul": noul, "confidence": 0.7}
    return {"model": f"laya-local-{_VERSION}", "answers": answers, "fixture_runtime": True}


def infer(state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
    if not ready():
        raise LayaError("Laya is not installed, enabled, and warm")
    with _LOCK:
        fn = _INFERENCE_FN
    started = time.perf_counter()
    if fn is not None:
        payload = fn(state, questions)
    else:
        payload = _default_inference(state, questions)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        raise LayaError("Laya returned no typed answers")
    payload = dict(payload)
    payload["inference_ms"] = elapsed_ms
    payload["model"] = str(payload.get("model") or f"laya-local-{_VERSION}")
    return payload
