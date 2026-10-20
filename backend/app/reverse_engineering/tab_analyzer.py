"""Profile `.tab` files from an FFS dump for the RFC-0208 `.tab` encryption review.

The profiler is fed by the FFS ingest stream (``ffs_ingest``): every `.tab` member
is profiled in the same read-only pass that hashes it, so a multi-GB archive is never
read twice and no member is extracted to disk. Per file it records the Shannon
entropy (bits per byte, 0.0-8.0), the leading header bytes, the most common byte and,
when the bytes look like single-byte-XOR text, the candidate key. ``summarize`` turns
the per-file profiles into the citable evidence payload (entropy classes, shared
header prefixes and the ``AT\\x00\\x02`` container census) that the encryption
writeup (``docs/reverse-engineering/autel-tab-container.md``) builds on.

``parse_tab_header`` decodes the Autel ``AT\\x00\\x02`` container header. Field
names follow the writeup: they are observations from the 2026-10 Autel MaxiSys dump,
not vendor documentation, so every parsed header keeps its raw bytes and anything that
deviates from the observed layout is reported in ``anomalies`` instead of being
silently accepted.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from typing import Any, Iterable

import numpy as np

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

# --- Autel AT\x00\x02 container (see docs/reverse-engineering/autel-tab-container.md) ---
AT2_MAGIC = b"AT\x00\x02"
AT2_CONTAINER = "autel-at2"
# Bytes captured per file so the full transformed-body header (64 bytes) can be parsed.
CONTAINER_HEADER_BYTES = 64
AT2_PLAIN_HEADER_LEN = 16  # byte 7 == 0: plain records start at offset 16
AT2_TRANSFORMED_HEADER_LEN = 64  # byte 7 == 1: descriptor at 16..22, zero padding to 64
AT2_DESCRIPTOR = bytes.fromhex("30004558")  # "0\x00EX" at offset 16 in every transformed file seen
AT2_DESCRIPTOR_TAIL = bytes.fromhex("0001")  # offsets 21-22
BODY_TRANSFORM = {0: "plain", 1: "keyed"}
MAX_CENSUS_GROUPS = 64

# Single-byte XOR text heuristic. Several vendor `.tab` families (TATA, GM, Fiat, Mazda
# tool_j*) are tab-separated text XORed with one byte. Every candidate key is scored on the
# streaming histogram alone (position-independent, so no body is kept): the share of bytes
# that decode to likely text, with digits and whitespace as a tie-breaker (XOR 0x20 only
# swaps letter case, so letters alone cannot pick between k and k ^ 0x20).
XOR_TEXT_MIN_SHARE = 0.9
XOR_TEXT_MIN_SYMBOLS = 8
_TEXT_LIKELY = np.zeros(256, dtype=bool)
for _byte in b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz \t\r\n,.:;_-/()$%#'\"=+*&[]<>?!@|":
    _TEXT_LIKELY[_byte] = True
_DIGIT_OR_SPACE = np.zeros(256, dtype=bool)
for _byte in b"0123456789 \t\r\n":
    _DIGIT_OR_SPACE[_byte] = True
del _byte
_XOR_TABLE = np.arange(256)[:, None] ^ np.arange(256)[None, :]  # [key, byte] -> byte ^ key
_TEXT_UNDER_KEY = _TEXT_LIKELY[_XOR_TABLE].astype(np.float64)
_DIGIT_SPACE_UNDER_KEY = _DIGIT_OR_SPACE[_XOR_TABLE].astype(np.float64)


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


def xor_text_key(counts: np.ndarray, total: int) -> int | None:
    """Return the single-byte XOR key under which the histogram decodes to text, else None.

    ``None`` for empty or near-constant data, for data that is already text (key 0) and
    when no key reaches ``XOR_TEXT_MIN_SHARE`` likely-text bytes.
    """
    if total <= 0 or int(np.count_nonzero(counts)) < XOR_TEXT_MIN_SYMBOLS:
        return None
    hist = counts.astype(np.float64)
    text_share = _TEXT_UNDER_KEY @ hist / total
    score = text_share + 1e-3 * (_DIGIT_SPACE_UNDER_KEY @ hist / total)
    key = int(score.argmax())
    if key == 0 or text_share[key] < XOR_TEXT_MIN_SHARE:
        return None
    return key


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
        if len(self._header) < CONTAINER_HEADER_BYTES:
            self._header.extend(chunk[: CONTAINER_HEADER_BYTES - len(self._header)])
        # ~1 GB/s on VRPC versus ~16 MB/s for 256 bytes.count passes: GB-sized .tab sets must
        # not slow the ingest below disk speed.
        self._counts += np.bincount(np.frombuffer(chunk, dtype=np.uint8), minlength=256)
        self._total += len(chunk)

    def result(self) -> dict[str, Any]:
        header = bytes(self._header)
        is_at2 = header.startswith(AT2_MAGIC)
        return {
            "size": self._total,
            "entropy": round(shannon_entropy(self._counts.tolist(), self._total), 4),
            "header_hex": header[:HEADER_BYTES].hex(),
            "container_hex": header.hex(),
            "top_byte": int(self._counts.argmax()) if self._total else None,
            # AT2 bodies use a keyed transform that is not single-byte XOR; only test the rest.
            "xor_key": None if is_at2 else xor_text_key(self._counts, self._total),
        }


def entropy_class(entropy: float, size: int) -> str:
    if size == 0:
        return "empty"
    if entropy >= HIGH_ENTROPY:
        return "high"
    if entropy >= MEDIUM_ENTROPY:
        return "medium"
    return "low"


def _tag(raw: bytes) -> str | None:
    if raw == b"\x00\x00":
        return None
    if all(0x20 < b < 0x7F for b in raw):
        return raw.decode("ascii")
    return None


def parse_tab_header(raw: bytes) -> dict[str, Any]:
    """Parse the leading bytes of a `.tab` file (pass at least 64 for a full parse).

    Returns ``container`` = ``"autel-at2"`` with the decoded fields, or ``"unknown"``
    (no AT\\x00\\x02 magic), ``"empty"`` or ``"truncated"`` (magic but fewer than 16
    bytes). Fields that need bytes beyond ``raw`` are ``None``; deviations from the
    observed layout are listed in ``anomalies``.
    """
    if not raw:
        return {"container": "empty"}
    if not raw.startswith(AT2_MAGIC):
        return {"container": "unknown", "magic_hex": raw[:4].hex()}
    if len(raw) < AT2_PLAIN_HEADER_LEN:
        return {"container": "truncated", "header_hex": raw.hex()}
    anomalies: list[str] = []
    transform_byte = raw[7]
    transform = BODY_TRANSFORM.get(transform_byte)
    if transform is None:
        anomalies.append(f"unrecognised body-transform byte 0x{transform_byte:02x} at offset 7")
    parsed: dict[str, Any] = {
        "container": AT2_CONTAINER,
        "tag": _tag(raw[4:6]),
        "tag_hex": raw[4:6].hex(),
        "table_type": raw[6],
        "body_transform": transform,
        "format_rev": int.from_bytes(raw[8:10], "big"),
        "flags": raw[10],
        "field_11": raw[11],
        "record_count": int.from_bytes(raw[12:16], "big"),
        "header_len": AT2_TRANSFORMED_HEADER_LEN if transform_byte == 1 else AT2_PLAIN_HEADER_LEN,
        "key_id": None,
        "reserved_zero": None,
        "anomalies": anomalies,
    }
    if raw[4:6] != b"\x00\x00" and parsed["tag"] is None:
        anomalies.append(f"non-ASCII tag bytes {raw[4:6].hex()} at offsets 4-5")
    if transform_byte == 1:
        if len(raw) >= 23:
            if raw[16:20] != AT2_DESCRIPTOR:
                anomalies.append(f"descriptor {raw[16:20].hex()} != {AT2_DESCRIPTOR.hex()} at offset 16")
            if raw[21:23] != AT2_DESCRIPTOR_TAIL:
                anomalies.append(f"descriptor tail {raw[21:23].hex()} != {AT2_DESCRIPTOR_TAIL.hex()} at offset 21")
            parsed["key_id"] = raw[20]
        if len(raw) >= AT2_TRANSFORMED_HEADER_LEN:
            parsed["reserved_zero"] = not any(raw[23:AT2_TRANSFORMED_HEADER_LEN])
            if not parsed["reserved_zero"]:
                anomalies.append("non-zero bytes in reserved range 23-63")
    return parsed


def _container_census(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    containers: Counter[str] = Counter()
    table_types: Counter[int] = Counter()
    transforms: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    key_ids: Counter[int] = Counter()
    key_top_bytes: dict[int, Counter[int]] = defaultdict(Counter)
    xor_keys: Counter[int] = Counter()
    anomalous = 0
    records = 0
    for item in profiles:
        header = item.get("container")
        if not isinstance(header, dict):
            raw = str(item.get("container_hex") or item.get("header_hex") or "")
            try:
                header = parse_tab_header(bytes.fromhex(raw))
            except ValueError:
                header = {"container": "unknown"}
        kind = header.get("container", "unknown")
        containers[kind] += 1
        if item.get("xor_key") is not None:
            xor_keys[int(item["xor_key"])] += 1
        if kind != AT2_CONTAINER:
            continue
        table_types[int(header["table_type"])] += 1
        transforms[str(header.get("body_transform"))] += 1
        tags[header.get("tag") or "-"] += 1
        records += int(header.get("record_count") or 0)
        if header.get("anomalies"):
            anomalous += 1
        if header.get("key_id") is not None:
            key = int(header["key_id"])
            key_ids[key] += 1
            if item.get("top_byte") is not None:
                key_top_bytes[key][int(item["top_byte"])] += 1
    return {
        "containers": dict(containers),
        "at2": {
            "files": containers.get(AT2_CONTAINER, 0),
            "body_transform": dict(transforms),
            "table_types": [{"table_type": t, "files": n} for t, n in sorted(table_types.items())],
            "tags": [{"tag": t, "files": n} for t, n in tags.most_common(MAX_CENSUS_GROUPS)],
            "record_count_total": records,
            "anomalous_headers": anomalous,
            # key_id vs the body's most common byte: one dominant top byte per key id is the
            # signature of a keyed, position-independent byte transform (see the writeup).
            "key_ids": [
                {
                    "key_id": key,
                    "files": n,
                    "dominant_top_byte": key_top_bytes[key].most_common(1)[0][0] if key_top_bytes[key] else None,
                    "dominant_top_byte_files": key_top_bytes[key].most_common(1)[0][1] if key_top_bytes[key] else 0,
                }
                for key, n in key_ids.most_common(MAX_CENSUS_GROUPS)
            ],
        },
        "single_byte_xor_text": {
            "files": sum(xor_keys.values()),
            "keys": [{"xor_key": k, "files": n} for k, n in xor_keys.most_common(MAX_CENSUS_GROUPS)],
        },
    }


def summarize(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-file profiles (``path``, ``bytes``, ``entropy``, ``header_hex`` and,
    when present, ``container``/``container_hex``, ``top_byte`` and ``xor_key``).

    Returns entropy-class counts, min/max/mean entropy, the most common header
    prefixes and the container census, so a reviewer can see which `.tab` files share
    the Autel container, which key ids they use and which are XOR-obfuscated text.
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
        "container_census": _container_census(profiles),
    }
