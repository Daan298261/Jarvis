"""RFC-0123: companion anti-impersonation signals, cooldown, and owner events."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Literal

from ..events import BUS
from .store import database, delete, put

log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 600
TRIP_THRESHOLD = 0.5

EndpointClass = Literal["lan", "forwarded", "relay", "unknown"]

_OWNER_SENTENCE = (
    "Someone tried to reach Jarvis as your phone without valid pairing keys."
)


class CompanionSecurityGuard:
    def __init__(self) -> None:
        self._cooldown_until = 0.0
        self._connectivity: Any | None = None

    def bind_connectivity(self, connectivity: Any) -> None:
        self._connectivity = connectivity

    def cooldown_active(self) -> bool:
        return time.time() < self._cooldown_until

    def cooldown_remaining_seconds(self) -> int:
        if not self.cooldown_active():
            return 0
        return max(0, int(self._cooldown_until - time.time()))

    def snapshot(self) -> dict[str, Any]:
        return {
            "cooldown_active": self.cooldown_active(),
            "cooldown_remaining_seconds": self.cooldown_remaining_seconds(),
        }

    def _persist_audit(self, payload: dict[str, Any]) -> None:
        with database() as db:
            put(
                db,
                "security_audit",
                payload["id"],
                {**payload, "created_at": time.time()},
            )

    async def _emit_hack_attempt(self, payload: dict[str, Any]) -> None:
        detail = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        await BUS.publish_ephemeral(
            "companion-security",
            "detected-hack-attempt",
            "Companion security alert",
            detail,
            stage="companion",
        )
        self._persist_audit(payload)

    def _endpoint_class(self, client_host: str) -> EndpointClass:
        if not client_host or client_host in {"127.0.0.1", "::1", "localhost"}:
            return "lan"
        try:
            import ipaddress

            address = ipaddress.ip_address(client_host)
            if address.is_private or address.is_loopback:
                return "lan"
        except ValueError:
            pass
        return "forwarded"

    async def consider(
        self,
        signal: str,
        probability: float,
        *,
        device_id: str = "",
        client_host: str = "",
        endpoint_class: EndpointClass | None = None,
    ) -> bool:
        """Record a signal; trip cooldown when probability >= threshold. Returns True if tripped."""
        probability = max(0.0, min(1.0, float(probability)))
        if probability < TRIP_THRESHOLD:
            return False
        endpoint = endpoint_class or self._endpoint_class(client_host)
        event_id = str(uuid.uuid4())
        payload = {
            "id": event_id,
            "kind": "detected-hack-attempt",
            "probability": probability,
            "signal": signal,
            "device_id": device_id or None,
            "endpoint_class": endpoint,
            "owner_message": _OWNER_SENTENCE,
        }
        log.warning(
            "Companion security trip signal=%s probability=%.2f device=%s endpoint=%s",
            signal,
            probability,
            device_id or "unknown",
            endpoint,
        )
        if device_id:
            with database() as db:
                delete(db, "session", device_id)
        await self._emit_hack_attempt(payload)
        self._cooldown_until = time.time() + COOLDOWN_SECONDS
        if self._connectivity is not None:
            await self._connectivity.on_security_cooldown()
        return True

    async def report_pin_mismatch(self, device_id: str, client_host: str = "") -> None:
        await self.consider(
            "tls_pin_mismatch",
            0.95,
            device_id=device_id,
            client_host=client_host,
        )

    async def report_bad_session(self, device_id: str, client_host: str = "") -> None:
        await self.consider(
            "invalid_session_or_device",
            0.85,
            device_id=device_id,
            client_host=client_host,
        )

    async def report_enroll_rate_limit(self, client_host: str = "") -> None:
        await self.consider(
            "enroll_rate_limit_exceeded",
            0.65,
            client_host=client_host,
        )

    async def report_cert_rotation(self, device_id: str = "", client_host: str = "") -> None:
        await self.consider(
            "unexpected_cert_rotation",
            0.95,
            device_id=device_id,
            client_host=client_host,
        )

    async def report_ordinary_auth_failure(self) -> None:
        # Explicit no-op for mistyped codes — must not trip the port.
        return


GUARD = CompanionSecurityGuard()
