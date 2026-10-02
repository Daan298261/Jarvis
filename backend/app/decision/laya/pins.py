"""Managed Laya pins + Apache-2.0 provenance (RFC-0171).

Production installs download the pinned Hugging Face revision of the
``laya-multilingual`` checkpoint into Jarvis's own data dir and verify every
artifact against the digests checked in below — never against digests written
by the installer itself. Verification results are cached by (size, mtime) so the
hot path does not re-hash a 640 MB checkpoint per decision.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config import data_dir, repo_root

LAYA_SOURCE_URL = "https://github.com/NandhaKishorM/laya"
LAYA_LICENSE = "Apache-2.0"
LAYA_LICENSE_URL = "https://github.com/NandhaKishorM/laya/blob/main/LICENSE"

LAYA_PACKAGE = "laya"
LAYA_PACKAGE_VERSION = "0.3.21"
LAYA_REPO = "convaiinnovations/laya"
LAYA_SUBFOLDER = "multilingual"
# Matches laya.revisions.PINNED_REVISIONS["convaiinnovations/laya"] in laya 0.3.21.
LAYA_REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
# mmBERT-base: 1,024-token default window with a 256-token option head.
LAYA_MAX_LEN = 1024
LAYA_HEAD_MAX_LEN = 256

# Paths are relative to the checkpoint subfolder, as laya.verify_digests expects.
ARTIFACTS: tuple[dict[str, Any], ...] = (
    {
        "name": "model.safetensors",
        "role": "hot_checkpoint",
        "license": LAYA_LICENSE,
        "sha256": "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204",
        "size": 643835514,
    },
    {
        "name": "rl_agent_config.json",
        "role": "agent_config",
        "license": LAYA_LICENSE,
        "sha256": "25061739243b617ad88d1219ba6f8a9c86c5881ca28df024fa2d9b3b2fcc30c6",
        "size": 472,
    },
    {
        "name": "encoder/config.json",
        "role": "encoder_config",
        "license": LAYA_LICENSE,
        "sha256": "83f6916d13ef0f556ac461f28308dc2bffa7ebeadee8ec9e2db5812020ea5bb4",
        "size": 1938,
    },
    {
        "name": "tokenizer/tokenizer.json",
        "role": "tokenizer",
        "license": LAYA_LICENSE,
        "sha256": "609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f",
        "size": 34363188,
    },
    {
        "name": "tokenizer/tokenizer_config.json",
        "role": "tokenizer_config",
        "license": LAYA_LICENSE,
        "sha256": "6c6b2d8e3c84ce0e671c129cd6b374b235d6f9863042a5836358d00a89bbb5a1",
        "size": 524,
    },
)

_VERIFY_LOCK = threading.Lock()
_VERIFIED: dict[str, tuple[int, int, str]] = {}


@dataclass(frozen=True)
class PinRecord:
    name: str
    role: str
    license: str
    sha256: str
    size: int


def expected_digests() -> dict[str, str]:
    return {str(row["name"]): str(row["sha256"]) for row in ARTIFACTS}


def pin_manifest() -> dict[str, Any]:
    return {
        "provider": "laya",
        "license": LAYA_LICENSE,
        "license_url": LAYA_LICENSE_URL,
        "source_url": LAYA_SOURCE_URL,
        "package": LAYA_PACKAGE,
        "package_version": LAYA_PACKAGE_VERSION,
        "repo": LAYA_REPO,
        "subfolder": LAYA_SUBFOLDER,
        "revision": LAYA_REVISION,
        "max_len": LAYA_MAX_LEN,
        "head_max_len": LAYA_HEAD_MAX_LEN,
        "provenance": "Apache-2.0 open System-One implementation (NandhaKishorM/laya)",
        "runtime": "in-process only; never exposed on LAN",
        "artifacts": [dict(row) for row in ARTIFACTS],
    }


def pins() -> list[PinRecord]:
    return [
        PinRecord(
            name=str(row["name"]),
            role=str(row["role"]),
            license=str(row["license"]),
            sha256=str(row["sha256"]),
            size=int(row["size"]),
        )
        for row in ARTIFACTS
    ]


def install_root() -> Path:
    path = data_dir() / "system_one" / "laya"
    path.mkdir(parents=True, exist_ok=True)
    return path


def manifest_path() -> Path:
    return install_root() / "install_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _verified_digest(path: Path) -> str:
    """sha256 of ``path``, cached until its size or mtime changes."""
    stat = path.stat()
    key = str(path.resolve())
    with _VERIFY_LOCK:
        cached = _VERIFIED.get(key)
        if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
            return cached[2]
    digest = sha256_file(path)
    with _VERIFY_LOCK:
        _VERIFIED[key] = (stat.st_size, stat.st_mtime_ns, digest)
    return digest


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def provenance_ok(artifact: PinRecord | dict[str, Any]) -> bool:
    license_id = artifact.license if isinstance(artifact, PinRecord) else artifact.get("license", "")
    return str(license_id).strip() == LAYA_LICENSE


def validate_artifact_bytes(name: str, payload: bytes, *, expected_sha256: str) -> None:
    if not expected_sha256 or set(expected_sha256) == {"0"}:
        raise ValueError(f"Laya artifact {name!r} has no pinned sha256; refuse install")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256.lower():
        raise ValueError(f"Laya artifact {name!r} sha256 mismatch")


def package_version() -> str | None:
    """Installed laya version from package metadata (does not import torch)."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(LAYA_PACKAGE)
    except PackageNotFoundError:
        return None


def ensure_package() -> str:
    """Install the pinned ``laya`` wheel when missing. Never pip-installs under pytest."""
    import os
    import subprocess
    import sys

    current = package_version()
    if current == LAYA_PACKAGE_VERSION:
        return current
    hint = f"pip install laya=={LAYA_PACKAGE_VERSION}"
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError(f"The 'laya' package is not installed ({hint})")
    cmd = [sys.executable, "-m", "pip", "install", f"laya=={LAYA_PACKAGE_VERSION}"]
    try:
        subprocess.check_call(cmd)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"Could not install laya=={LAYA_PACKAGE_VERSION}: {exc}") from exc
    import importlib

    importlib.invalidate_caches()
    current = package_version()
    if current != LAYA_PACKAGE_VERSION:
        raise RuntimeError(
            f"laya {current or 'missing'} after {hint}; Jarvis pins laya=={LAYA_PACKAGE_VERSION}"
        )
    return current


def write_test_install(
    *,
    encoder_bytes: bytes | None = None,
    tokenizer_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Install a labeled fixture for tests (served by the fixture backend, never the encoder)."""
    root = install_root()
    enc = encoder_bytes if encoder_bytes is not None else b"LAYA_TEST_ENCODER_V1"
    tok = tokenizer_bytes if tokenizer_bytes is not None else b'{"laya_test_tokenizer": true}\n'
    enc_path = root / "fixture-encoder.bin"
    tok_path = root / "fixture-tokenizer.json"
    enc_path.write_bytes(enc)
    tok_path.write_bytes(tok)
    payload = {
        "provider": "laya",
        "license": LAYA_LICENSE,
        "source_url": LAYA_SOURCE_URL,
        "source_ref": "test-fixture",
        "fixture": True,
        "artifacts": [
            {
                "name": enc_path.name,
                "path": str(enc_path),
                "sha256": hashlib.sha256(enc).hexdigest(),
                "role": "hot_checkpoint",
                "license": LAYA_LICENSE,
            },
            {
                "name": tok_path.name,
                "path": str(tok_path),
                "sha256": hashlib.sha256(tok).hexdigest(),
                "role": "tokenizer",
                "license": LAYA_LICENSE,
            },
        ],
    }
    manifest_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def install_managed(*, token: str | None = None) -> dict[str, Any]:
    """Download the pinned checkpoint into the Jarvis data dir and verify every digest."""
    version = ensure_package()
    from huggingface_hub import snapshot_download

    snapshot = Path(
        snapshot_download(
            LAYA_REPO,
            revision=LAYA_REVISION,
            cache_dir=str(install_root() / "hub"),
            allow_patterns=[f"{LAYA_SUBFOLDER}/*", f"{LAYA_SUBFOLDER}/**/*"],
            token=token,
        )
    )
    model_dir = snapshot / LAYA_SUBFOLDER
    for record in pins():
        path = model_dir / record.name
        if not path.is_file():
            raise RuntimeError(f"Pinned Laya artifact {record.name!r} missing after download")
        if _verified_digest(path) != record.sha256:
            raise RuntimeError(f"Laya artifact {record.name!r} sha256 mismatch against checked-in pin")
    payload = {
        "provider": "laya",
        "license": LAYA_LICENSE,
        "source_url": LAYA_SOURCE_URL,
        "fixture": False,
        "package_version": version,
        "repo": LAYA_REPO,
        "subfolder": LAYA_SUBFOLDER,
        "revision": LAYA_REVISION,
        "model_dir": str(model_dir),
    }
    manifest_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_install_manifest() -> dict[str, Any] | None:
    path = manifest_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _verify_fixture(root: Path, manifest: dict[str, Any]) -> tuple[bool, str]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False, "Laya install has no artifacts"
    for row in artifacts:
        if not isinstance(row, dict):
            return False, "Corrupt Laya artifact row"
        if not provenance_ok(row):
            return False, f"Artifact {row.get('name')} is not Apache-2.0"
        path = Path(str(row.get("path") or ""))
        if not _inside(root, path) or not path.is_file():
            return False, f"Missing Laya artifact file {row.get('name')}"
        expected = str(row.get("sha256") or "")
        if not expected:
            return False, f"Laya artifact {row.get('name')} missing sha256"
        if _verified_digest(path) != expected.lower():
            return False, f"Laya artifact {row.get('name')} hash mismatch"
    return True, ""


def _verify_managed(root: Path, manifest: dict[str, Any]) -> tuple[bool, str]:
    if manifest.get("revision") != LAYA_REVISION or manifest.get("repo") != LAYA_REPO:
        return False, "Laya install does not match the pinned repo/revision"
    model_dir = Path(str(manifest.get("model_dir") or ""))
    if not _inside(root, model_dir) or not model_dir.is_dir():
        return False, "Laya model_dir is outside the managed install root"
    for record in pins():
        path = model_dir / record.name
        if not path.is_file():
            return False, f"Missing Laya artifact file {record.name}"
        if _verified_digest(path) != record.sha256:
            return False, f"Laya artifact {record.name} hash mismatch against checked-in pin"
    return True, ""


def verify_installed(*, allow_fixture: bool = True) -> tuple[bool, str, dict[str, Any] | None]:
    manifest = load_install_manifest()
    if not manifest:
        return False, "Laya not installed", None
    if manifest.get("license") != LAYA_LICENSE:
        return False, "Laya install missing Apache-2.0 provenance", manifest
    root = install_root()
    if manifest.get("fixture"):
        if not allow_fixture:
            return False, "Laya fixture install is not production-ready", manifest
        ok, reason = _verify_fixture(root, manifest)
    else:
        ok, reason = _verify_managed(root, manifest)
    return ok, reason, manifest


def model_dir() -> Path | None:
    manifest = load_install_manifest()
    if not manifest or manifest.get("fixture"):
        return None
    path = Path(str(manifest.get("model_dir") or ""))
    return path if path.is_dir() else None


def clear_install() -> None:
    root = install_root()
    manifest = manifest_path()
    if manifest.is_file():
        manifest.unlink()
    for path in root.iterdir():
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink()
    with _VERIFY_LOCK:
        _VERIFIED.clear()


def repo_pin_document_path() -> Path:
    """Checked-in pin document for auditors (not the live install)."""
    return repo_root() / "backend" / "app" / "decision" / "laya" / "PINNED.json"
