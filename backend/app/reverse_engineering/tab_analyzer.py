"""Profile `.tab` files from an FFS dump for the RFC-0208 `.tab` encryption review.

The profiler is fed by the FFS ingest stream (``ffs_ingest``): every `.tab` member
is profiled in the same read-only pass that hashes it, so a multi-GB archive is never
read twice and no member is extracted to disk. Per file it records the Shannon
entropy (bits per byte, 0.0-8.0) and the leading header bytes; ``summarize`` turns
the per-file profiles into the citable evidence payload (entropy classes and shared
header prefixes) that the encryption writeup builds on.
"""

from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np

CHUNK_SIZE = 1024 * 1024
HEADER_BYTES = 16
TAB_SUFFIX = ".tab"

# Entropy classes (bits per byte). Ciphertext and good compression sit near 8.0;
# structured binary tables are far lower. The bands are descriptive, not a verdict:
# high entropy alone cannot distinguish encryption from compression.
HIGH_ENTROPY = 7.9
MEDIUM_ENTROPY = 6.0
# Header prefix lengths compared across files (magic/version fields).
PREFIX_LENGTHS = (4, 8)
MAX_PREFIX_GROUPS = 20


def is_tab_path(path: str) -> bool:
    """True when ``path`` names a `.tab` file (case-insensitive)."""
    return path.lower().endswith(TAB_SUFFIX)


def shannon_entropy(counts: Iterable[int], total: int) -> float:
    """Shannon entropy in bits per byte for a 256-bin byte histogram."""
    if total <= 0:
        return 0.0
    entropy = 0.0
    for count in counts:
        if count:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


class TabProfiler:
    """Streaming accumulator: feed chunks with ``update``; read ``result()`` when done."""

    __slots__ = ("_counts", "_total", "_header")

    def __init__(self) -> None:
        self._counts = np.zeros(256, dtype=np.int64)
        self._total = 0
        self._header = bytearray()

    def update(self, chunk: bytes) -> None:
        if not chunk:
            return
        if len(self._header) < HEADER_BYTES:
            self._header.extend(chunk[: HEADER_BYTES - len(self._header)])
        # ~1 GB/s on VRPC versus ~16 MB/s for 256 bytes.count passes: GB-sized .tab sets must
        # not slow the ingest below disk speed.
        self._counts += np.bincount(np.frombuffer(chunk, dtype=np.uint8), minlength=256)
        self._total += len(chunk)

    def result(self) -> dict[str, Any]:
        return {
            "size": self._total,
            "entropy": round(shannon_entropy(self._counts.tolist(), self._total), 4),
            "header_hex": bytes(self._header).hex(),
        }


def profile_file(path: Path) -> dict[str, Any]:
    """Stream one local file read-only and return its size, entropy and header bytes."""
    profiler = TabProfiler()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            profiler.update(chunk)
    return profiler.result()


def entropy_class(entropy: float, size: int) -> str:
    if size == 0:
        return "empty"
    if entropy >= HIGH_ENTROPY:
        return "high"
    if entropy >= MEDIUM_ENTROPY:
        return "medium"
    return "low"


def summarize(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-file profiles (``path``, ``bytes``, ``entropy``, ``header_hex``).

    Returns entropy-class counts, min/max/mean entropy and the most common header
    prefixes, so a reviewer can see whether `.tab` files share a container format.
    """
    classes: Counter[str] = Counter()
    entropies: list[float] = []
    prefixes: dict[int, Counter[str]] = {n: Counter() for n in PREFIX_LENGTHS}
    total_bytes = 0
    for item in profiles:
        size = int(item.get("bytes") or 0)
        entropy = float(item.get("entropy") or 0.0)
        total_bytes += size
        classes[entropy_class(entropy, size)] += 1
        if size:
            entropies.append(entropy)
        header = str(item.get("header_hex") or "")
        for n in PREFIX_LENGTHS:
            if len(header) >= 2 * n:
                prefixes[n][header[: 2 * n]] += 1
    return {
        "file_count": len(profiles),
        "total_bytes": total_bytes,
        "entropy_classes": {name: classes.get(name, 0) for name in ("high", "medium", "low", "empty")},
        "entropy_bands": {"high": f">= {HIGH_ENTROPY}", "medium": f">= {MEDIUM_ENTROPY}", "low": f"< {MEDIUM_ENTROPY}"},
        "entropy_min": round(min(entropies), 4) if entropies else None,
        "entropy_max": round(max(entropies), 4) if entropies else None,
        "entropy_mean": round(sum(entropies) / len(entropies), 4) if entropies else None,
        "common_header_prefixes": {
            f"{n}_bytes": [
                {"prefix_hex": prefix, "files": count}
                for prefix, count in prefixes[n].most_common(MAX_PREFIX_GROUPS)
            ]
            for n in PREFIX_LENGTHS
        },
    }