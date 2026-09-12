"""Discover a locally installed Qwen3.8-9B uncensored GGUF (RFC-0078)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..config import models_dir

QWEN38_9B_RE = re.compile(
    r"qwen[\s_\-]*3(?:[.\-_]|m)?8[\s_\-]*9b",
    re.IGNORECASE,
)
QWEN38_27B_RE = re.compile(
    r"qwen[\s_\-]*3(?:[.\-_]|m)?8[\s_\-]*27b",
    re.IGNORECASE,
)
UNCENSORED_RE = re.compile(
    r"uncensored|abliterat|defiant|heretic|unfiltered|norefusal|no[\-_]?refusal",
    re.IGNORECASE,
)
MMPROJ_RE = re.compile(r"mmproj", re.IGNORECASE)
QUANT_RANK = ("Q8_0", "Q6_K", "Q5_K_M", "Q5_K", "Q4_K_M", "Q4_K_S", "Q4_K", "Q4", "Q3_K_S", "Q3_K_M", "Q3")
HERETIC_27B_FILENAME = "RVN-Q3_K_S-multilingual.gguf"

EVERYDAY_PROFILE_NAMES = frozenset({"balanced", "fast", "quality", "qwen38_9b"})
PINNED_PROFILE_NAMES = frozenset(
    {"expert", "ornith_9b", "ornith_35b", "bootstrap"}
)


@dataclass(frozen=True)
class DiscoveredQwen38:
    path: Path
    filename: str
    uncensored: bool
    quantization: str


def _quant_from_name(name: str) -> str:
    match = re.search(r"(Q\d+(?:_K(?:_[SM])?)?|IQ\d+(?:_XS)?)", name, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _quant_rank(quant: str) -> int:
    try:
        return QUANT_RANK.index(quant)
    except ValueError:
        return len(QUANT_RANK)


def is_qwen38_9b_filename(name: str) -> bool:
    if MMPROJ_RE.search(name):
        return False
    if not name.lower().endswith(".gguf"):
        return False
    return bool(QWEN38_9B_RE.search(name))


def is_qwen38_27b_heretic_path(path: Path) -> bool:
    """Recognize the RVN 27B GGUF even though its filename omits Qwen/27B."""
    if MMPROJ_RE.search(path.name) or path.suffix.lower() != ".gguf":
        return False
    marker = str(path).replace("\\", "/")
    return bool(QWEN38_27B_RE.search(marker) and UNCENSORED_RE.search(marker))


def is_uncensored_filename(name: str) -> bool:
    return bool(UNCENSORED_RE.search(name))


def _iter_ggufs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    try:
        return [path for path in root.rglob("*.gguf") if path.is_file()]
    except OSError:
        return []


def _lmstudio_root() -> Path:
    from .lmstudio_catalog import resolve_models_root

    return resolve_models_root()


def discover_qwen38_9b_candidates(extra_roots: list[Path] | None = None) -> list[DiscoveredQwen38]:
    roots = [models_dir(), _lmstudio_root()]
    if extra_roots:
        roots.extend(extra_roots)
    seen: set[str] = set()
    found: list[DiscoveredQwen38] = []
    for root in roots:
        for path in _iter_ggufs(root):
            marker = str(path.resolve()) if path.exists() else str(path)
            if marker in seen:
                continue
            if not is_qwen38_9b_filename(path.name):
                continue
            seen.add(marker)
            found.append(
                DiscoveredQwen38(
                    path=path,
                    filename=path.name,
                    uncensored=is_uncensored_filename(path.name),
                    quantization=_quant_from_name(path.name),
                )
            )
    found.sort(key=lambda item: (not item.uncensored, _quant_rank(item.quantization), item.filename.lower()))
    return found


def discover_qwen38_9b_uncensored(extra_roots: list[Path] | None = None) -> DiscoveredQwen38 | None:
    """Best local Qwen3.8-9B: uncensored-tagged first, else any 3.8-9B GGUF."""
    candidates = discover_qwen38_9b_candidates(extra_roots)
    if not candidates:
        return None
    preferred = [item for item in candidates if item.uncensored]
    return (preferred or candidates)[0]


def discover_qwen38_27b_heretic(extra_roots: list[Path] | None = None) -> DiscoveredQwen38 | None:
    """Find the requested internal Qwen3.8 27B Heretic/RVN quantization."""
    roots = [models_dir(), _lmstudio_root()]
    if extra_roots:
        roots.extend(extra_roots)
    found: list[DiscoveredQwen38] = []
    seen: set[str] = set()
    for root in roots:
        for path in _iter_ggufs(root):
            if not is_qwen38_27b_heretic_path(path):
                continue
            marker = str(path.resolve()) if path.exists() else str(path)
            if marker in seen:
                continue
            seen.add(marker)
            found.append(
                DiscoveredQwen38(
                    path=path,
                    filename=path.name,
                    uncensored=True,
                    quantization=_quant_from_name(path.name),
                )
            )
    found.sort(key=lambda item: (item.filename.lower() != HERETIC_27B_FILENAME.lower(), _quant_rank(item.quantization), item.filename.lower()))
    return found[0] if found else None


def should_prefer_qwen38_default(current_profile: str) -> bool:
    name = (current_profile or "balanced").strip().lower()
    if name in PINNED_PROFILE_NAMES:
        return False
    if name.startswith("lm-") or name.startswith("runtime"):
        return False
    return name in EVERYDAY_PROFILE_NAMES or not name
