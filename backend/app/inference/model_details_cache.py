"""Optional model-page catalogs/metrics cannot delay health/status reads."""
from __future__ import annotations

import asyncio
import copy
import time


class ModelDetailsCache:
    def __init__(self):
        self.value: dict = {}
        self.updated = 0.0
        self.error = ""
        self.task: asyncio.Task | None = None

    async def collect(self) -> dict:
        from .profiles import available_profiles
        from .benchmarks import list_benchmarks, task_outcome_stats
        from .harness import load_last_report

        profiles = await asyncio.to_thread(available_profiles)
        return {
            "profiles": [{"name": p.name, "label": p.label, "quant": p.quant,
                          "thinking": p.thinking, "context_size": p.context_size,
                          "description": p.description, "escalation_only": p.name == "expert"}
                         for p in profiles],
            "outcomes": await task_outcome_stats(),
            "benchmarks": await list_benchmarks(limit=12),
            "harness": await asyncio.to_thread(load_last_report),
        }

    def read(self) -> dict:
        if (not self.updated or time.monotonic() - self.updated > 30) and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._refresh())
        result = copy.deepcopy(self.value)
        result["details_cache"] = {"pending": bool(self.task and not self.task.done()),
                                   "available": bool(self.value), "error": self.error,
                                   "age_seconds": time.monotonic() - self.updated if self.updated else None}
        return result

    async def _refresh(self):
        try:
            self.value = await self.collect()
            self.error = ""
        except Exception as exc:
            self.error = str(exc)[:200]
        finally:
            self.updated = time.monotonic()

    def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = None


MODEL_DETAILS = ModelDetailsCache()
