"""Subtitle fetch helpers for OpenSubtitles, SubDL, and SubSource."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from moviebox_api.language import normalize_language_id, to_iso639_1
from moviebox_api.security.secrets import get_secret

SUBDL_API_KEY_ENV = "MOVIEBOX_SUBDL_API_KEY"
SUBSOURCE_API_KEY_ENV = "MOVIEBOX_SUBSOURCE_API_KEY"

_OPEN_SUBTITLES_URL = "https://opensubtitles-v3.strem.io"
_SUBDL_BASE_URL = "https://subdl.strem.top"
_SUBSOURCE_BASE_URL = "https://subsource.strem.top"
_DEFAULT_HEARING_MODE = "hiInclude"

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}

_SUBSOURCE_KEY_VALIDATION_CACHE: dict[str, bool] = {}


@dataclass(slots=True)
class ExternalSubtitle:
    """Subtitle entry returned from external subtitle providers."""

    url: str
    language: str
    label: str
    source: str


def _normalise_language_code(language: str | None) -> str:
    canonical = normalize_language_id(language)
    if canonical == "unknown":
        return "unknown"

    iso639_1 = to_iso639_1(canonical)
    if iso639_1:
        return iso639_1

    return canonical


def _preferred_language_codes(preferred_languages: list[str] | None) -> list[str]:
    if not preferred_languages:
        return ["en", "id"]

    values: list[str] = []
    for language in preferred_languages:
        code = _normalise_language_code(language)
        if code == "unknown":
            continue
        if code not in values:
            values.append(code)

    if not values:
        return ["en", "id"]

    for fallback in ("en", "id"):
        if fallback not in values:
            values.append(fallback)

    return values[:3]


def _build_subdl_config_path(api_key: str, language_codes: list[str]) -> str:
    raw = f"{api_key}/{','.join(language_codes)}/{_DEFAULT_HEARING_MODE}/"
    return base64.b64encode(raw.encode()).decode()


def _build_subsource_config_path(api_key: str, language_codes: list[str]) -> str:
    raw = f"{api_key}/{','.join(language_codes)}/{_DEFAULT_HEARING_MODE}/type:0/"
    return base64.b64encode(raw.encode()).decode()


def subtitle_source_is_configured(source_name: str) -> bool:
    lowered = source_name.strip().lower()
    if lowered == "subdl":
        return bool(get_secret(SUBDL_API_KEY_ENV, "").strip())
    if lowered == "subsource":
        return bool(get_secret(SUBSOURCE_API_KEY_ENV, "").strip())
    return True


def _looks_like_error_entry(entry: dict[str, Any]) -> bool:
    subtitle_id = str(entry.get("id") or "").lower()
    subtitle_url = str(entry.get("url") or "").lower()
    return subtitle_id.startswith("error_") or "/error-subtitle/" in subtitle_url


def _map_subtitle_entry(entry: dict[str, Any], source_name: str) -> ExternalSubtitle | None:
    url = str(entry.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None

    language_code = _normalise_language_code(str(entry.get("lang") or "").strip())
    subtitle_id = str(entry.get("id") or "").strip()
    label = subtitle_id or language_code

    return ExternalSubtitle(
        url=url,
        language=language_code,
        label=label,
        source=source_name,
    )


async def _fetch_json(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(
        headers=_DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


async def _fetch_opensubtitles(video_id: str, content_type: str) -> list[ExternalSubtitle]:
    payload = await _fetch_json(f"{_OPEN_SUBTITLES_URL}/subtitles/{content_type}/{video_id}.json")
    raw_subtitles = payload.get("subtitles")
    if not isinstance(raw_subtitles, list):
        return []

    mapped: list[ExternalSubtitle] = []
    for entry in raw_subtitles:
        if not isinstance(entry, dict):
            continue

        subtitle = _map_subtitle_entry(entry, "opensubtitles")
        if subtitle is None:
            continue
        mapped.append(subtitle)

    return mapped


async def _fetch_subdl(
    video_id: str, content_type: str, preferred_languages: list[str] | None
) -> list[ExternalSubtitle]:
    api_key = get_secret(SUBDL_API_KEY_ENV, "").strip()
    if not api_key:
        return []

    language_codes = _preferred_language_codes(preferred_languages)
    config_path = _build_subdl_config_path(api_key, language_codes)
    url = f"{_SUBDL_BASE_URL}/{config_path}/subtitles/{content_type}/{video_id}.json"

    payload = await _fetch_json(url)
    raw_subtitles = payload.get("subtitles")
    if not isinstance(raw_subtitles, list):
        return []

    mapped: list[ExternalSubtitle] = []
    for entry in raw_subtitles:
        if not isinstance(entry, dict):
            continue

        if _looks_like_error_entry(entry):
            continue

        subtitle = _map_subtitle_entry(entry, "subdl")
        if subtitle is None:
            continue
        mapped.append(subtitle)

    return mapped


async def _fetch_subsource(
    video_id: str,
    content_type: str,
    preferred_languages: list[str] | None,
) -> list[ExternalSubtitle]:
    api_key = get_secret(SUBSOURCE_API_KEY_ENV, "").strip()
    if not api_key:
        return []

    if not await _is_subsource_api_key_valid(api_key):
        raise RuntimeError("SubSource API key is invalid or expired")

    language_codes = _preferred_language_codes(preferred_languages)
    config_path = _build_subsource_config_path(api_key, language_codes)
    url = f"{_SUBSOURCE_BASE_URL}/{config_path}/subtitles/{content_type}/{video_id}.json"

    payload = await _fetch_json(url)
    raw_subtitles = payload.get("subtitles")
    if not isinstance(raw_subtitles, list):
        return []

    mapped: list[ExternalSubtitle] = []
    for entry in raw_subtitles:
        if not isinstance(entry, dict):
            continue

        if _looks_like_error_entry(entry):
            continue

        subtitle = _map_subtitle_entry(entry, "subsource")
        if subtitle is None:
            continue
        mapped.append(subtitle)

    return mapped


async def _is_subsource_api_key_valid(api_key: str) -> bool:
    cached = _SUBSOURCE_KEY_VALIDATION_CACHE.get(api_key)
    if cached is not None:
        return cached

    validation_url = f"{_SUBSOURCE_BASE_URL}/api/validate-api-key"
    try:
        async with httpx.AsyncClient(
            headers={**_DEFAULT_HEADERS, "Content-Type": "application/json"},
            follow_redirects=True,
            timeout=httpx.Timeout(15.0),
        ) as client:
            response = await client.post(validation_url, json={"apiKey": api_key})
            response.raise_for_status()
            payload = response.json()
            is_valid = bool(isinstance(payload, dict) and payload.get("valid") is True)
    except Exception:
        # Do not hard-fail on temporary network/endpoint issues.
        is_valid = True

    _SUBSOURCE_KEY_VALIDATION_CACHE[api_key] = is_valid
    return is_valid


async def fetch_external_subtitles(
    *,
    video_id: str,
    content_type: str,
    sources: list[str],
    preferred_languages: list[str] | None = None,
) -> list[ExternalSubtitle]:
    """Fetch subtitles from selected external subtitle providers."""

    valid_content_type = content_type.strip().lower()
    if valid_content_type not in {"movie", "series"}:
        return []

    requested_sources = []
    for source in sources:
        normalized = source.strip().lower()
        if normalized in {"opensubtitles", "subdl", "subsource"} and normalized not in requested_sources:
            requested_sources.append(normalized)

    if not requested_sources:
        return []

    subtitles: list[ExternalSubtitle] = []
    seen_urls: set[str] = set()
    source_errors: list[str] = []

    for source_name in requested_sources:
        try:
            if source_name == "opensubtitles":
                fetched = await _fetch_opensubtitles(video_id, valid_content_type)
            elif source_name == "subdl":
                fetched = await _fetch_subdl(video_id, valid_content_type, preferred_languages)
            else:
                fetched = await _fetch_subsource(video_id, valid_content_type, preferred_languages)
        except Exception as exc:
            source_errors.append(f"{source_name}: {exc}")
            fetched = []

        for subtitle in fetched:
            if subtitle.url in seen_urls:
                continue
            seen_urls.add(subtitle.url)
            subtitles.append(subtitle)

    if not subtitles and source_errors:
        raise RuntimeError("; ".join(source_errors))

    return subtitles
