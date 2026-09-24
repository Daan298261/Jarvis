"""Managed Laya pins + Apache-2.0 provenance (RFC-0171)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config import data_dir, repo_root

# Upstream: https://github.com/NandhaKishorM/laya — Apache-2.0
LAYA_SOURCE_URL = "https://github.com/NandhaKishorM/laya"
LAYA_LICENSE = "Apache-2.0"
LAYA_LICENSE_URL = "https://github.com/NandhaKishorM/laya/blob/main/LICENSE"

# Pinned release/commit for managed installs. Update only with hash re-validation.
LAYA_SOURCE_REF = "v0.1.0"
# Placeholder digest format is sha256 of the canonical pin document itself when
# artifacts are vendor-mirrored; install validates downloaded bytes against ARTIFACTS.
LAYA_SOURCE_COMMIT = "0000000000000000000000000000000000000000"

# Managed checkpoint artifacts (loopback/in-process only). Hashes are required;
# empty sha256 means "not yet mirrored" and install refuses to mark ready.
ARTIFACTS: tuple[dict[str, str], ...] = (
    {
        "name": "laya-encoder-multilingual.safetensors",
        "version": "0.1.0",
        "role": "hot_checkpoint",
        "license": LAYA_LICENSE,
        "source_url": f"{LAYA_SOURCE_URL}/releases/download/{LAYA_SOURCE_REF}/laya-encoder-multilingual.safetensors",
        # Production install must replace with the real digest before enabling.
        "sha256": "",
    },
    {
        "name": "laya-tokenizer.json",
        "version": "0.1.0",
        "role": "tokenizer",
        "license": LAYA_LICENSE,
        "source_url": f"{LAYA_SOURCE_URL}/releases/download/{LAYA_SOURCE_REF}/laya-tokenizer.json",
        "sha256": "",
    },
)


@dataclass(frozen=True)
class PinRecord:
    name: str
    version: str
    role: str
    license: str
    source_url: str
    sha256: str


def pin_manifest() -> dict[str, Any]:
    return {
        "provider": "laya",
        "license": LAYA_LICENSE,
        "license_url": LAYA_LICENSE_URL,
        "source_url": LAYA_SOURCE_URL,
        "source_ref": LAYA_SOURCE_REF,
        "source_commit": LAYA_SOURCE_COMMIT,
        "provenance": "Apache-2.0 open System-One implementation (NandhaKishorM/laya)",
        "runtime": "loopback-only or in-process; never expose on LAN",
        "artifacts": [dict(row) for row in ARTIFACTS],
    }


def pins() -> list[PinRecord]:
    return [
        PinRecord(
            name=row["name"],
            version=row["version"],
            role=row["role"],
            license=row["license"],
            source_url=row["source_url"],
            sha256=row["sha256"],
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


def provenance_ok(artifact: PinRecord | dict[str, str]) -> bool:
    license_id = artifact.license if isinstance(artifact, PinRecord) else artifact.get("license", "")
    return str(license_id).strip() == LAYA_LICENSE


def validate_artifact_bytes(name: str, payload: bytes, *, expected_sha256: str) -> None:
    if not expected_sha256 or set(expected_sha256) == {"0"}:
        raise ValueError(f"Laya artifact {name!r} has no pinned sha256; refuse install")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256.lower():
        raise ValueError(f"Laya artifact {name!r} sha256 mismatch")


def write_test_install(
    *,
    encoder_bytes: bytes | None = None,
    tokenizer_bytes: bytes | None = None,
) -> dict[str, Any]:
    """
    Install labeled local fixtures for tests. Production must supply real
    pinned checkpoints with matching sha256 entries in ARTIFACTS.
    """
    root = install_root()
    enc = encoder_bytes if encoder_bytes is not None else b"LAYA_TEST_ENCODER_V1"
    tok = tokenizer_bytes if tokenizer_bytes is not None else b'{"laya_test_tokenizer": true}\n'
    enc_hash = hashlib.sha256(enc).hexdigest()
    tok_hash = hashlib.sha256(tok).hexdigest()
    enc_path = root / "laya-encoder-multilingual.safetensors"
    tok_path = root / "laya-tokenizer.json"
    enc_path.write_bytes(enc)
    tok_path.write_bytes(tok)
    payload = {
        "provider": "laya",
        "license": LAYA_LICENSE,
        "source_url": LAYA_SOURCE_URL,
        "source_ref": "test-fixture",
        "fixture": True,
        "warm": True,
        "artifacts": [
            {
                "name": enc_path.name,
                "path": str(enc_path),
                "sha256": enc_hash,
                "role": "hot_checkpoint",
                "license": LAYA_LICENSE,
            },
            {
                "name": tok_path.name,
                "path": str(tok_path),
                "sha256": tok_hash,
                "role": "tokenizer",
                "license": LAYA_LICENSE,
            },
        ],
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


def verify_installed(*, allow_fixture: bool = True) -> tuple[bool, str, dict[str, Any] | None]:
    manifest = load_install_manifest()
    if not manifest:
        return False, "Laya not installed", None
    if manifest.get("license") != LAYA_LICENSE:
        return False, "Laya install missing Apache-2.0 provenance", manifest
    if manifest.get("fixture") and not allow_fixture:
        return False, "Laya fixture install is not production-ready", manifest
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False, "Laya install has no artifacts", manifest
    for row in artifacts:
        if not isinstance(row, dict):
            return False, "Corrupt Laya artifact row", manifest
        if not provenance_ok(row):
            return False, f"Artifact {row.get('name')} is not Apache-2.0", manifest
        path = Path(str(row.get("path") or ""))
        if not path.is_file():
            return False, f"Missing Laya artifact file {row.get('name')}", manifest
        expected = str(row.get("sha256") or "")
        if not expected:
            return False, f"Laya artifact {row.get('name')} missing sha256", manifest
        actual = sha256_file(path)
        if actual != expected.lower():
            return False, f"Laya artifact {row.get('name')} hash mismatch", manifest
    return True, "", manifest


def clear_install() -> None:
    root = install_root()
    manifest = manifest_path()
    if manifest.is_file():
        manifest.unlink()
    for path in root.glob("*"):
        if path.is_file():
            path.unlink()


def repo_pin_document_path() -> Path:
    """Checked-in pin document for auditors (not the live install)."""
    return repo_root() / "backend" / "app" / "decision" / "laya" / "PINNED.json"
