"""CloudStream-style extractor helpers for the Filmkita-backed provider.

Copyright (c) 2026 Fajar Melfiano Obese Afoan Toan and Inggrit Setya Budi.

Personal Use Only License:
- Permission is granted to use, study, and modify this file for personal,
  non-commercial use only.
- Commercial use, resale, sublicensing, paid redistribution, or inclusion in
  commercial products or services is prohibited.
- This notice must be preserved in copies or substantial portions of this file.
- All other rights are reserved.

This provider replaces the previous unused CNCVerse-backed implementation.
It is translated from the user-supplied Filmkita CloudStream plugin and keeps
an internal CloudStream-like extractor/interceptor core for host dispatch.
"""

from __future__ import annotations

import ast
import base64
import json
import re
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from html import unescape
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from moviebox_api.providers.anime_common import (
    ResolvedMediaCandidate,
    dedupe_streams,
    extract_hls_variant_candidates,
    extract_nested_embed_urls,
    quality_rank,
    resolve_wrapped_stream_candidates,
)
from moviebox_api.providers.models import ProviderStream, ProviderSubtitle

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_MEDIA_URL_PATTERN = re.compile(
    r"(?:https?://|/)[^\"'\s<>]+\.(?:m3u8|mpd|mp4|mkv|webm|avi|mov|m4v|ts)(?:\?[^\"'\s<>]*)?",
    flags=re.I,
)
_PACKER_PATTERN = re.compile(
    r"\}\s*\('(.*)',\s*(.*?),\s*(\d+),\s*'(.*?)'\.split\('\|'\)",
    flags=re.S,
)
_HLS_ATTRIBUTE_PATTERN = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]+)')
_IMAGE_SEGMENT_PATTERN = re.compile(r'\.(?:jpg|jpeg|png|webp)(?:[?#].*)?$', flags=re.I)
_DUMMY_VIDEO_PATTERN = re.compile(r'/(?:error|notfound)\.mp4(?:[?#].*)?$', flags=re.I)
_MIXDROP_SOURCE_PATTERN = re.compile(r'wurl.*?=.*?"(.*?)";', flags=re.S)
_WORD_PATTERN = re.compile(r'\b[a-zA-Z0-9_]+\b')
_NODE_BINARY = shutil.which('node')


class _TextRequesterProtocol(Protocol):
    async def _request_text(
        self,
        path_or_url: str,
        *,
        referer: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[str, str]: ...


@dataclass(slots=True)
class CloudstreamInterceptor:
    """Merge per-stream headers in a CloudStream-like way."""

    user_agent: str = DEFAULT_USER_AGENT

    def headers_for(
        self,
        *,
        referer: str | None = None,
        origin: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        headers = {
            'User-Agent': self.user_agent,
            'Accept': '*/*',
        }
        for key, value in dict(extra or {}).items():
            if key and value:
                headers[str(key)] = str(value)
        if referer:
            headers['Referer'] = referer
        if origin:
            headers['Origin'] = origin
        return headers


class BaseCloudstreamExtractor:
    """Base extractor contract used by the local CloudStream core."""

    name = 'unknown'
    hosts: tuple[str, ...] = ()

    def matches(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return any(host.endswith(candidate) for candidate in self.hosts)

    async def extract(
        self,
        core: CloudstreamExtractorCore,
        url: str,
        *,
        referer: str | None = None,
    ) -> list[ProviderStream]:
        raise NotImplementedError


class EarnvidsExtractor(BaseCloudstreamExtractor):
    """Port of Filmkita's Earnvids-based extractor family."""

    name = 'earnvids'
    hosts = (
        'bingezove.com',
        'dingtezuni.com',
        'mivalyo.com',
        'ryderjet.com',
        'movearnpre.com',
        'minochinos.com',
    )

    @staticmethod
    def _embed_url(url: str) -> str:
        for source_path in ('/d/', '/download/', '/file/', '/f/'):
            if source_path in url:
                return url.replace(source_path, '/v/')
        return url

    async def extract(
        self,
        core: CloudstreamExtractorCore,
        url: str,
        *,
        referer: str | None = None,
    ) -> list[ProviderStream]:
        embed_url = self._embed_url(url)
        parsed = urlparse(embed_url)
        origin = f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme and parsed.netloc else None
        headers = core.interceptor.headers_for(referer=referer or url, origin=origin)
        try:
            response = await core._client.get(embed_url, headers=headers)
            response.raise_for_status()
        except Exception:
            return []

        html = response.text
        subtitles = _collect_html_subtitles(html, str(response.url))
        source_name = f'cloudstream:{_host_label(url)}'

        texts_to_scan = [html]
        for script in _extract_packer_scripts(html):
            unpacked = _unpack_packer_script(script)
            if unpacked:
                texts_to_scan.append(unpacked)

        candidates: list[ResolvedMediaCandidate] = []
        seen: set[str] = set()
        for text in texts_to_scan:
            for matched in _MEDIA_URL_PATTERN.findall(text):
                candidate_url = urljoin(str(response.url), unescape(matched))
                if candidate_url in seen:
                    continue
                seen.add(candidate_url)
                candidates.append(ResolvedMediaCandidate(url=candidate_url, headers=headers))

        if not candidates:
            return []

        validated = await core._validate_candidates(candidates, referer=embed_url)
        return await core._streams_from_candidates(
            validated,
            source=source_name,
            referer=embed_url,
            extra_headers=headers,
            subtitles=subtitles,
        )



class GdriveplayerExtractor(BaseCloudstreamExtractor):
    """Port of CloudStream's AES-based Gdriveplayer extractor."""

    name = 'gdriveplayer'
    hosts = (
        'databasegdriveplayer.co',
        'series.databasegdriveplayer.co',
        'gdriveplayerapi.com',
        'gdriveplayer.app',
        'gdriveplayer.fun',
        'gdriveplayer.io',
        'gdriveplayer.me',
        'gdriveplayer.biz',
        'gdriveplayer.org',
        'gdriveplayer.us',
        'gdriveplayer.co',
        'gdriveplayer.to',
    )

    async def extract(
        self,
        core: CloudstreamExtractorCore,
        url: str,
        *,
        referer: str | None = None,
    ) -> list[ProviderStream]:
        parsed = urlparse(url)
        main_url = f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme and parsed.netloc else url
        headers = core.interceptor.headers_for(referer=referer or url, origin=main_url)
        try:
            response = await core._client.get(url, headers=headers)
            response.raise_for_status()
        except Exception:
            return []

        decrypted_source = ''
        for script in _extract_packer_scripts(response.text):
            unpacked = _unpack_packer_script(script)
            if unpacked and "data='" in unpacked:
                decrypted_source = unpacked.replace('\\', '')
                break
        if not decrypted_source:
            return []

        data_match = re.search(r"data='(\S+?)'", decrypted_source)
        password_match = re.search(r"null,['\"](\w+)['\"]", decrypted_source)
        if data_match is None or password_match is None:
            return []

        password_script = _decode_digit_obfuscation(password_match.group(1))
        password_value = re.search(r'var pass = \"(\S+?)\"', password_script)
        if password_value is None:
            return []

        decrypted_payload = _decrypt_gdriveplayer_payload(
            data_match.group(1),
            password_value.group(1),
        )
        if not decrypted_payload:
            return []

        decoded_payload = _decode_javascript_string_literal(decrypted_payload)
        unpacked_payload = _unpack_packer_script(decoded_payload) or decoded_payload
        source_data = _slice_javascript_array(unpacked_payload, 'sources')
        track_data = _slice_javascript_array(unpacked_payload, 'tracks')
        if not source_data:
            return []

        source_entries = _evaluate_javascript_array(source_data, referer or '')
        track_entries = _evaluate_javascript_array(track_data, referer or '') if track_data else []
        subtitles = _subtitles_from_entries(track_entries)

        candidates: list[ResolvedMediaCandidate] = []
        seen_keys: set[tuple[str, str]] = set()
        for entry in source_entries:
            raw_url = _normalize_javascript_url(entry.get('file') or '')
            if not raw_url:
                continue
            quality = _quality_from_cloudstream_entry(entry)
            dedupe_key = (
                quality or '',
                re.sub(r'([?&])t=\d+', r'\1t=', raw_url),
            )
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            candidates.append(
                ResolvedMediaCandidate(
                    url=raw_url,
                    quality=quality,
                    headers={'Range': 'bytes=0-'},
                )
            )

        if not candidates:
            return []

        validated = await core._validate_candidates(candidates, referer=main_url)
        return await core._streams_from_candidates(
            validated,
            source='cloudstream:gdriveplayer',
            referer=main_url,
            extra_headers={'Range': 'bytes=0-'},
            subtitles=subtitles,
        )


class MixDropExtractor(BaseCloudstreamExtractor):
    """Port of CloudStream's MixDrop extractor for Filmkita fallback mirrors."""

    name = 'mixdrop'
    hosts = (
        'mixdrop.co',
        'mixdrop.ps',
        'mixdrop.bz',
        'mixdrop.ag',
        'mixdrop.ch',
        'mixdrop.to',
        'mixdrop.si',
        'mxdrop.to',
        'mdy48tn97.com',
    )

    async def extract(
        self,
        core: CloudstreamExtractorCore,
        url: str,
        *,
        referer: str | None = None,
    ) -> list[ProviderStream]:
        embed_url = url.replace('/f/', '/e/')
        headers = core.interceptor.headers_for(referer=referer or url)
        try:
            response = await core._client.get(embed_url, headers=headers)
            response.raise_for_status()
        except Exception:
            return []

        unpacked = _unpack_packer_script(response.text)
        match = _MIXDROP_SOURCE_PATTERN.search(unpacked or response.text)
        if match is None:
            return []

        stream_url = _normalize_javascript_url(match.group(1))
        if not stream_url:
            return []

        return await core._streams_from_url(
            stream_url,
            source='cloudstream:mixdrop',
            referer=str(response.url),
            headers={'Referer': str(response.url)},
            depth=1,
            seen={url},
        )


class LayarwibuExtractor(BaseCloudstreamExtractor):
    """Port of Filmkita's player2/base64 HLS extractor."""

    name = 'layarwibu'
    hosts = (
        'hls-bekop.layarwibu.com',
        'hls-terea.layarwibu.com',
    )

    def matches(self, url: str) -> bool:
        parsed = urlparse(url)
        if '/player2/' in parsed.path.lower():
            return True
        return super().matches(url)

    async def extract(
        self,
        core: CloudstreamExtractorCore,
        url: str,
        *,
        referer: str | None = None,
    ) -> list[ProviderStream]:
        decoded_url = _decode_player2_target(url) or url
        parent_url = decoded_url.rsplit('/', maxsplit=1)[0] if '/' in decoded_url else decoded_url
        headers = core.interceptor.headers_for(referer=parent_url, origin=parent_url)
        source_name = _layarwibu_source_label(url)
        streams = await core._streams_from_url(
            decoded_url,
            source=source_name,
            referer=parent_url,
            headers=headers,
            depth=1,
            seen={url},
        )
        return sorted(
            streams,
            key=lambda stream: (_layarwibu_stability_score(stream), -quality_rank(stream.quality)),
        )


class CloudstreamExtractorCore:
    """Minimal local clone of CloudStream's extractor dispatch behavior."""

    def __init__(
        self,
        requester: _TextRequesterProtocol,
        client: httpx.AsyncClient,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self._requester = requester
        self._client = client
        self.interceptor = CloudstreamInterceptor(user_agent=user_agent)
        self._extractors: tuple[BaseCloudstreamExtractor, ...] = (
            EarnvidsExtractor(),
            GdriveplayerExtractor(),
            MixDropExtractor(),
            LayarwibuExtractor(),
        )

    async def load_extractor(
        self,
        url: str,
        *,
        referer: str | None = None,
        depth: int = 0,
        seen: set[str] | None = None,
    ) -> list[ProviderStream]:
        normalized_url = str(url or '').strip()
        if not normalized_url:
            return []

        visited = seen if seen is not None else set()
        if normalized_url in visited or depth > 4:
            return []
        visited.add(normalized_url)

        parsed = urlparse(normalized_url)
        if not parsed.scheme or not parsed.netloc:
            return []

        for extractor in self._extractors:
            if extractor.matches(normalized_url):
                streams = await extractor.extract(self, normalized_url, referer=referer)
                if streams:
                    return dedupe_streams(streams)

        wrapped_candidates = await resolve_wrapped_stream_candidates(
            self._requester,
            normalized_url,
            referer=referer,
        )
        if wrapped_candidates:
            streams = await self._streams_from_candidates(
                wrapped_candidates,
                source=f'cloudstream:{_host_label(normalized_url)}',
                referer=referer or normalized_url,
            )
            if streams:
                return dedupe_streams(streams)

        return await self._streams_from_url(
            normalized_url,
            source=f'cloudstream:{_host_label(normalized_url)}',
            referer=referer,
            depth=depth,
            seen=visited,
        )

    async def _validate_candidates(
        self,
        candidates: Iterable[ResolvedMediaCandidate],
        *,
        referer: str | None = None,
    ) -> list[ResolvedMediaCandidate]:
        validated: list[ResolvedMediaCandidate] = []
        for candidate in candidates:
            request_headers = self.interceptor.headers_for(
                referer=referer,
                extra=candidate.headers,
            )
            try:
                response = await self._client.get(candidate.url, headers=request_headers)
                response.raise_for_status()
            except Exception:
                continue

            final_url = str(response.url)
            content_type = str(response.headers.get('content-type') or '').lower()
            if _looks_like_dummy_media(final_url):
                continue
            if content_type.startswith('audio/') or 'text/html' in content_type:
                continue
            if _IMAGE_SEGMENT_PATTERN.search(urlparse(final_url).path):
                continue

            stream_type = candidate.stream_type
            if 'mpegurl' in content_type or final_url.lower().endswith('.m3u8'):
                stream_type = 'hls'
            elif 'application/dash+xml' in content_type or final_url.lower().endswith('.mpd'):
                stream_type = 'dash'

            validated.append(
                ResolvedMediaCandidate(
                    url=final_url,
                    quality=candidate.quality,
                    headers=dict(candidate.headers),
                    stream_type=stream_type,
                )
            )
        return validated

    async def _streams_from_candidates(
        self,
        candidates: Iterable[ResolvedMediaCandidate],
        *,
        source: str,
        referer: str | None = None,
        extra_headers: dict[str, str] | None = None,
        subtitles: list[ProviderSubtitle] | None = None,
    ) -> list[ProviderStream]:
        streams: list[ProviderStream] = []
        for candidate in candidates:
            headers = dict(extra_headers or {})
            headers.update(candidate.headers or {})
            streams.extend(
                await self._streams_from_url(
                    candidate.url,
                    source=source,
                    referer=referer,
                    headers=headers,
                    quality=candidate.quality,
                    subtitles=subtitles,
                )
            )
        return dedupe_streams(streams)

    async def _streams_from_url(
        self,
        url: str,
        *,
        source: str,
        referer: str | None = None,
        headers: dict[str, str] | None = None,
        quality: str | None = None,
        subtitles: list[ProviderSubtitle] | None = None,
        depth: int = 0,
        seen: set[str] | None = None,
    ) -> list[ProviderStream]:
        request_headers = self.interceptor.headers_for(referer=referer, extra=headers)
        try:
            response = await self._client.get(url, headers=request_headers)
            response.raise_for_status()
        except Exception:
            return []
        return await self._streams_from_response(
            response,
            source=source,
            referer=referer,
            headers=request_headers,
            quality=quality,
            subtitles=subtitles,
            depth=depth,
            seen=seen,
        )

    async def _streams_from_response(
        self,
        response: httpx.Response,
        *,
        source: str,
        referer: str | None = None,
        headers: dict[str, str] | None = None,
        quality: str | None = None,
        subtitles: list[ProviderSubtitle] | None = None,
        depth: int = 0,
        seen: set[str] | None = None,
    ) -> list[ProviderStream]:
        current_url = str(response.url)
        content_type = str(response.headers.get('content-type') or '').lower()
        if _looks_like_dummy_media(current_url):
            return []
        if content_type.startswith('audio/'):
            return []
        if _IMAGE_SEGMENT_PATTERN.search(urlparse(current_url).path):
            return []

        response_text = ''
        if (
            'text/' in content_type
            or 'json' in content_type
            or 'xml' in content_type
            or 'mpegurl' in content_type
        ):
            response_text = response.text
        elif current_url.lower().endswith('.m3u8'):
            response_text = response.text

        merged_subtitles = list(subtitles or [])

        if (
            'mpegurl' in content_type
            or current_url.lower().endswith('.m3u8')
            or response_text.startswith('#EXTM3U')
        ):
            merged_subtitles = _merge_subtitles(
                merged_subtitles,
                _extract_hls_subtitles(response_text, current_url),
            )
            variant_candidates = extract_hls_variant_candidates(
                response_text,
                base_url=current_url,
                headers=dict(headers or {}),
            )
            if variant_candidates:
                streams = [
                    ProviderStream(
                        url=candidate.url,
                        source=source,
                        quality=candidate.quality or quality,
                        headers=dict(candidate.headers or headers or {}),
                        subtitles=list(merged_subtitles),
                    )
                    for candidate in variant_candidates
                ]
                return _sort_streams(streams)

            return [
                ProviderStream(
                    url=current_url,
                    source=source,
                    quality=quality or _quality_hint(current_url),
                    headers=dict(headers or {}),
                    subtitles=list(merged_subtitles),
                )
            ]

        if 'application/dash+xml' in content_type or current_url.lower().endswith('.mpd'):
            return [
                ProviderStream(
                    url=current_url,
                    source=source,
                    quality=quality or _quality_hint(current_url),
                    headers=dict(headers or {}),
                    subtitles=list(merged_subtitles),
                )
            ]

        if content_type.startswith('video/') or current_url.lower().endswith(
            ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v', '.ts')
        ):
            return [
                ProviderStream(
                    url=current_url,
                    source=source,
                    quality=quality or _quality_hint(current_url),
                    headers=dict(headers or {}),
                    subtitles=list(merged_subtitles),
                )
            ]

        if 'text/html' not in content_type and response_text:
            direct_urls = _extract_media_urls_from_text(response_text, current_url)
            if direct_urls:
                candidates = [
                    ResolvedMediaCandidate(url=direct_url, headers=dict(headers or {}))
                    for direct_url in direct_urls
                ]
                validated = await self._validate_candidates(
                    candidates,
                    referer=referer or current_url,
                )
                return await self._streams_from_candidates(
                    validated,
                    source=source,
                    referer=referer or current_url,
                    extra_headers=headers,
                    subtitles=merged_subtitles,
                )
            return []

        html = response_text or response.text
        html_subtitles = _collect_html_subtitles(html, current_url)
        merged_subtitles = _merge_subtitles(merged_subtitles, html_subtitles)

        direct_urls = _extract_media_urls_from_text(html, current_url)
        streams: list[ProviderStream] = []
        if direct_urls:
            candidates = [
                ResolvedMediaCandidate(url=direct_url, headers=dict(headers or {}))
                for direct_url in direct_urls
            ]
            validated = await self._validate_candidates(
                candidates,
                referer=referer or current_url,
            )
            streams.extend(
                await self._streams_from_candidates(
                    validated,
                    source=source,
                    referer=referer or current_url,
                    extra_headers=headers,
                    subtitles=merged_subtitles,
                )
            )

        nested_urls = extract_nested_embed_urls(html, base_url=current_url)
        visited = seen if seen is not None else {current_url}
        for nested_url in nested_urls:
            streams.extend(
                await self.load_extractor(
                    nested_url,
                    referer=current_url,
                    depth=depth + 1,
                    seen=visited,
                )
            )

        return dedupe_streams(streams)


def _extract_hls_subtitles(playlist_text: str, base_url: str) -> list[ProviderSubtitle]:
    subtitles: list[ProviderSubtitle] = []
    seen: set[str] = set()
    for raw_line in str(playlist_text or '').splitlines():
        line = raw_line.strip()
        if not line.startswith('#EXT-X-MEDIA:'):
            continue
        attributes = _hls_attribute_map(line.partition(':')[2])
        if str(attributes.get('TYPE') or '').upper() != 'SUBTITLES':
            continue
        uri = str(attributes.get('URI') or '').strip()
        if not uri:
            continue
        subtitle_url = urljoin(base_url, uri)
        if subtitle_url in seen:
            continue
        seen.add(subtitle_url)
        subtitles.append(
            ProviderSubtitle(
                url=subtitle_url,
                language=str(attributes.get('LANGUAGE') or attributes.get('NAME') or 'unknown'),
                label=str(attributes.get('NAME') or attributes.get('LANGUAGE') or '').strip() or None,
            )
        )
    return subtitles


def _collect_html_subtitles(html: str, base_url: str) -> list[ProviderSubtitle]:
    soup = BeautifulSoup(html or '', 'html.parser')
    subtitles: list[ProviderSubtitle] = []
    seen: set[str] = set()
    for track in soup.select('track[src], source[src][kind="captions"]'):
        raw_url = str(track.get('src') or '').strip()
        if not raw_url:
            continue
        subtitle_url = urljoin(base_url, raw_url)
        if subtitle_url in seen:
            continue
        seen.add(subtitle_url)
        language = str(track.get('srclang') or track.get('label') or 'unknown').strip() or 'unknown'
        label = str(track.get('label') or language).strip() or None
        subtitles.append(ProviderSubtitle(url=subtitle_url, language=language, label=label))
    return subtitles


def _merge_subtitles(*groups: Iterable[ProviderSubtitle]) -> list[ProviderSubtitle]:
    merged: dict[str, ProviderSubtitle] = {}
    for group in groups:
        for subtitle in group:
            if subtitle.url:
                merged[subtitle.url] = subtitle
    return list(merged.values())


def _hls_attribute_map(raw_value: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for key, value in _HLS_ATTRIBUTE_PATTERN.findall(raw_value or ''):
        cleaned_value = str(value).strip()
        if cleaned_value.startswith('"') and cleaned_value.endswith('"'):
            cleaned_value = cleaned_value[1:-1]
        attributes[str(key).strip().upper()] = cleaned_value
    return attributes


def _sort_streams(streams: list[ProviderStream]) -> list[ProviderStream]:
    return sorted(streams, key=lambda stream: quality_rank(stream.quality), reverse=True)


def _quality_hint(url: str) -> str | None:
    matched = re.search(r'(2160|1440|1080|720|480|360)p', str(url or '').lower())
    if matched:
        return f'{matched.group(1)}p'
    return None


def _host_label(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if not host:
        return 'direct'
    parts = [part for part in host.split('.') if part and part not in {'www'}]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0]


def _layarwibu_source_label(url: str) -> str:
    lowered = str(url or '').lower()
    if 'terea' in lowered:
        return 'cloudstream:alkhalifitv-2'
    if 'bekop' in lowered:
        return 'cloudstream:alkhalifitv-1'
    return 'cloudstream:layarwibu'


def _layarwibu_stability_score(stream: ProviderStream) -> int:
    rank = quality_rank(stream.quality)
    if 700 <= rank < 900:
        return 0
    if 400 <= rank < 700:
        return 1
    if rank >= 900:
        return 2
    return 3



def _looks_like_dummy_media(url: str) -> bool:
    lowered = str(url or '').lower()
    return bool(_DUMMY_VIDEO_PATTERN.search(urlparse(lowered).path) or 'reason=folder' in lowered)


def _decode_digit_obfuscation(encoded: str) -> str:
    parts = [part for part in re.split(r'\D+', str(encoded or '')) if part]
    chars: list[str] = []
    for part in parts:
        try:
            chars.append(chr(int(part)))
        except ValueError:
            continue
    return ''.join(chars)


def _decode_javascript_string_literal(value: str) -> str:
    text = str(value or '').strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'\"', "'"}:
        try:
            return str(ast.literal_eval(text))
        except Exception:
            return text[1:-1]
    return text


def _node_eval(script: str, *, input_text: str = '', args: list[str] | None = None) -> str:
    if not _NODE_BINARY:
        return ''
    try:
        completed = subprocess.run(
            [_NODE_BINARY, '-e', script, *(args or [])],
            input=input_text,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            check=True,
            timeout=30,
        )
    except Exception:
        return ''
    return str(completed.stdout or '')


def _decrypt_gdriveplayer_payload(data: str, password: str) -> str:
    script = '''
const crypto = require('crypto');
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const password = Buffer.from(process.argv[1] || '', 'utf8');
const salt = Buffer.from(payload.s, 'hex');
const iv = Buffer.from(payload.iv, 'hex');
const target = 32 + iv.length;
let generated = Buffer.alloc(0);
let block = Buffer.alloc(0);
while (generated.length < target) {
  const hash = crypto.createHash('md5');
  if (block.length) hash.update(block);
  hash.update(password);
  hash.update(salt);
  block = hash.digest();
  generated = Buffer.concat([generated, block]);
}
const key = generated.subarray(0, 32);
const decipher = crypto.createDecipheriv('aes-256-cbc', key, iv);
decipher.setAutoPadding(false);
const decrypted = Buffer.concat([
  decipher.update(Buffer.from(payload.ct, 'base64')),
  decipher.final(),
]);
process.stdout.write(decrypted.toString('utf8'));
'''
    return _node_eval(script, input_text=data, args=[password])


def _evaluate_javascript_array(source_data: str, referrer: str) -> list[dict[str, object]]:
    if not str(source_data or '').strip():
        return []
    script = '''
const fs = require('fs');
const document = { referrer: process.argv[1] || '' };
const sourceData = fs.readFileSync(0, 'utf8');
const factory = new Function('document', `return [${sourceData}];`);
const value = factory(document);
process.stdout.write(JSON.stringify(value));
'''
    raw_output = _node_eval(script, input_text=source_data, args=[referrer])
    if not raw_output:
        return []
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _slice_javascript_array(script_text: str, key: str) -> str:
    needle = f'{key}:['
    start_index = str(script_text or '').find(needle)
    if start_index == -1:
        return ''
    index = start_index + len(needle)
    depth = 1
    in_string: str | None = None
    escaped = False
    collected: list[str] = []
    while index < len(script_text):
        char = script_text[index]
        if in_string is not None:
            collected.append(char)
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == in_string:
                in_string = None
            index += 1
            continue

        if char in {'\"', "'"}:
            in_string = char
            collected.append(char)
            index += 1
            continue
        if char == '[':
            depth += 1
            collected.append(char)
            index += 1
            continue
        if char == ']':
            depth -= 1
            if depth == 0:
                return ''.join(collected).strip()
            collected.append(char)
            index += 1
            continue
        collected.append(char)
        index += 1
    return ''


def _normalize_javascript_url(value: object) -> str:
    normalized = str(value or '').strip().replace('\\/', '/')
    if normalized.startswith('//'):
        return f'https:{normalized}'
    return normalized


def _subtitles_from_entries(entries: list[dict[str, object]]) -> list[ProviderSubtitle]:
    subtitles: list[ProviderSubtitle] = []
    seen: set[str] = set()
    for entry in entries:
        kind = str(entry.get('kind') or '').lower()
        if kind and kind not in {'captions', 'subtitles'}:
            continue
        subtitle_url = _normalize_javascript_url(entry.get('file') or '')
        if not subtitle_url or subtitle_url in seen:
            continue
        seen.add(subtitle_url)
        label = str(entry.get('label') or '').strip() or None
        subtitles.append(
            ProviderSubtitle(
                url=subtitle_url,
                language=label or 'unknown',
                label=label,
            )
        )
    return subtitles


def _quality_from_cloudstream_entry(entry: dict[str, object]) -> str | None:
    for key in ('label', 'res', 'quality'):
        raw_value = str(entry.get(key) or '').strip()
        matched = re.search(r'(2160|1440|1080|720|480|360)', raw_value)
        if matched:
            return f'{matched.group(1)}p'
    return _quality_hint(str(entry.get('file') or ''))


def _decode_player2_target(url: str) -> str | None:
    encoded = str(url or '').partition('/player2/')[2].strip()
    if not encoded:
        return None
    padded = encoded + ('=' * (-len(encoded) % 4))
    try:
        decoded = base64.b64decode(padded).decode('utf-8', errors='ignore').strip()
    except Exception:
        return None
    return decoded or None


def _extract_media_urls_from_text(text: str, base_url: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    soup = BeautifulSoup(text or '', 'html.parser')
    for selector, attribute in (
        ('video[src]', 'src'),
        ('source[src]', 'src'),
        ('a[href]', 'href'),
    ):
        for element in soup.select(selector):
            raw_value = str(element.get(attribute) or '').strip()
            if not raw_value:
                continue
            if not _MEDIA_URL_PATTERN.search(raw_value):
                continue
            candidate_url = urljoin(base_url, unescape(raw_value))
            if candidate_url in seen:
                continue
            seen.add(candidate_url)
            candidates.append(candidate_url)

    texts_to_scan = [text]
    for script in _extract_packer_scripts(text or ''):
        unpacked = _unpack_packer_script(script)
        if unpacked:
            texts_to_scan.append(unpacked)

    for chunk in texts_to_scan:
        for matched in _MEDIA_URL_PATTERN.findall(chunk):
            candidate_url = urljoin(base_url, unescape(matched))
            if candidate_url in seen:
                continue
            seen.add(candidate_url)
            candidates.append(candidate_url)
    return candidates


def _extract_packer_scripts(html: str) -> list[str]:
    scripts: list[str] = []
    start_index = 0
    needle = 'eval(function(p,a,c,k,e,d){'
    while True:
        start_index = html.find(needle, start_index)
        if start_index == -1:
            break
        end_index = html.find('</script>', start_index)
        if end_index == -1:
            scripts.append(html[start_index:].strip())
            break
        scripts.append(html[start_index:end_index].strip())
        start_index = end_index + len('</script>')
    return scripts


def _unpack_packer_script(script: str) -> str:
    matched = _PACKER_PATTERN.search(script or '')
    if not matched:
        return ''

    payload, alphabet_size, symbol_count, replacements = matched.groups()
    payload = str(payload or '').replace("\\'", "'")
    try:
        base = int(str(alphabet_size).strip())
        int(symbol_count)
    except ValueError:
        return ''
    values = str(replacements or '').split('|')
    alphabet = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'

    def unbase(word: str) -> int:
        if base <= 36:
            return int(word, base)
        dictionary = {character: index for index, character in enumerate(alphabet[:base])}
        value = 0
        for character in word:
            if character not in dictionary:
                return -1
            value = (value * base) + dictionary[character]
        return value

    def replace_word(match: re.Match[str]) -> str:
        word = match.group(0)
        try:
            index = unbase(word)
        except Exception:
            return word
        if 0 <= index < len(values) and values[index]:
            return values[index]
        return word

    return _WORD_PATTERN.sub(replace_word, payload)
