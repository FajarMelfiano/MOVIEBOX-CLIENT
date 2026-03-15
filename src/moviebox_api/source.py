"""High-level helpers for multi-provider stream resolution."""

from moviebox_api.constants import SubjectType
from moviebox_api.providers import SUPPORTED_ANIME_PROVIDERS, get_provider, normalize_provider_name
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle


class SourceResolver:
    """Resolve stream links from a selected provider."""

    def __init__(self, provider_name: str | None = None):
        self.provider_name = provider_name
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
        if subject_type == SubjectType.ANIME:
            from moviebox_api.anime import resolve_anime_source_query

            selected_provider_name: str | None = None
            if self.provider_name:
                try:
                    normalized_provider_name = normalize_provider_name(self.provider_name)
                except ValueError:
                    normalized_provider_name = ''
                if normalized_provider_name in SUPPORTED_ANIME_PROVIDERS:
                    selected_provider_name = normalized_provider_name

            item, streams, subtitles, _provider_name = await resolve_anime_source_query(
                title,
                year=year,
                season=season,
                episode=episode,
                provider_name=selected_provider_name,
            )
            return (item, streams, subtitles)

        item: ProviderSearchResult | None = None

        id_builder = getattr(self.provider, 'build_item_from_ids', None)
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
