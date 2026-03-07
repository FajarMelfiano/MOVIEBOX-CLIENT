"""Subtitle fetch helpers for OpenSubtitles, SubDL, and SubSource."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

import httpx

from moviebox_api.language import normalize_language_id, to_iso639_1
from moviebox_api.security.secrets import get_secret

SUBDL_API_KEY_ENV = "MOVIEBOX_SUBDL_API_KEY"
SUBSOURCE_API_KEY_ENV = "MOVIEBOX_SUBSOURCE_API_KEY"
SUBTITLE_PROXY_URL_ENV = "MOVIEBOX_SUBTITLE_PROXY_URL"
SUBTITLE_PROXY_AUTH_TOKEN_ENV = "MOVIEBOX_SUBTITLE_PROXY_AUTH_TOKEN"
SUBTITLE_PROXY_DISABLE_ENV = "MOVIEBOX_SUBTITLE_PROXY_DISABLE"

_DEFAULT_SUBTITLE_PROXY_URL = "https://roowyrmfytbldcdvagbp.supabase.co/functions/v1/subtitle-proxy"

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

_SUBDL_KEY_VALIDATION_CACHE: dict[str, bool | None] = {}
_SUBSOURCE_KEY_VALIDATION_CACHE: dict[str, bool | None] = {}


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
    if lowered in {"subdl", "subsource"} and subtitle_proxy_is_configured():
        return True

    if lowered == "subdl":
        return bool(get_secret(SUBDL_API_KEY_ENV, "").strip())
    if lowered == "subsource":
        return bool(get_secret(SUBSOURCE_API_KEY_ENV, "").strip())
    return True


def subtitle_proxy_url() -> str:
    disabled_value = os.getenv(SUBTITLE_PROXY_DISABLE_ENV, "").strip().lower()
    if disabled_value in {"1", "true", "yes", "on"}:
        return ""

    configured = os.getenv(SUBTITLE_PROXY_URL_ENV, "").strip()
    if configured:
        return configured

    return _DEFAULT_SUBTITLE_PROXY_URL


def subtitle_proxy_is_configured() -> bool:
    return bool(subtitle_proxy_url())


def _subtitle_proxy_headers() -> dict[str, str]:
    headers = dict(_DEFAULT_HEADERS)
    token = os.getenv(SUBTITLE_PROXY_AUTH_TOKEN_ENV, "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["apikey"] = token
    return headers


def _map_proxy_subtitle_entry(entry: dict[str, Any]) -> ExternalSubtitle | None:
    url = str(entry.get("url") or entry.get("link") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None

    language_raw = str(
        entry.get("lang")
        or entry.get("language")
        or entry.get("language_id")
        or entry.get("languageCode")
        or ""
    ).strip()
    language_code = _normalise_language_code(language_raw)

    subtitle_id = str(entry.get("id") or "").strip()
    label = str(entry.get("label") or subtitle_id or language_code).strip()
    source_name = str(entry.get("source") or "subtitle-proxy").strip().lower()
    return ExternalSubtitle(url=url, language=language_code, label=label, source=source_name)


async def _fetch_subtitle_proxy(
    *,
    video_id: str,
    content_type: str,
    sources: list[str],
    preferred_languages: list[str] | None,
) -> tuple[list[ExternalSubtitle], list[str]]:
    proxy_url = subtitle_proxy_url()
    if not proxy_url:
        return [], []

    payload = {
        "video_id": video_id,
        "content_type": content_type,
        "sources": sources,
        "preferred_languages": preferred_languages or [],
    }

    async with httpx.AsyncClient(
        headers=_subtitle_proxy_headers(),
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
    ) as client:
        response = await client.post(proxy_url, json=payload)
        response.raise_for_status()
        body = response.json()

    raw_subtitles: list[Any] = []
    raw_errors: list[Any] = []

    if isinstance(body, list):
        raw_subtitles = list(body)
    elif isinstance(body, dict):
        raw_subtitles_candidate = body.get("subtitles")
        if not isinstance(raw_subtitles_candidate, list):
            raw_subtitles_candidate = body.get("results")
        if not isinstance(raw_subtitles_candidate, list):
            raw_subtitles_candidate = body.get("data")
        if isinstance(raw_subtitles_candidate, list):
            raw_subtitles = list(raw_subtitles_candidate)

        raw_errors_candidate = body.get("errors")
        if isinstance(raw_errors_candidate, list):
            raw_errors = list(raw_errors_candidate)

    subtitles: list[ExternalSubtitle] = []
    for entry in raw_subtitles:
        if not isinstance(entry, dict):
            continue
        mapped = _map_proxy_subtitle_entry(entry)
        if mapped is not None:
            subtitles.append(mapped)

    errors: list[str] = []
    for raw_error in raw_errors:
        if isinstance(raw_error, str):
            text = raw_error.strip()
            if text:
                errors.append(text)
            continue

        if isinstance(raw_error, dict):
            source_name = str(raw_error.get("source") or "subtitle-proxy").strip().lower()
            message = str(raw_error.get("message") or raw_error.get("error") or "unknown error").strip()
            if message:
                errors.append(f"{source_name}: {message}")

    return subtitles, errors


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

    is_key_valid = await _is_subdl_api_key_valid(api_key)
    if is_key_valid is False:
        raise RuntimeError("SubDL API key is invalid or expired")

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

    if not mapped and is_key_valid is None:
        raise RuntimeError(
            "SubDL returned no subtitles and key validation could not be verified. "
            "Check network access to api.subdl.com or use a fresh API key."
        )

    return mapped


async def _is_subdl_api_key_valid(api_key: str) -> bool | None:
    cached = _SUBDL_KEY_VALIDATION_CACHE.get(api_key)
    if cached is not None:
        return cached

    validation_url = "https://api.subdl.com/api/v1/subtitles"
    try:
        async with httpx.AsyncClient(
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(15.0),
        ) as client:
            response = await client.get(
                validation_url,
                params={"api_key": api_key, "film_name": "Inception"},
            )
            response.raise_for_status()
            payload = response.json()
            is_valid = bool(isinstance(payload, dict) and payload.get("status") is True)
    except Exception:
        is_valid = None

    _SUBDL_KEY_VALIDATION_CACHE[api_key] = is_valid
    return is_valid


async def _fetch_subsource(
    video_id: str,
    content_type: str,
    preferred_languages: list[str] | None,
) -> list[ExternalSubtitle]:
    api_key = get_secret(SUBSOURCE_API_KEY_ENV, "").strip()
    if not api_key:
        return []

    is_key_valid = await _is_subsource_api_key_valid(api_key)
    if is_key_valid is False:
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

    if not mapped and is_key_valid is None:
        raise RuntimeError(
            "SubSource returned no subtitles and key validation could not be verified. "
            "Check network access to subsource.strem.top or refresh API key."
        )

    return mapped


async def _is_subsource_api_key_valid(api_key: str) -> bool | None:
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
        is_valid = None

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

    proxy_sources = [
        source_name for source_name in requested_sources if source_name in {"subdl", "subsource"}
    ]
    use_proxy = subtitle_proxy_is_configured() and bool(proxy_sources)
    proxy_handled_sources: set[str] = set()

    if use_proxy:
        try:
            proxy_subtitles, proxy_errors = await _fetch_subtitle_proxy(
                video_id=video_id,
                content_type=valid_content_type,
                sources=proxy_sources,
                preferred_languages=preferred_languages,
            )
        except Exception as exc:
            source_errors.append(f"subtitle-proxy: {exc}")
            proxy_subtitles = []
            proxy_errors = []

        source_errors.extend(proxy_errors)
        for subtitle in proxy_subtitles:
            if subtitle.source in {"subdl", "subsource"}:
                proxy_handled_sources.add(subtitle.source)
            if subtitle.url in seen_urls:
                continue
            seen_urls.add(subtitle.url)
            subtitles.append(subtitle)

    for source_name in requested_sources:
        if use_proxy and source_name in {"subdl", "subsource"} and source_name in proxy_handled_sources:
            continue

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
