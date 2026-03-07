"""Provider abstraction for external stream sources."""

from abc import ABC, abstractmethod
from difflib import SequenceMatcher

from moviebox_api.constants import SubjectType
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle


class BaseStreamProvider(ABC):
    """Base interface that all stream providers implement."""

    name: str = "unknown"

    @abstractmethod
    async def search(
        self,
        query: str,
        subject_type: SubjectType,
        *,
        year: int | None = None,
        limit: int = 20,
    ) -> list[ProviderSearchResult]:
        """Search content by title."""

    @abstractmethod
    async def resolve_streams(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderStream]:
        """Resolve playable streams for a selected item."""

    async def resolve_subtitles(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderSubtitle]:
        """Resolve subtitles for a selected item."""

        return []

    async def search_best_match(
        self,
        query: str,
        subject_type: SubjectType,
        *,
        year: int | None = None,
    ) -> ProviderSearchResult | None:
        """Find the best title match from provider search results."""

        results = await self.search(query, subject_type, year=year)
        if not results:
            return None

        def score(item: ProviderSearchResult) -> float:
            return SequenceMatcher(None, query.lower(), item.title.lower()).ratio()

        scored_items = sorted(results, key=score, reverse=True)

        if year:
            for item in scored_items:
                if item.year == year and score(item) >= 0.6:
                    return item

        first_item = scored_items[0]
        return first_item if score(first_item) >= 0.6 else None
