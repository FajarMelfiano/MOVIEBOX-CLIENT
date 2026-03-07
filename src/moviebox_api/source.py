"""High-level helpers for multi-provider stream resolution."""

from moviebox_api.constants import SubjectType
from moviebox_api.providers import get_provider
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle


class SourceResolver:
    """Resolve stream links from a selected provider."""

    def __init__(self, provider_name: str | None = None):
        self.provider = get_provider(provider_name)

    async def resolve(
        self,
        title: str,
        subject_type: SubjectType,
        *,
        year: int | None = None,
        season: int = 0,
        episode: int = 0,
        imdb_id: str | None = None,
        tmdb_id: int | None = None,
    ) -> tuple[ProviderSearchResult | None, list[ProviderStream], list[ProviderSubtitle]]:
        item: ProviderSearchResult | None = None

        id_builder = getattr(self.provider, "build_item_from_ids", None)
        if callable(id_builder):
            try:
                item = await id_builder(
                    subject_type=subject_type,
                    imdb_id=imdb_id,
                    tmdb_id=tmdb_id,
                    title=title,
                    year=year,
                )
            except Exception:
                item = None

        if item is None:
            item = await self.provider.search_best_match(
                query=title,
                subject_type=subject_type,
                year=year,
            )
        if item is None:
            return (None, [], [])

        streams = await self.provider.resolve_streams(
            item,
            season=season,
            episode=episode,
        )

        subtitles = await self.provider.resolve_subtitles(
            item,
            season=season,
            episode=episode,
        )

        if not subtitles:
            for stream in streams:
                subtitles.extend(stream.subtitles)

        return (item, streams, subtitles)
