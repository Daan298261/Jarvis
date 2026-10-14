"""Locate `.tab` files in an ingested filesystem and profile their bytes.

Supports the RFC-0208 `.tab` encryption writeup: per-file Shannon entropy
(bits per byte, 0.0-8.0) and leading header bytes, computed in a single
streaming pass so multi-GB files never load fully into memory.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

CHUNK_SIZE = 1024 * 1024
HEADER_BYTES = 16


def shannon_entropy(counts: list[int], total: int) -> float:
    """Shannon entropy in bits per byte for a 256-bin byte histogram."""
    if total <= 0:
        return 0.0
    entropy = 0.0
    for count in counts:
        if count:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def profile_file(path: Path) -> dict[str, Any]:
    """Stream one file and return its size, entropy and header bytes."""
    counts = [0] * 256
    total = 0
    header = b""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            if len(header) < HEADER_BYTES:
                header += chunk[: HEADER_BYTES - len(header)]
            for value, n in enumerate(_histogram(chunk)):
                counts[value] += n
            total += len(chunk)
    return {
        "size": total,
        "entropy": round(shannon_entropy(counts, total), 4),
        "header_hex": header.hex(),
    }


def _histogram(chunk: bytes) -> list[int]:
    counts = [0] * 256
    for value in range(256):
        counts[value] = chunk.count(value)
    return counts


def analyze_tab_files(root: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Profile every `.tab` file under ``root`` (case-insensitive), sorted by path.

    Unreadable files are reported with an ``error`` field instead of being
    silently dropped, so the evidence trail stays complete.
    """
    root_path = Path(root)
    results: list[dict[str, Any]] = []
    for dirpath, _dirnames, filenames in os.walk(root_path):
        for filename in filenames:
            if not filename.lower().endswith(".tab"):
                continue
            path = Path(dirpath) / filename
            relative = path.relative_to(root_path).as_posix()
            try:
                entry = {"relative_path": relative, **profile_file(path)}
            except OSError as exc:
                entry = {"relative_path": relative, "error": str(exc)}
            results.append(entry)
    results.sort(key=lambda item: item["relative_path"])
    return results
