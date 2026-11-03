"""Registry of the models ANZU itself loaded, with each model's own last use.

Idle unload and the HUD Unload button act only on models listed here. A model ANZU
did not load (for example Black Grid's ``bgm-ingest-9b`` in Ollama or LM Studio)
is never unloaded and never has a keep-alive set on it, whatever Keep warm says.
Entries are keyed by backend and model id; ids are compared case-insensitively
and Ollama's implicit ``:latest`` tag is ignored.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

OLLAMA = "ollama"
LMSTUDIO = "lmstudio"
LLAMA_SERVER = "llama-server"
WORKER = "worker"  # ANZU's managed llama-server for the main model
FRONT = "front"    # ANZU's front-responder llama-server


def canonical(model: str) -> str:
    name = (model or "").strip().lower()
    return name[:-7] if name.endswith(":latest") else name


@dataclass
class Entry:
    backend: str
    model: str
    aliases: set[str] = field(default_factory=set)
    last_use: float = 0.0
    primary: bool = False  # used by every turn (the main model and the front responder)

    @property
    def key(self) -> tuple[str, str]:
        return (self.backend, canonical(self.model))

    def ids(self) -> set[str]:
        return {canonical(self.model), *(canonical(alias) for alias in self.aliases)}


class LoadedModels:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[tuple[str, str], Entry] = {}

    def record(self, backend: str, model: str, *, aliases: Iterable[str] = (), primary: bool = False) -> Entry:
        """ANZU loaded (or attached to) this model just now."""
        probe = Entry(backend, model, set(aliases), self._clock(), primary)
        entry = self._entries.get(probe.key)
        if entry is None:
            self._entries[probe.key] = entry = probe
        else:
            entry.aliases |= probe.aliases
            entry.last_use = probe.last_use
            entry.primary = entry.primary or primary
        return entry

    def match(self, backend: str, ids: Iterable[str]) -> Entry | None:
        wanted = {canonical(value) for value in ids if value}
        return next((e for e in self._entries.values() if e.backend == backend and e.ids() & wanted), None)

    def touch(self, backend: str, model: str) -> None:
        entry = self.match(backend, [model])
        if entry is not None:
            entry.last_use = self._clock()

    def defer(self, entry: Entry) -> None:
        """A release failed: the next attempt waits a full idle window."""
        entry.last_use = self._clock()

    def forget(self, entry: Entry) -> None:
        self._entries.pop(entry.key, None)

    def entries(self) -> list[Entry]:
        return list(self._entries.values())

    def idle_for(self, entry: Entry) -> float:
        return max(0.0, self._clock() - entry.last_use)

    def clear(self) -> None:
        self._entries.clear()


LOADED = LoadedModels()
