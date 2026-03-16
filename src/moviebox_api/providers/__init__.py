"""Stream provider adapters."""

from moviebox_api.providers.base import BaseStreamProvider
from moviebox_api.providers.cloudstream_provider import CloudstreamProvider
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle
from moviebox_api.providers.registry import (
    DEFAULT_PROVIDER,
    ENVIRONMENT_PROVIDER_KEY,
    SUPPORTED_ANIME_PROVIDERS,
    SUPPORTED_MEDIA_PROVIDERS,
    SUPPORTED_PROVIDERS,
    get_provider,
    normalize_provider_name,
)
from moviebox_api.providers.vega_provider import ENV_VEGA_PROVIDER_KEY

__all__ = [
    "BaseStreamProvider",
    "CloudstreamProvider",
    "ProviderSearchResult",
    "ProviderStream",
    "ProviderSubtitle",
    "get_provider",
    "normalize_provider_name",
    "SUPPORTED_PROVIDERS",
    "SUPPORTED_MEDIA_PROVIDERS",
    "SUPPORTED_ANIME_PROVIDERS",
    "DEFAULT_PROVIDER",
    "ENVIRONMENT_PROVIDER_KEY",
    "ENV_VEGA_PROVIDER_KEY",
]
