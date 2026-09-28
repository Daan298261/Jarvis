"""Input sizing and deterministic extractive compression for long text.

Used by the Reflex projection (so Laya/Jev see head, tail and salient spans of a
long paste instead of only its first characters) and by owner-chat intake
(compress vs sequential planning). Pure functions: same input -> same output,
which keeps Reflex cache keys stable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

# Conservative default when no tokenizer is available (overestimates tokens, so
# budgets err on the safe side).
DEFAULT_CHARS_PER_TOKEN = 3.0
OMISSION_MARKER = " […] "

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|\n{2,}|\n(?=\s*(?:[-*•]|\d+[.)])\s)")
_WORD = re.compile(r"[^\W_]{3,}", re.UNICODE)

TokenCounter = Callable[[str], int]


def estimate_tokens(text: str, *, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / max(0.5, chars_per_token)) + 1)


def count_tokens(text: str, counter: TokenCounter | None = None) -> int:
    """Exact count when a tokenizer counter is supplied, otherwise the conservative estimate."""
    if not text:
        return 0
    if counter is not None:
        try:
            return int(counter(text))
        except Exception:  # noqa: BLE001 — tokenizer failure must not break sizing
            pass
    return estimate_tokens(text)


def split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text or "")]
    return [part for part in parts if part]


def _words(text: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(text or "")}


@dataclass(frozen=True)
class CompressionResult:
    text: str
    original_chars: int
    kept_chars: int
    kept_sentences: int
    total_sentences: int

    @property
    def compressed(self) -> bool:
        return self.kept_chars < self.original_chars


def compress_text(text: str, max_chars: int, *, focus: str = "") -> CompressionResult:
    """Fit ``text`` into ``max_chars`` keeping head, tail and the most salient sentences.

    Head and tail are kept because owners usually state the ask at the start or the
    end of a long paste. Middle sentences are ranked by overlap with ``focus`` (the
    question or the closing instruction) plus overlap with the head/tail, and are
    emitted in original order with omission markers where spans were dropped.
    """
    source = (text or "").strip()
    limit = max(16, int(max_chars))
    if len(source) <= limit:
        return CompressionResult(source, len(source), len(source), 1, 1)

    sentences = split_sentences(source)
    if len(sentences) <= 2:
        half = max(8, (limit - len(OMISSION_MARKER)) // 2)
        head, tail = source[:half].rstrip(), source[-half:].lstrip()
        joined = f"{head}{OMISSION_MARKER}{tail}"[:limit]
        return CompressionResult(joined, len(source), len(joined), len(sentences), len(sentences))

    first, last = sentences[0], sentences[-1]
    anchor_words = _words(focus) | _words(first) | _words(last)
    ranked: list[tuple[float, int]] = []
    for index, sentence in enumerate(sentences[1:-1], start=1):
        words = _words(sentence)
        overlap = len(words & anchor_words) / max(1, len(words)) if words else 0.0
        # Slight preference for spans near the ends; stable tie-break on position.
        edge = 1.0 - min(index, len(sentences) - 1 - index) / max(1, len(sentences))
        ranked.append((overlap * 2.0 + edge * 0.25, index))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    def _cap(sentence: str, room: int) -> str:
        return sentence if len(sentence) <= room else sentence[: max(0, room - 1)].rstrip() + "…"

    budget = limit
    first_text = _cap(first, max(16, limit // 3))
    last_text = _cap(last, max(16, limit // 3))
    budget -= len(first_text) + len(last_text) + 2 * len(OMISSION_MARKER)
    chosen: set[int] = set()
    for _score, index in ranked:
        cost = len(sentences[index]) + 1
        if cost > budget:
            continue
        chosen.add(index)
        budget -= cost

    pieces: list[str] = [first_text]
    previous = 0
    for index in sorted(chosen):
        pieces.append(OMISSION_MARKER.strip() if index - previous > 1 else "")
        pieces.append(sentences[index])
        previous = index
    if len(sentences) - 1 - previous > 1:
        pieces.append(OMISSION_MARKER.strip())
    pieces.append(last_text)
    joined = " ".join(piece for piece in pieces if piece)
    if len(joined) > limit:
        joined = joined[: limit - 1].rstrip() + "…"
    kept = 2 + len(chosen)
    return CompressionResult(joined, len(source), len(joined), kept, len(sentences))


def split_segments(text: str, max_chars: int) -> list[str]:
    """Split on paragraph, then sentence boundaries into segments of at most ``max_chars``."""
    source = (text or "").strip()
    limit = max(64, int(max_chars))
    if len(source) <= limit:
        return [source] if source else []
    segments: list[str] = []
    current = ""
    for sentence in split_sentences(source):
        while len(sentence) > limit:
            if current:
                segments.append(current)
                current = ""
            segments.append(sentence[:limit])
            sentence = sentence[limit:]
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > limit:
            segments.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        segments.append(current)
    return [segment for segment in segments if segment]
