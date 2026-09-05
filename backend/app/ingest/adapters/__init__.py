"""Platform-specific HTTP resolvers."""

from .instagram import InstagramAdapter
from .generic import GenericWebAdapter

ADAPTERS = {
    "instagram": InstagramAdapter(),
    "web": GenericWebAdapter(),
    "tiktok": GenericWebAdapter(),
    "x": GenericWebAdapter(),
    "youtube": GenericWebAdapter(),
    "github": GenericWebAdapter(),
}


def adapter_for(platform: str):
    return ADAPTERS.get(platform) or GenericWebAdapter()
