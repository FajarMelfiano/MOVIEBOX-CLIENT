"""Common models used by stream providers."""

from dataclasses import dataclass, field
from typing import Any

from moviebox_api.constants import SubjectType


@dataclass(slots=True)
class ProviderSubtitle:
    """Subtitle metadata returned by a provider."""

    url: str
    language: str = "unknown"
    label: str | None = None


@dataclass(slots=True)
class ProviderStream:
    """Stream metadata returned by a provider."""

    url: str
    source: str
    quality: str | None = None
    size: int | None = None
    audio: str | None = None
    audio_tracks: list[str] = field(default_factory=list)
    subtitles: list[ProviderSubtitle] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderSearchResult:
    """Generic search item returned by a provider."""

    id: str
    title: str
    page_url: str
    subject_type: SubjectType
    year: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
