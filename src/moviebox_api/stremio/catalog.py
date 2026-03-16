"""Cinemeta search helpers for interactive TUI flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

import httpx

from moviebox_api.constants import SubjectType

_CINEMETA_BASE_URL = "https://v3-cinemeta.strem.io"
_UNKNOWN_RELEASE_DATE = date(1900, 1, 1)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}


@dataclass(slots=True)
class StremioSearchItem:
    """Search result item used by interactive TUI."""

    subjectId: str
    subjectType: SubjectType
    title: str
    description: str
    releaseDate: date
    imdbRatingValue: float
    genre: list[str]
    imdbId: str
    tmdbId: int | None = None
    releaseInfo: str = ""
    page_url: str = ""
    stremioType: str = "movie"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def year(self) -> int | None:
        return None if self.releaseDate.year <= _UNKNOWN_RELEASE_DATE.year else self.releaseDate.year


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_year(value: str | None) -> int | None:
    if not value:
        return None

    for token in value.replace("/", "-").split("-"):
        token = token.strip()
        if len(token) == 4 and token.isdigit():
            parsed = int(token)
            if 1900 <= parsed <= 2200:
                return parsed
    return None


def _parse_release_date(meta: dict[str, Any]) -> date:
    raw_released = str(meta.get("released") or "").strip()
    if raw_released:
        iso_date = raw_released.split("T", maxsplit=1)[0]
        try:
            return datetime.fromisoformat(iso_date).date()
        except ValueError:
            pass

    year = _extract_year(str(meta.get("releaseInfo") or ""))
    if year is None:
        year = _extract_year(str(meta.get("year") or ""))

    if year is None:
        return _UNKNOWN_RELEASE_DATE

    return date(year, 1, 1)


def _normalise_genres(meta: dict[str, Any]) -> list[str]:
    raw_genres = meta.get("genres")
    if not isinstance(raw_genres, list):
        raw_genres = meta.get("genre")
    if not isinstance(raw_genres, list):
        return []

    values: list[str] = []
    for value in raw_genres:
        item = str(value).strip()
        if item and item not in values:
            values.append(item)
    return values


def _subject_type_from_cinemeta(content_type: str) -> SubjectType:
    return SubjectType.TV_SERIES if content_type == "series" else SubjectType.MOVIES


def _item_from_meta(meta: dict[str, Any], *, fallback_type: str) -> StremioSearchItem | None:
    imdb_id = str(meta.get("imdb_id") or meta.get("id") or "").strip()
    if not imdb_id.startswith("tt"):
        return None

    stremio_type = str(meta.get("type") or fallback_type or "movie").strip().lower()
    if stremio_type not in {"movie", "series"}:
        stremio_type = fallback_type

    title = str(meta.get("name") or "").strip()
    if not title:
        return None

    release_date = _parse_release_date(meta)
    rating = _to_float(meta.get("imdbRating"), default=0.0)
    release_info = str(meta.get("releaseInfo") or meta.get("year") or "").strip()

    tmdb_id_raw = meta.get("moviedb_id")
    tmdb_id: int | None = None
    if isinstance(tmdb_id_raw, int):
        tmdb_id = tmdb_id_raw
    elif isinstance(tmdb_id_raw, str) and tmdb_id_raw.isdigit():
        tmdb_id = int(tmdb_id_raw)

    page_url = f"https://www.imdb.com/title/{imdb_id}/"
    links = meta.get("links")
    if isinstance(links, list):
        for entry in links:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("category") or "").lower() != "share":
                continue
            candidate_url = str(entry.get("url") or "").strip()
            if candidate_url:
                page_url = candidate_url
                break

    return StremioSearchItem(
        subjectId=imdb_id,
        subjectType=_subject_type_from_cinemeta(stremio_type),
        title=title,
        description=str(meta.get("description") or "").strip(),
        releaseDate=release_date,
        imdbRatingValue=rating,
        genre=_normalise_genres(meta),
        imdbId=imdb_id,
        tmdbId=tmdb_id,
        releaseInfo=release_info,
        page_url=page_url,
        stremioType=stremio_type,
        metadata=dict(meta),
    )


def _catalog_types_for_subject(subject_type: SubjectType) -> list[str]:
    if subject_type == SubjectType.TV_SERIES:
        return ["series"]
    if subject_type == SubjectType.MOVIES:
        return ["movie"]
    return ["movie", "series"]


def _normalized_title_key(value: str) -> str:
    return ''.join(character for character in value.lower() if character.isalnum())


def _search_sort_key(query: str, item: StremioSearchItem) -> tuple[int, int, float, float, int, str]:
    normalized_query = _normalized_title_key(query)
    normalized_title = _normalized_title_key(item.title)
    exact_match = int(normalized_query == normalized_title and bool(normalized_query))
    starts_with_match = int(bool(normalized_query) and normalized_title.startswith(normalized_query))
    similarity = SequenceMatcher(None, normalized_query, normalized_title).ratio()
    return (
        exact_match,
        starts_with_match,
        similarity,
        item.imdbRatingValue,
        item.year or 0,
        item.title.lower(),
    )


async def search_cinemeta_catalog(
    query: str,
    subject_type: SubjectType,
    *,
    limit: int = 80,
) -> list[StremioSearchItem]:
    """Search movies/series from Cinemeta catalog endpoint."""

    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    discovered: list[StremioSearchItem] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(
        headers=_DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
    ) as client:
        for content_type in _catalog_types_for_subject(subject_type):
            encoded_query = quote(cleaned_query, safe="")
            url = f"{_CINEMETA_BASE_URL}/catalog/{content_type}/top/search={encoded_query}.json"
            response = await client.get(url)
            response.raise_for_status()

            payload = response.json()
            metas = payload.get("metas") if isinstance(payload, dict) else []
            if not isinstance(metas, list):
                continue

            for meta in metas:
                if not isinstance(meta, dict):
                    continue

                mapped_item = _item_from_meta(meta, fallback_type=content_type)
                if mapped_item is None:
                    continue
                if mapped_item.imdbId in seen_ids:
                    continue

                seen_ids.add(mapped_item.imdbId)
                discovered.append(mapped_item)

    discovered.sort(key=lambda item: _search_sort_key(cleaned_query, item), reverse=True)
    return discovered[:limit]


async def fetch_cinemeta_top_catalog(
    subject_type: SubjectType,
    *,
    limit: int = 60,
) -> list[StremioSearchItem]:
    """Fetch top/trending titles from Cinemeta catalog endpoint."""

    discovered: list[StremioSearchItem] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(
        headers=_DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
    ) as client:
        for content_type in _catalog_types_for_subject(subject_type):
            url = f"{_CINEMETA_BASE_URL}/catalog/{content_type}/top.json"
            response = await client.get(url)
            response.raise_for_status()

            payload = response.json()
            metas = payload.get("metas") if isinstance(payload, dict) else []
            if not isinstance(metas, list):
                continue

            for meta in metas:
                if not isinstance(meta, dict):
                    continue

                mapped_item = _item_from_meta(meta, fallback_type=content_type)
                if mapped_item is None:
                    continue
                if mapped_item.imdbId in seen_ids:
                    continue

                seen_ids.add(mapped_item.imdbId)
                discovered.append(mapped_item)

    discovered.sort(
        key=lambda item: (
            item.imdbRatingValue,
            item.year or 0,
            item.title.lower(),
        ),
        reverse=True,
    )
    return discovered[:limit]


async def fetch_cinemeta_meta(item: StremioSearchItem) -> dict[str, Any]:
    """Fetch full Cinemeta meta payload for an item."""

    if item.metadata.get("videos"):
        return item.metadata

    async with httpx.AsyncClient(
        headers=_DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
    ) as client:
        url = f"{_CINEMETA_BASE_URL}/meta/{item.stremioType}/{item.imdbId}.json"
        response = await client.get(url)
        response.raise_for_status()

    payload = response.json()
    meta = payload.get("meta") if isinstance(payload, dict) else {}
    if not isinstance(meta, dict):
        return item.metadata

    item.metadata = meta
    item.description = item.description or str(meta.get("description") or "").strip()
    item.genre = item.genre or _normalise_genres(meta)
    item.releaseInfo = item.releaseInfo or str(meta.get("releaseInfo") or "").strip()

    tmdb_id_raw = meta.get("moviedb_id")
    if isinstance(tmdb_id_raw, int):
        item.tmdbId = tmdb_id_raw
    elif isinstance(tmdb_id_raw, str) and tmdb_id_raw.isdigit():
        item.tmdbId = int(tmdb_id_raw)

    return item.metadata


def extract_series_seasons(meta: dict[str, Any]) -> dict[int, int]:
    """Extract season -> max_episode mapping from Cinemeta series meta."""

    videos = meta.get("videos")
    if not isinstance(videos, list):
        return {}

    seasons: dict[int, int] = {}
    for video in videos:
        if not isinstance(video, dict):
            continue

        season = _to_int(video.get("season"))
        episode = _to_int(video.get("episode"))
        if season is None or episode is None:
            continue

        if season <= 0 or episode <= 0:
            continue

        current_max = seasons.get(season, 0)
        if episode > current_max:
            seasons[season] = episode

    return dict(sorted(seasons.items()))


def build_stremio_video_id(item: StremioSearchItem, season: int = 0, episode: int = 0) -> str:
    """Build Stremio-compatible video id for subtitle endpoints."""

    if item.subjectType == SubjectType.TV_SERIES and season > 0 and episode > 0:
        return f"{item.imdbId}:{season}:{episode}"
    return item.imdbId
