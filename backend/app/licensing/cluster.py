from __future__ import annotations

import hashlib
import platform
import socket
import uuid
from pathlib import Path

from ..config import data_dir

CLUSTER_ID_FILE = "cluster_id"


def licensing_root() -> Path:
    path = data_dir() / "licensing"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cluster_id_path() -> Path:
    return licensing_root() / CLUSTER_ID_FILE


def _derive_cluster_fingerprint() -> str:
    """Stable cluster fingerprint from host characteristics (no network)."""
    parts = [
        platform.node(),
        platform.machine(),
        platform.system(),
        socket.gethostname(),
    ]
    try:
        parts.append(str(uuid.getnode()))
    except Exception:
        pass
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"jarvis-cluster-{digest[:32]}"


def get_cluster_id() -> str:
    path = _cluster_id_path()
    if path.exists():
        stored = path.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    return ensure_cluster_identity()


def ensure_cluster_identity() -> str:
    path = _cluster_id_path()
    if path.exists():
        stored = path.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    cluster_id = _derive_cluster_fingerprint()
    path.write_text(cluster_id + "\n", encoding="utf-8")
    return cluster_id
