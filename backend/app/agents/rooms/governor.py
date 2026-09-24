"""Resource governor for Agent Rooms (RFC-0174).

Caps parallel local/cloud agents against CPU/GPU/VRAM/provider budgets and
respects cost + privacy modes. Soft-fail theater is forbidden: over-budget
acquisitions raise hard errors.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

CostMode = Literal["frugal", "balanced", "performance"]
PrivacyMode = Literal["local_only", "allow_cloud", "require_local"]
ProviderKind = Literal["local", "cloud"]

COST_MODES: tuple[str, ...] = ("frugal", "balanced", "performance")
PRIVACY_MODES: tuple[str, ...] = ("local_only", "allow_cloud", "require_local")

# Parallel agent caps by cost mode (defaults; may be lowered further by hardware).
_COST_PARALLEL_CAPS: dict[str, dict[str, int]] = {
    "frugal": {"local": 1, "cloud": 0},
    "balanced": {"local": 3, "cloud": 1},
    "performance": {"local": 6, "cloud": 3},
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ResourceBudget:
    max_parallel_local: int = 3
    max_parallel_cloud: int = 1
    cpu_slots: int = 4
    gpu_slots: int = 1
    vram_mib: int = 8192
    provider_calls: int = 32
    cost_mode: CostMode = "balanced"
    privacy_mode: PrivacyMode = "local_only"

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_parallel_local": self.max_parallel_local,
            "max_parallel_cloud": self.max_parallel_cloud,
            "cpu_slots": self.cpu_slots,
            "gpu_slots": self.gpu_slots,
            "vram_mib": self.vram_mib,
            "provider_calls": self.provider_calls,
            "cost_mode": self.cost_mode,
            "privacy_mode": self.privacy_mode,
        }


@dataclass(frozen=True)
class ResourceClaim:
    agent_id: str
    provider: ProviderKind
    cpu_slots: int = 1
    gpu_slots: int = 0
    vram_mib: int = 0
    provider_calls: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "provider": self.provider,
            "cpu_slots": self.cpu_slots,
            "gpu_slots": self.gpu_slots,
            "vram_mib": self.vram_mib,
            "provider_calls": self.provider_calls,
        }


@dataclass
class ResourceLease:
    id: str
    claim: ResourceClaim
    acquired_at: str
    released: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "claim": self.claim.as_dict(),
            "acquired_at": self.acquired_at,
            "released": self.released,
        }


class GovernorDenied(Exception):
    """Hard denial when a claim would exceed budget or privacy policy."""

    def __init__(self, reason: str, *, code: str = "governor_denied") -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


def build_budget(
    *,
    cost_mode: str = "balanced",
    privacy_mode: str = "local_only",
    cpu_slots: int | None = None,
    gpu_slots: int | None = None,
    vram_mib: int | None = None,
    provider_calls: int | None = None,
    max_parallel_local: int | None = None,
    max_parallel_cloud: int | None = None,
) -> ResourceBudget:
    cost = str(cost_mode or "balanced").strip().lower()
    if cost not in COST_MODES:
        raise ValueError(f"Invalid cost_mode: {cost_mode!r}")
    privacy = str(privacy_mode or "local_only").strip().lower()
    if privacy not in PRIVACY_MODES:
        raise ValueError(f"Invalid privacy_mode: {privacy_mode!r}")
    caps = _COST_PARALLEL_CAPS[cost]
    local_cap = caps["local"] if max_parallel_local is None else int(max_parallel_local)
    cloud_cap = caps["cloud"] if max_parallel_cloud is None else int(max_parallel_cloud)
    if privacy in {"local_only", "require_local"}:
        cloud_cap = 0
    return ResourceBudget(
        max_parallel_local=max(0, local_cap),
        max_parallel_cloud=max(0, cloud_cap),
        cpu_slots=max(0, int(cpu_slots if cpu_slots is not None else 4)),
        gpu_slots=max(0, int(gpu_slots if gpu_slots is not None else 1)),
        vram_mib=max(0, int(vram_mib if vram_mib is not None else 8192)),
        provider_calls=max(0, int(provider_calls if provider_calls is not None else 32)),
        cost_mode=cost,  # type: ignore[arg-type]
        privacy_mode=privacy,  # type: ignore[arg-type]
    )


class ResourceGovernor:
    """Tracks active leases and enforces hard caps for room parallelism."""

    def __init__(self, budget: ResourceBudget | None = None) -> None:
        self.budget = budget or build_budget()
        self._lock = threading.RLock()
        self._leases: dict[str, ResourceLease] = {}

    def _active(self) -> list[ResourceLease]:
        return [lease for lease in self._leases.values() if not lease.released]

    def usage(self) -> dict[str, Any]:
        with self._lock:
            active = self._active()
            local_n = sum(1 for l in active if l.claim.provider == "local")
            cloud_n = sum(1 for l in active if l.claim.provider == "cloud")
            return {
                "parallel_local": local_n,
                "parallel_cloud": cloud_n,
                "cpu_slots": sum(l.claim.cpu_slots for l in active),
                "gpu_slots": sum(l.claim.gpu_slots for l in active),
                "vram_mib": sum(l.claim.vram_mib for l in active),
                "provider_calls": sum(l.claim.provider_calls for l in active),
                "active_leases": len(active),
                "budget": self.budget.as_dict(),
            }

    def _check(self, claim: ResourceClaim, active: list[ResourceLease]) -> None:
        privacy = self.budget.privacy_mode
        if claim.provider == "cloud" and privacy in {"local_only", "require_local"}:
            raise GovernorDenied(
                f"cloud provider blocked by privacy_mode={privacy}",
                code="privacy_blocked",
            )
        local_n = sum(1 for l in active if l.claim.provider == "local")
        cloud_n = sum(1 for l in active if l.claim.provider == "cloud")
        if claim.provider == "local" and local_n + 1 > self.budget.max_parallel_local:
            raise GovernorDenied(
                f"local parallel cap exceeded ({self.budget.max_parallel_local})",
                code="parallel_local_cap",
            )
        if claim.provider == "cloud" and cloud_n + 1 > self.budget.max_parallel_cloud:
            raise GovernorDenied(
                f"cloud parallel cap exceeded ({self.budget.max_parallel_cloud})",
                code="parallel_cloud_cap",
            )
        cpu = sum(l.claim.cpu_slots for l in active) + claim.cpu_slots
        gpu = sum(l.claim.gpu_slots for l in active) + claim.gpu_slots
        vram = sum(l.claim.vram_mib for l in active) + claim.vram_mib
        calls = sum(l.claim.provider_calls for l in active) + claim.provider_calls
        if cpu > self.budget.cpu_slots:
            raise GovernorDenied("cpu_slots budget exceeded", code="cpu_cap")
        if gpu > self.budget.gpu_slots:
            raise GovernorDenied("gpu_slots budget exceeded", code="gpu_cap")
        if vram > self.budget.vram_mib:
            raise GovernorDenied("vram_mib budget exceeded", code="vram_cap")
        if calls > self.budget.provider_calls:
            raise GovernorDenied("provider_calls budget exceeded", code="provider_cap")

    def acquire(
        self,
        *,
        agent_id: str,
        provider: str = "local",
        cpu_slots: int = 1,
        gpu_slots: int = 0,
        vram_mib: int = 0,
        provider_calls: int = 1,
        lease_id: str | None = None,
    ) -> ResourceLease:
        aid = str(agent_id or "").strip().lower()
        if not aid:
            raise ValueError("agent_id is required")
        prov = str(provider or "local").strip().lower()
        if prov not in {"local", "cloud"}:
            raise ValueError(f"Invalid provider: {provider!r}")
        claim = ResourceClaim(
            agent_id=aid,
            provider=prov,  # type: ignore[arg-type]
            cpu_slots=max(0, int(cpu_slots)),
            gpu_slots=max(0, int(gpu_slots)),
            vram_mib=max(0, int(vram_mib)),
            provider_calls=max(0, int(provider_calls)),
        )
        with self._lock:
            active = self._active()
            self._check(claim, active)
            lease = ResourceLease(
                id=lease_id or str(uuid.uuid4()),
                claim=claim,
                acquired_at=_utcnow().astimezone(timezone.utc).isoformat(),
            )
            self._leases[lease.id] = lease
            return lease

    def release(self, lease_id: str) -> ResourceLease:
        with self._lock:
            lease = self._leases.get(lease_id)
            if lease is None:
                raise LookupError(f"lease not found: {lease_id}")
            lease.released = True
            return lease

    def concurrency_budget(self) -> int:
        """Max concurrent specialists the supervisor may run under current budget."""
        privacy = self.budget.privacy_mode
        if privacy in {"local_only", "require_local"}:
            return self.budget.max_parallel_local
        return self.budget.max_parallel_local + self.budget.max_parallel_cloud
