"""Stream provider adapters."""

from moviebox_api.providers.base import BaseStreamProvider
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle
from moviebox_api.providers.registry import (
    DEFAULT_PROVIDER,
    ENVIRONMENT_PROVIDER_KEY,
    SUPPORTED_PROVIDERS,
    get_provider,
    normalize_provider_name,
)
from moviebox_api.providers.vega_provider import ENV_VEGA_PROVIDER_KEY

__all__ = [
    "BaseStreamProvider",
    "ProviderSearchResult",
    "ProviderStream",
    "ProviderSubtitle",
    "get_provider",
    "normalize_provider_name",
    "SUPPORTED_PROVIDERS",
    "DEFAULT_PROVIDER",
    "ENVIRONMENT_PROVIDER_KEY",
    "ENV_VEGA_PROVIDER_KEY",
]
