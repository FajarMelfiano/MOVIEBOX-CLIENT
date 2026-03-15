"""Shared anime catalog, provider fallback, and subtitle helpers."""

from __future__ import annotations

import asyncio
import re
from datetime import date
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

from moviebox_api.constants import SubjectType
from moviebox_api.providers import SUPPORTED_ANIME_PROVIDERS, get_provider, normalize_provider_name
from moviebox_api.providers.anime_common import quality_rank
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle
from moviebox_api.stremio.catalog import StremioSearchItem, build_stremio_video_id, search_cinemeta_catalog
from moviebox_api.stremio.subtitle_sources import ExternalSubtitle, fetch_external_subtitles

_UNKNOWN_RELEASE_DATE = date(1900, 1, 1)
_DIRECT_MEDIA_EXTENSIONS = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v', '.ts')
_STREAMABLE_MEDIA_EXTENSIONS = _DIRECT_MEDIA_EXTENSIONS + ('.m3u8', '.mpd')


def anime_provider_order(provider_name: str | None = None) -> tuple[str, ...]:
    """Return anime provider names with the preferred provider first."""

    if provider_name is None or not str(provider_name).strip():
        return SUPPORTED_ANIME_PROVIDERS

    normalized = normalize_provider_name(provider_name)
    if normalized not in SUPPORTED_ANIME_PROVIDERS:
        allowed = ', '.join(SUPPORTED_ANIME_PROVIDERS)
        raise ValueError(f"Unsupported anime provider '{provider_name}'. Choose from: {allowed}")

    return (normalized,) + tuple(name for name in SUPPORTED_ANIME_PROVIDERS if name != normalized)


def is_anime_item(item: StremioSearchItem | None) -> bool:
    """Return True when the selected catalog item belongs to the anime flow."""

    return bool(item and item.subjectType == SubjectType.ANIME)


def anime_payload(item: StremioSearchItem | None) -> dict[str, Any]:
    """Return the primary anime payload stored on a search item."""

    if item is None or not isinstance(item.metadata, dict):
        return {}
    payload = item.metadata.get('anime_payload')
    return payload if isinstance(payload, dict) else {}


def anime_provider_name(item: StremioSearchItem | None) -> str:
    """Return the primary provider name for an anime item."""

    payload = anime_payload(item)
    provider_name = str(payload.get('provider_name') or '').strip().lower()
    if provider_name:
        return provider_name

    if item and isinstance(item.metadata, dict):
        return str(item.metadata.get('anime_provider_name') or '').strip().lower()
    return ''


def anime_alt_titles(item: StremioSearchItem | None) -> list[str]:
    """Return alternate titles stored on an anime item."""

    payload = anime_payload(item)
    values = payload.get('alt_titles')
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def anime_genres(item: StremioSearchItem | None) -> list[str]:
    """Return genres stored on an anime item."""

    payload = anime_payload(item)
    values = payload.get('genres')
    if not isinstance(values, list):
        return list(item.genre) if item else []
    return [str(value).strip() for value in values if str(value).strip()]


def anime_episode_count(item: StremioSearchItem | None) -> int:
    """Return the known episode count for an anime item."""

    payload = anime_payload(item)
    try:
        return max(int(payload.get('episode_count') or 0), 0)
    except (TypeError, ValueError):
        return 0


def anime_status(item: StremioSearchItem | None) -> str:
    """Return the provider status value for an anime item."""

    payload = anime_payload(item)
    return str(payload.get('status') or '').strip()


def anime_content_subject_type(item: StremioSearchItem | None) -> SubjectType:
    """Return movie-vs-series semantics for anime content."""

    payload = anime_payload(item)
    raw_value = payload.get('content_subject_type')
    if isinstance(raw_value, SubjectType):
        return raw_value
    if isinstance(raw_value, int):
        try:
            return SubjectType(raw_value)
        except ValueError:
            pass
    if isinstance(raw_value, str):
        cleaned = raw_value.strip().upper()
        if cleaned in SubjectType.__members__:
            return SubjectType[cleaned]

    return SubjectType.TV_SERIES if anime_episode_count(item) > 1 else SubjectType.MOVIES


def anime_season_map(item: StremioSearchItem | None) -> dict[int, int]:
    """Return season metadata for anime flows."""

    payload = anime_payload(item)
    season_map = payload.get('season_map')
    if isinstance(season_map, dict):
        normalized: dict[int, int] = {}
        for key, value in season_map.items():
            try:
                season = int(key)
                episodes = int(value)
            except (TypeError, ValueError):
                continue
            if season > 0 and episodes > 0:
                normalized[season] = episodes
        if normalized:
            return dict(sorted(normalized.items()))

    episode_count = anime_episode_count(item)
    if anime_content_subject_type(item) == SubjectType.TV_SERIES and episode_count > 0:
        return {1: episode_count}
    return {}


def anime_has_episode_flow(item: StremioSearchItem | None) -> bool:
    """Return True when anime item should expose season/episode selectors."""

    return anime_content_subject_type(item) == SubjectType.TV_SERIES and bool(anime_season_map(item))


def anime_requires_season_selection(item: StremioSearchItem | None) -> bool:
    """Return True when the UI should show a separate season selector for anime."""

    return anime_has_episode_flow(item) and len(anime_season_map(item)) > 1


def anime_default_season(item: StremioSearchItem | None) -> int:
    """Return the default season number for anime episode selection."""

    seasons = anime_season_map(item)
    return next(iter(seasons), 1)


def anime_query_candidates(item: StremioSearchItem | None) -> list[str]:
    """Build a list of search queries for provider and subtitle fallback lookups."""

    candidates: list[str] = []
    if item is not None:
        candidates.append(item.title)
        candidates.extend(anime_alt_titles(item))
        if isinstance(item.metadata, dict):
            extra_candidates = item.metadata.get('anime_query_candidates')
            if isinstance(extra_candidates, list):
                candidates.extend(str(value).strip() for value in extra_candidates)

    deduped: list[str] = []
    for candidate in candidates:
        cleaned = str(candidate).strip()
        if cleaned and cleaned.lower() not in {value.lower() for value in deduped}:
            deduped.append(cleaned)
    return deduped


def stream_is_streamable(url: str) -> bool:
    """Return True when the URL looks stream-friendly for known players."""

    path = urlparse(url).path.lower()
    return path.endswith(_STREAMABLE_MEDIA_EXTENSIONS)


def stream_is_direct_download(url: str) -> bool:
    """Return True when the URL looks safe for direct file download."""

    parsed = urlparse(url)
    path = parsed.path.lower()
    host = parsed.netloc.lower()
    if path.endswith(_DIRECT_MEDIA_EXTENSIONS):
        return True
    if 'videoplayback' in path or 'download' in path:
        return True
    if 'pixeldrain.com' in host and path.startswith('/api/file/'):
        return True
    if 'drive.google.com' in host and path.startswith('/uc'):
        return True
    if host == 'drive.usercontent.google.com' and path.startswith('/download'):
        return True
    if host.endswith('googleusercontent.com') and path.startswith('/download'):
        return True
    return False


def _stream_is_usable(stream: ProviderStream) -> bool:
    if stream_is_streamable(stream.url) or stream_is_direct_download(stream.url):
        return True

    source = str(stream.source or '').strip().lower()
    if ':hls' in source or ':dash' in source:
        return True
    return False


def _release_date(year: int | None) -> date:
    if year and 1900 <= year <= 2200:
        return date(year, 1, 1)
    return _UNKNOWN_RELEASE_DATE


def _normalized_title_key(title: str) -> str:
    return ''.join(character for character in title.lower() if character.isalnum())


def _provider_record(item: ProviderSearchResult) -> dict[str, Any]:
    return {
        'id': item.id,
        'title': item.title,
        'page_url': item.page_url,
        'year': item.year,
        'payload': dict(item.payload),
    }


def _record_to_provider_result(record: dict[str, Any]) -> ProviderSearchResult | None:
    item_id = str(record.get('id') or '').strip()
    title = str(record.get('title') or '').strip()
    page_url = str(record.get('page_url') or '').strip()
    payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
    if not item_id or not title or not page_url:
        return None
    return ProviderSearchResult(
        id=item_id,
        title=title,
        page_url=page_url,
        subject_type=SubjectType.ANIME,
        year=record.get('year') if isinstance(record.get('year'), int) else None,
        payload=dict(payload),
    )


def _build_minimal_item(
    title: str,
    *,
    year: int | None = None,
    query_candidates: list[str] | None = None,
) -> StremioSearchItem:
    candidates = [title, *(query_candidates or [])]
    deduped_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = str(candidate).strip()
        lowered = cleaned.lower()
        if not cleaned or lowered in seen:
            continue
        seen.add(lowered)
        deduped_candidates.append(cleaned)

    primary_title = deduped_candidates[0] if deduped_candidates else title.strip()
    return StremioSearchItem(
        subjectId=f"anime:query:{_normalized_title_key(primary_title) or 'unknown'}",
        subjectType=SubjectType.ANIME,
        title=primary_title,
        description='',
        releaseDate=_release_date(year),
        imdbRatingValue=0.0,
        genre=[],
        imdbId=f"anime:query:{_normalized_title_key(primary_title) or 'unknown'}",
        releaseInfo=str(year or ''),
        page_url='',
        stremioType='series',
        metadata={'anime_query_candidates': deduped_candidates},
    )


def _provider_result_to_item(item: ProviderSearchResult) -> StremioSearchItem:
    payload = dict(item.payload)
    provider_name = str(payload.get('provider_name') or '').strip().lower() or 'anime'
    alt_titles = [str(value).strip() for value in payload.get('alt_titles', []) if str(value).strip()]
    query_candidates = [item.title, *alt_titles]
    provider_record = _provider_record(item)
    subject_key = _normalized_title_key(item.title) or provider_name
    semantic_subject_type = anime_content_subject_type(
        StremioSearchItem(
            subjectId='temp',
            subjectType=SubjectType.ANIME,
            title=item.title,
            description=str(payload.get('description') or '').strip(),
            releaseDate=_release_date(item.year),
            imdbRatingValue=float(payload.get('rating') or 0.0),
            genre=[str(value).strip() for value in payload.get('genres', []) if str(value).strip()],
            imdbId='temp',
            releaseInfo=str(item.year or ''),
            page_url=item.page_url,
            stremioType='series',
            metadata={'anime_payload': payload},
        )
    )
    return StremioSearchItem(
        subjectId=f"anime:{provider_name}:{subject_key}",
        subjectType=SubjectType.ANIME,
        title=item.title,
        description=str(payload.get('description') or '').strip(),
        releaseDate=_release_date(item.year),
        imdbRatingValue=float(payload.get('rating') or 0.0),
        genre=[str(value).strip() for value in payload.get('genres', []) if str(value).strip()],
        imdbId=f"anime:{provider_name}:{subject_key}",
        releaseInfo=str(item.year or ''),
        page_url=item.page_url,
        stremioType='series' if semantic_subject_type == SubjectType.TV_SERIES else 'movie',
        metadata={
            'anime_provider_name': provider_name,
            'anime_provider_names': [provider_name],
            'anime_provider_payloads': {provider_name: provider_record},
            'anime_payload': payload,
            'anime_query_candidates': query_candidates,
        },
    )




def anime_item_from_provider_result(item: ProviderSearchResult) -> StremioSearchItem:
    """Public wrapper for mapping a provider search result into the shared anime item shape."""

    return _provider_result_to_item(item)


async def search_best_anime_item(
    query: str,
    *,
    provider_name: str | None = None,
    year: int | None = None,
    limit: int = 20,
) -> StremioSearchItem | None:
    """Find the best anime search result across configured providers."""

    cleaned_query = query.strip()
    if not cleaned_query:
        return None

    if provider_name:
        provider = get_provider(anime_provider_order(provider_name)[0])
        provider_results = await provider.search(cleaned_query, SubjectType.ANIME, year=year, limit=limit)
        results = [_provider_result_to_item(item) for item in provider_results]
    else:
        results = await search_anime_catalog(cleaned_query, provider_name=provider_name, limit=limit)

    if year is not None:
        exact_year_results = [item for item in results if item.year == year]
        if exact_year_results:
            results = exact_year_results

    scored = [(_score_query_to_item(cleaned_query, item, year=year), item) for item in results]
    if not scored:
        return None

    scored.sort(key=lambda entry: entry[0], reverse=True)
    top_score, top_item = scored[0]
    return top_item if top_score >= 0.55 else None

def _item_richness(item: StremioSearchItem) -> tuple[int, int, int, float]:
    payload = anime_payload(item)
    return (
        len(str(item.description or '').strip()),
        len(payload.get('episodes') or []) if isinstance(payload.get('episodes'), list) else 0,
        len(item.genre),
        float(payload.get('rating') or 0.0),
    )


def _merge_items(target: StremioSearchItem, candidate: StremioSearchItem) -> None:
    target_records = target.metadata.setdefault('anime_provider_payloads', {})
    candidate_records = candidate.metadata.get('anime_provider_payloads', {})
    if isinstance(target_records, dict) and isinstance(candidate_records, dict):
        target_records.update(candidate_records)

    provider_names = target.metadata.setdefault('anime_provider_names', [])
    for provider_name in candidate.metadata.get('anime_provider_names', []):
        if provider_name not in provider_names:
            provider_names.append(provider_name)

    combined_queries = anime_query_candidates(target) + anime_query_candidates(candidate)
    deduped_queries: list[str] = []
    seen: set[str] = set()
    for query in combined_queries:
        lowered = query.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped_queries.append(query)
    target.metadata['anime_query_candidates'] = deduped_queries

    if _item_richness(candidate) > _item_richness(target):
        target.description = candidate.description or target.description
        target.releaseDate = candidate.releaseDate
        target.imdbRatingValue = candidate.imdbRatingValue
        target.genre = list(candidate.genre or target.genre)
        target.page_url = candidate.page_url or target.page_url
        target.releaseInfo = candidate.releaseInfo or target.releaseInfo
        target.stremioType = candidate.stremioType or target.stremioType
        target.metadata['anime_provider_name'] = candidate.metadata.get('anime_provider_name')
        target.metadata['anime_payload'] = dict(anime_payload(candidate))


def _sort_items(
    items: list[StremioSearchItem],
    *,
    query: str | None = None,
) -> list[StremioSearchItem]:
    return sorted(
        items,
        key=lambda item: (
            _score_query_to_item(query, item, year=None) if query else 0.0,
            *_item_richness(item),
            anime_episode_count(item),
            item.year or 0,
            item.title.lower(),
        ),
        reverse=True,
    )


def _title_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r'[^a-z0-9]+', str(value).strip().lower())
        if token
    }


def _title_match_score(query: str, candidate: str) -> float:
    cleaned_query = str(query).strip().lower()
    cleaned_candidate = str(candidate).strip().lower()
    if not cleaned_query or not cleaned_candidate:
        return 0.0

    query_key = _normalized_title_key(cleaned_query)
    candidate_key = _normalized_title_key(cleaned_candidate)
    score = max(
        SequenceMatcher(None, cleaned_query, cleaned_candidate).ratio(),
        SequenceMatcher(None, query_key, candidate_key).ratio() if query_key and candidate_key else 0.0,
    )

    if query_key and candidate_key:
        if query_key == candidate_key:
            score += 0.4
        elif candidate_key.startswith(query_key):
            score += 0.25
        elif query_key in candidate_key:
            score += 0.18

    query_tokens = _title_tokens(cleaned_query)
    candidate_tokens = _title_tokens(cleaned_candidate)
    if query_tokens and candidate_tokens:
        score += 0.25 * (len(query_tokens & candidate_tokens) / len(query_tokens))
    return score


def _provider_item_candidates(item: ProviderSearchResult) -> list[str]:
    candidates = [item.title]
    if isinstance(item.payload, dict):
        alt_titles = item.payload.get('alt_titles')
        if isinstance(alt_titles, list):
            candidates.extend(str(value).strip() for value in alt_titles if str(value).strip())
    return [candidate for candidate in candidates if candidate]


def _score_provider_item(
    item: ProviderSearchResult,
    title_candidates: list[str],
    *,
    year: int | None,
) -> float:
    provider_candidates = _provider_item_candidates(item)
    score = max(
        _title_match_score(title_candidate, provider_candidate)
        for title_candidate in title_candidates
        for provider_candidate in provider_candidates
    )
    payload = item.payload if isinstance(item.payload, dict) else {}
    try:
        episode_count = max(int(payload.get('episode_count') or 0), 0)
    except (TypeError, ValueError):
        episode_count = 0
    anime_type = str(payload.get('anime_type') or '').strip().lower()
    if episode_count > 0:
        score += min(episode_count, 24) / 200.0
    elif anime_type not in {'movie', 'film'}:
        score -= 0.12
    if year and item.year and year == item.year:
        score += 0.08
    return score


def _score_match(
    candidate_title: str,
    title_candidates: list[str],
    *,
    year: int | None,
    candidate_year: int | None,
) -> float:
    score = max(_title_match_score(value, candidate_title) for value in title_candidates)
    if year and candidate_year and year == candidate_year:
        score += 0.08
    return score


def _score_query_to_item(query: str | None, item: StremioSearchItem, *, year: int | None) -> float:
    cleaned_query = str(query or '').strip()
    if not cleaned_query:
        return 0.0

    candidates = anime_query_candidates(item) or [item.title]
    score = max(_title_match_score(cleaned_query, candidate) for candidate in candidates)
    episode_count = anime_episode_count(item)
    if episode_count > 0:
        score += min(episode_count, 24) / 200.0
    elif anime_content_subject_type(item) == SubjectType.TV_SERIES:
        score -= 0.12
    if year and item.year and year == item.year:
        score += 0.08
    return score


async def search_anime_catalog(
    query: str,
    *,
    provider_name: str | None = None,
    limit: int = 80,
) -> list[StremioSearchItem]:
    """Search all configured anime providers and merge results."""

    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    provider_names = anime_provider_order(provider_name)
    per_provider_limit = max(5, min(limit, 20))
    tasks = [
        get_provider(name).search(cleaned_query, SubjectType.ANIME, limit=per_provider_limit)
        for name in provider_names
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    merged: dict[str, StremioSearchItem] = {}
    for response in responses:
        if isinstance(response, Exception):
            continue
        for provider_item in response:
            mapped = _provider_result_to_item(provider_item)
            key = f"{_normalized_title_key(mapped.title)}:{mapped.year or 0}"
            if key not in merged:
                merged[key] = mapped
                continue
            _merge_items(merged[key], mapped)

    return _sort_items(list(merged.values()), query=cleaned_query)[:limit]


async def fetch_anime_home_items(*, limit: int = 60) -> list[StremioSearchItem]:
    """Fetch trending or recently updated anime items from configured providers."""

    tasks: list[asyncio.Future | asyncio.Task | Any] = []
    provider_names: list[str] = []
    for name in anime_provider_order(None):
        provider = get_provider(name)
        list_trending = getattr(provider, 'list_trending', None)
        if callable(list_trending):
            provider_names.append(name)
            tasks.append(list_trending(limit=limit))

    if not tasks:
        return []

    responses = await asyncio.gather(*tasks, return_exceptions=True)
    merged: dict[str, StremioSearchItem] = {}
    for response in responses:
        if isinstance(response, Exception):
            continue
        for provider_item in response:
            mapped = _provider_result_to_item(provider_item)
            key = f"{_normalized_title_key(mapped.title)}:{mapped.year or 0}"
            if key not in merged:
                merged[key] = mapped
                continue
            _merge_items(merged[key], mapped)

    return _sort_items(list(merged.values()))[:limit]


def _provider_item_identity(item: ProviderSearchResult) -> str:
    return str(item.page_url or item.id or item.title).strip().lower()


def _provider_item_episode_count(item: ProviderSearchResult) -> int:
    payload = item.payload if isinstance(item.payload, dict) else {}
    try:
        return max(int(payload.get('episode_count') or 0), 0)
    except (TypeError, ValueError):
        return 0


async def _search_provider_items(
    provider_name: str,
    title_candidates: list[str],
    *,
    year: int | None,
) -> list[ProviderSearchResult]:
    provider = get_provider(provider_name)
    scored_matches: dict[str, tuple[float, ProviderSearchResult]] = {}
    search_years = [year]
    if year is not None:
        search_years.append(None)

    for title_candidate in title_candidates:
        candidate = title_candidate.strip()
        if not candidate:
            continue
        for search_year in search_years:
            try:
                provider_results = await provider.search(
                    candidate,
                    SubjectType.ANIME,
                    year=search_year,
                    limit=20,
                )
            except Exception:
                continue
            for provider_item in provider_results:
                score = _score_provider_item(provider_item, title_candidates, year=year)
                identity = _provider_item_identity(provider_item)
                current = scored_matches.get(identity)
                if current is None or score > current[0]:
                    scored_matches[identity] = (score, provider_item)

    ranked = sorted(
        scored_matches.values(),
        key=lambda entry: (
            entry[0],
            _provider_item_episode_count(entry[1]),
            entry[1].year or 0,
        ),
        reverse=True,
    )
    return [entry[1] for entry in ranked]


async def _search_provider_item(
    provider_name: str,
    title_candidates: list[str],
    *,
    year: int | None,
) -> ProviderSearchResult | None:
    provider_items = await _search_provider_items(provider_name, title_candidates, year=year)
    return provider_items[0] if provider_items else None


def _restore_provider_item(item: StremioSearchItem, provider_name: str) -> ProviderSearchResult | None:
    if not isinstance(item.metadata, dict):
        return None
    records = item.metadata.get('anime_provider_payloads')
    if not isinstance(records, dict):
        return None
    record = records.get(provider_name)
    if not isinstance(record, dict):
        return None
    return _record_to_provider_result(record)


async def resolve_anime_sources(
    item: StremioSearchItem,
    *,
    provider_name: str | None = None,
    season: int = 0,
    episode: int = 0,
) -> tuple[ProviderSearchResult | None, list[ProviderStream], list[ProviderSubtitle], str]:
    """Resolve anime streams with automatic provider fallback."""

    if not is_anime_item(item):
        raise ValueError('resolve_anime_sources expects an anime item')

    episodic = anime_has_episode_flow(item)
    season_number = season if season > 0 else (1 if episodic else 0)
    episode_number = episode if episode > 0 else (1 if episodic else 0)
    requested_provider = str(provider_name or '').strip()
    if requested_provider:
        provider_names = (anime_provider_order(requested_provider)[0],)
    else:
        provider_names = anime_provider_order(anime_provider_name(item) or None)
    title_candidates = anime_query_candidates(item) or [item.title]
    errors: list[str] = []
    fallback_result: (
        tuple[ProviderSearchResult | None, list[ProviderStream], list[ProviderSubtitle], str] | None
    ) = None

    for current_provider in provider_names:
        provider_items: list[ProviderSearchResult] = []
        restored_item = _restore_provider_item(item, current_provider)
        if restored_item is not None:
            provider_items.append(restored_item)

        searched_items = await _search_provider_items(current_provider, title_candidates, year=item.year)
        for searched_item in searched_items:
            already_added = any(
                _provider_item_identity(existing) == _provider_item_identity(searched_item)
                for existing in provider_items
            )
            if already_added:
                continue
            provider_items.append(searched_item)

        if not provider_items:
            errors.append(f'{current_provider}: no search match')
            continue

        provider = get_provider(current_provider)
        current_fallback_result: (
            tuple[ProviderSearchResult | None, list[ProviderStream], list[ProviderSubtitle], str] | None
        ) = None
        current_provider_errors: list[str] = []

        for provider_item in provider_items[:5]:
            try:
                streams = await provider.resolve_streams(
                    provider_item,
                    season=season_number,
                    episode=episode_number,
                )
                subtitles = await provider.resolve_subtitles(
                    provider_item,
                    season=season_number,
                    episode=episode_number,
                )
            except Exception as exc:
                current_provider_errors.append(f"{provider_item.title}: {exc}")
                continue

            if not subtitles:
                subtitles = []
                for stream in streams:
                    subtitles.extend(stream.subtitles)

            usable_streams = [stream for stream in streams if _stream_is_usable(stream)]
            if usable_streams:
                return provider_item, usable_streams, subtitles, current_provider
            if streams and current_fallback_result is None:
                current_fallback_result = (provider_item, streams, subtitles, current_provider)
                current_provider_errors.append(f'{provider_item.title}: wrapper-only streams')
                continue

            current_provider_errors.append(f'{provider_item.title}: no streams')

        if current_fallback_result is not None and fallback_result is None:
            fallback_result = current_fallback_result

        if current_provider_errors:
            errors.extend(f'{current_provider}: {detail}' for detail in current_provider_errors)

    if fallback_result is not None:
        return fallback_result
    raise RuntimeError('; '.join(errors) or 'No anime streams resolved')


async def resolve_anime_source_query(
    title: str,
    *,
    year: int | None = None,
    season: int = 0,
    episode: int = 0,
    provider_name: str | None = None,
    query_candidates: list[str] | None = None,
) -> tuple[ProviderSearchResult | None, list[ProviderStream], list[ProviderSubtitle], str]:
    """Resolve anime streams starting from a plain title query."""

    query_item = _build_minimal_item(title, year=year, query_candidates=query_candidates)
    return await resolve_anime_sources(
        query_item,
        provider_name=provider_name,
        season=season,
        episode=episode,
    )


def select_stream_by_quality(
    streams: list[ProviderStream],
    quality: str | None,
    *,
    prefer_direct: bool = False,
    audio: str | None = None,
) -> ProviderStream | None:
    """Pick the best stream candidate for the requested quality and audio label."""

    if not streams:
        return None

    target_quality = str(quality or 'BEST').strip().upper()
    audio_filter = str(audio or '').strip().lower()

    filtered = streams
    if audio_filter:
        matching_audio = [
            stream
            for stream in filtered
            if audio_filter in str(stream.audio or '').strip().lower()
            or any(audio_filter in str(label).strip().lower() for label in stream.audio_tracks)
            or audio_filter in str(stream.source or '').strip().lower()
        ]
        if matching_audio:
            filtered = matching_audio

    if prefer_direct:
        direct = [stream for stream in filtered if stream_is_direct_download(stream.url)]
        if direct:
            filtered = direct

    ranked = list(filtered)
    if target_quality == 'WORST':
        ranked.sort(key=lambda stream: quality_rank(stream.quality))
        return ranked[0]
    if target_quality == 'BEST':
        ranked.sort(key=lambda stream: quality_rank(stream.quality), reverse=True)
        return ranked[0]

    desired_quality = quality_rank(target_quality)
    ranked.sort(
        key=lambda stream: (
            abs(quality_rank(stream.quality) - desired_quality),
            -quality_rank(stream.quality),
        )
    )
    return ranked[0]


async def resolve_anime_cinemeta_item(item: StremioSearchItem) -> StremioSearchItem | None:
    """Match an anime item to a Cinemeta movie or series entry for subtitle fallback."""

    if not is_anime_item(item):
        return item

    if isinstance(item.metadata, dict):
        cached = item.metadata.get('anime_cinemeta_match')
        if isinstance(cached, StremioSearchItem):
            return cached

    title_candidates = anime_query_candidates(item) or [item.title]
    preferred_subject_type = anime_content_subject_type(item)
    subject_candidates = [preferred_subject_type]
    if SubjectType.ALL not in subject_candidates:
        subject_candidates.append(SubjectType.ALL)

    best_match: StremioSearchItem | None = None
    best_score = 0.0
    for subject_type in subject_candidates:
        for title_candidate in title_candidates:
            try:
                results = await search_cinemeta_catalog(title_candidate, subject_type, limit=20)
            except Exception:
                continue
            for candidate in results:
                score = _score_match(
                    candidate.title,
                    title_candidates,
                    year=item.year,
                    candidate_year=candidate.year,
                )
                if preferred_subject_type == candidate.subjectType:
                    score += 0.05
                if score > best_score:
                    best_match = candidate
                    best_score = score
            if best_score >= 0.92:
                break
        if best_score >= 0.92:
            break

    if best_match is None or best_score < 0.58:
        return None

    if isinstance(item.metadata, dict):
        item.metadata['anime_cinemeta_match'] = best_match
    return best_match


async def fetch_anime_external_subtitles(
    item: StremioSearchItem,
    *,
    season: int = 0,
    episode: int = 0,
    sources: list[str],
    preferred_languages: list[str] | None = None,
) -> list[ExternalSubtitle]:
    """Fetch external subtitles for anime after matching the title back to Cinemeta."""

    matched_item = await resolve_anime_cinemeta_item(item)
    if matched_item is None:
        return []

    if matched_item.subjectType == SubjectType.TV_SERIES:
        season_number = season if season > 0 else 1
        episode_number = episode if episode > 0 else 1
        video_id = build_stremio_video_id(matched_item, season=season_number, episode=episode_number)
        content_type = 'series'
    else:
        video_id = build_stremio_video_id(matched_item)
        content_type = 'movie'

    return await fetch_external_subtitles(
        video_id=video_id,
        content_type=content_type,
        sources=sources,
        preferred_languages=preferred_languages,
    )
