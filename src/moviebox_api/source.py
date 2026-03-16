"""High-level helpers for multi-provider stream resolution."""

from difflib import SequenceMatcher

from moviebox_api.constants import SubjectType
from moviebox_api.providers import SUPPORTED_ANIME_PROVIDERS, get_provider, normalize_provider_name
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle


def _normalized_title_key(value: str) -> str:
    return ''.join(character for character in value.lower() if character.isalnum())


def _cross_subject_fallback_allowed(title: str, item: ProviderSearchResult) -> bool:
    requested_key = _normalized_title_key(title)
    candidate_key = _normalized_title_key(item.title)
    if not requested_key or not candidate_key:
        return False
    if requested_key == candidate_key:
        return True
    return SequenceMatcher(None, requested_key, candidate_key).ratio() >= 0.97


def _alternate_subject_type(subject_type: SubjectType) -> SubjectType | None:
    if subject_type == SubjectType.MOVIES:
        return SubjectType.TV_SERIES
    if subject_type == SubjectType.TV_SERIES:
        return SubjectType.MOVIES
    return None


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

        normalized_provider_name = ''
        raw_provider_name = self.provider_name or getattr(self.provider, 'name', '')
        if raw_provider_name:
            try:
                normalized_provider_name = normalize_provider_name(raw_provider_name)
            except ValueError:
                normalized_provider_name = ''

        if item is None and normalized_provider_name == 'cloudstream':
            alternate_subject_type = _alternate_subject_type(subject_type)
            fallback_years: list[int | None] = []
            if year is not None:
                fallback_years.append(year)
            fallback_years.append(None)

            if alternate_subject_type is not None:
                for fallback_year in fallback_years:
                    alternate_item = await self.provider.search_best_match(
                        query=title,
                        subject_type=alternate_subject_type,
                        year=fallback_year,
                    )
                    if alternate_item is None:
                        continue
                    if not _cross_subject_fallback_allowed(title, alternate_item):
                        continue
                    alternate_item.payload['resolved_subject_fallback_from'] = subject_type.name
                    item = alternate_item
                    break

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
