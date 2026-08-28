"""Amazon Ads API integration."""

from .client import AmazonAdsClient, AmazonAdsError, RateLimitError, TokenExpiredError
from .factory import CLIENT_MODE_ENV, REQUIRED_ENV_VARS, client_mode_info, create_amazon_ads_client
from .live_client import LiveAmazonAdsClient
from .mock_client import MockAmazonAdsClient

__all__ = [
    "AmazonAdsClient",
    "AmazonAdsError",
    "CLIENT_MODE_ENV",
    "LiveAmazonAdsClient",
    "MockAmazonAdsClient",
    "RateLimitError",
    "REQUIRED_ENV_VARS",
    "TokenExpiredError",
    "client_mode_info",
    "create_amazon_ads_client",
]
