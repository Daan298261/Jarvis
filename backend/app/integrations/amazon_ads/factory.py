"""Factory for Amazon Ads clients — mock is the default.

Required environment variable *names* (never commit values):

- ``AMAZON_ADS_CLIENT_ID`` — LWA application client id
- ``AMAZON_ADS_CLIENT_SECRET`` — LWA application client secret
- ``AMAZON_ADS_REFRESH_TOKEN`` — optional default refresh token (per-connection
  tokens from OAuth are preferred at runtime)
- ``AMAZON_ADS_REGION`` — ``na`` (default), ``eu``, or ``fe``

Set ``JARVIS_AMAZON_ADS_CLIENT=live`` to request the live client. When
credentials are missing or incomplete the factory falls back to mock.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ...marketing.store import AMAZON_ADS_ENV
from ...workers.credentials import get_credential_secret, list_credentials
from .client import AmazonAdsClient
from .live_client import LiveAmazonAdsClient
from .mock_client import MockAmazonAdsClient

logger = logging.getLogger(__name__)

CLIENT_MODE_ENV = "JARVIS_AMAZON_ADS_CLIENT"

REQUIRED_ENV_VARS: tuple[str, ...] = (
    "AMAZON_ADS_CLIENT_ID",
    "AMAZON_ADS_CLIENT_SECRET",
    "AMAZON_ADS_REFRESH_TOKEN",
    "AMAZON_ADS_REGION",
)

CAP_CLIENT_ID = "amazon_ads.client_id"
CAP_CLIENT_SECRET = "amazon_ads.client_secret"
CAP_REFRESH_TOKEN = "amazon_ads.refresh_token"

_ENV_TO_FIELD: tuple[tuple[str, str, str], ...] = (
    ("AMAZON_ADS_CLIENT_ID", "client_id", CAP_CLIENT_ID),
    ("AMAZON_ADS_CLIENT_SECRET", "client_secret", CAP_CLIENT_SECRET),
    ("AMAZON_ADS_REFRESH_TOKEN", "refresh_token", CAP_REFRESH_TOKEN),
)


def _vault_secret_by_capability(capability: str) -> str | None:
    for row in list_credentials(AMAZON_ADS_ENV):
        if row.get("capability") == capability:
            secret = get_credential_secret(AMAZON_ADS_ENV, str(row.get("id") or ""))
            if secret:
                return secret
    return None


def resolve_client_credentials() -> dict[str, str]:
    """Compose app credentials from environment variables and the secrets vault."""
    creds: dict[str, str] = {}
    for env_name, field, capability in _ENV_TO_FIELD:
        value = (os.environ.get(env_name) or "").strip()
        if not value:
            value = (_vault_secret_by_capability(capability) or "").strip()
        if value:
            creds[field] = value

    region = (os.environ.get("AMAZON_ADS_REGION") or "na").strip().lower() or "na"
    creds["region"] = region
    return creds


def create_amazon_ads_client() -> AmazonAdsClient:
    """Return a mock client by default; live only when configured."""
    mode = (os.environ.get(CLIENT_MODE_ENV) or "mock").strip().lower()
    if mode == "mock":
        return MockAmazonAdsClient()

    creds = resolve_client_credentials()
    if not creds.get("client_id") or not creds.get("client_secret"):
        logger.info(
            "Amazon Ads live client requested (%s=%s) but credentials are incomplete — using mock",
            CLIENT_MODE_ENV,
            mode,
        )
        return MockAmazonAdsClient()

    return LiveAmazonAdsClient(
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
        region=creds.get("region", "na"),
        refresh_token=creds.get("refresh_token"),
    )


def client_mode_info() -> dict[str, Any]:
    """Metadata for health checks — documents env var names, never values."""
    creds = resolve_client_credentials()
    mode = (os.environ.get(CLIENT_MODE_ENV) or "mock").strip().lower()
    live_ready = bool(creds.get("client_id") and creds.get("client_secret"))
    effective = "live" if mode == "live" and live_ready else "mock"
    return {
        "requested_mode": mode,
        "effective_mode": effective,
        "live_ready": live_ready,
        "region": creds.get("region", "na"),
        "required_env_vars": list(REQUIRED_ENV_VARS),
        "client_mode_env": CLIENT_MODE_ENV,
    }
