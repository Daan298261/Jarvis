from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AmazonAdsError(RuntimeError):
    """Base error for Amazon Ads client operations."""


class TokenExpiredError(AmazonAdsError):
    """Raised when an access token has expired and refresh failed."""


class RateLimitError(AmazonAdsError):
    """Raised when API rate limits are exceeded."""


class AmazonAdsClient(ABC):
    """Interface for the official Amazon Ads API (live or mock)."""

    @abstractmethod
    def build_authorization_url(self, *, state: str, redirect_uri: str) -> str:
        ...

    @abstractmethod
    def exchange_code(self, *, code: str, redirect_uri: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def refresh_token(self, *, refresh_token: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def revoke_token(self, *, connection_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def fetch_performance_report(
        self,
        *,
        profile_id: str,
        start_date: str,
        end_date: str,
        access_token: str,
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    def apply_action(
        self,
        *,
        profile_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        change: dict[str, Any],
        access_token: str,
    ) -> dict[str, Any]:
        ...
