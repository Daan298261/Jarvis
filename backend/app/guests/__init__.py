"""Scoped guest portals — revocable capability tokens with deny-by-default access."""

from .service import GuestContext, GuestPortalService, SERVICE

__all__ = ["GuestContext", "GuestPortalService", "SERVICE"]
