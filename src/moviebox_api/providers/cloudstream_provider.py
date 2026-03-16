"""Cloudstream Filmkita provider adapter.

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

import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from moviebox_api.constants import SubjectType
from moviebox_api.providers.anime_common import (
    configured_base_urls,
    dedupe_streams,
    parse_year,
    title_match_score,
)
from moviebox_api.providers.base import BaseStreamProvider
from moviebox_api.providers.cloudstream_core import DEFAULT_USER_AGENT, CloudstreamExtractorCore
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle

_ENV_CLOUDSTREAM_URLS = 'MOVIEBOX_CLOUDSTREAM_URLS'
_DEFAULT_BASE_URLS = (
    'https://filmkita.cloud',
    'https://3x.jalanmaxwin.site',
    'https://2x.jalanmaxwin.site',
)
_DEFAULT_HEADERS = {
    'User-Agent': DEFAULT_USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5,id;q=0.4',
}
_RESULT_RATING_PATTERN = re.compile(r'(\d+(?:\.\d+)?)')
_SEASON_PATTERN = re.compile(r'(?:season|s)\s*([0-9]{1,3})', flags=re.I)
_EPISODE_PATTERN = re.compile(r'(?:episode|ep|e)\s*([0-9]{1,4})', flags=re.I)
_TRAILING_NUMBER_PATTERN = re.compile(r'([0-9]{1,4})$')
_DIRECT_MEDIA_PATTERN = re.compile(
    r"(?:https?://|/)[^\"'\s<>]+\.(?:m3u8|mpd|mp4|mkv|webm|avi|mov|m4v|ts)(?:\?[^\"'\s<>]*)?",
    flags=re.I,
)


class CloudstreamProvider(BaseStreamProvider):
    """Movie and series provider backed by the Filmkita CloudStream plugin."""

    name = 'cloudstream'

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        base_urls: tuple[str, ...] | None = None,
    ):
        self._client = client or httpx.AsyncClient(
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=15.0),
        )
        self._base_urls = base_urls or configured_base_urls(
            (_ENV_CLOUDSTREAM_URLS,),
            _DEFAULT_BASE_URLS,
        )
        self._active_base_url: str | None = None
        self._extractor_core = CloudstreamExtractorCore(
            self,
            self._client,
            user_agent=_DEFAULT_HEADERS['User-Agent'],
        )

    async def search(
        self,
        query: str,
        subject_type: SubjectType,
        *,
        year: int | None = None,
        limit: int = 20,
    ) -> list[ProviderSearchResult]:
        raw_query = str(query or '').strip()
        if not raw_query:
            return []

        results_by_id: dict[str, ProviderSearchResult] = {}
        for search_query in _search_variants(raw_query):
            response_text, resolved_base_url = await self._request_text(
                f'/?s={quote_plus(search_query)}&post_type[]=post&post_type[]=tv',
            )
            soup = BeautifulSoup(response_text, 'html.parser')
            for article in soup.select('article.item'):
                search_result = self._search_result_from_article(
                    article,
                    resolved_base_url=resolved_base_url,
                    requested_subject_type=subject_type,
                )
                if search_result is None:
                    continue
                if year and search_result.year is not None and search_result.year != year:
                    continue
                results_by_id[search_result.id] = search_result
            if results_by_id:
                break

        results = list(results_by_id.values())
        results.sort(
            key=lambda item: self._score_result(
                raw_query,
                item,
                requested_subject_type=subject_type,
                year=year,
            ),
            reverse=True,
        )
        return results[:limit]

    async def search_best_match(
        self,
        query: str,
        subject_type: SubjectType,
        *,
        year: int | None = None,
    ) -> ProviderSearchResult | None:
        results = await self.search(query, SubjectType.ALL, year=year, limit=40)
        if not results:
            return None

        scored = sorted(
            results,
            key=lambda item: self._score_result(
                query,
                item,
                requested_subject_type=subject_type,
                year=year,
            ),
            reverse=True,
        )

        for item in scored:
            if year and item.year is not None and item.year != year:
                continue
            if subject_type != SubjectType.ALL:
                resolved_type = await self._resolve_subject_type(item)
                if resolved_type is not subject_type:
                    continue
            if self._score_result(query, item, requested_subject_type=subject_type, year=year) < 0.55:
                continue
            if item.year is None or not item.payload.get('episodes'):
                soup, page_url = await self._load_soup(item.page_url)
                analysis = self._analyze_document(soup, page_url)
                self._apply_analysis(item, analysis)
            return item
        return None

    async def resolve_streams(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderStream]:
        soup, page_url, analysis = await self._resolve_playback_page(
            item,
            season=season,
            episode=episode,
        )
        self._apply_analysis(item, analysis)

        embed_urls: list[str] = []
        player_container = soup.select_one('div#muvipro_player_content_id')
        if player_container and player_container.get('data-id'):
            post_id = str(player_container.get('data-id')).strip()
            tab_ids = [
                str(anchor.get('href') or '').lstrip('#').strip()
                for anchor in soup.select('ul.muvipro-player-tabs li a[href]')
                if str(anchor.get('href') or '').startswith('#')
            ]
            for tab_id in tab_ids:
                if not tab_id:
                    continue
                try:
                    tab_html = await self._load_player_tab(post_id, tab_id, page_url)
                except Exception:
                    continue
                embed_urls.extend(_extract_embed_urls(tab_html, page_url))

        if not embed_urls:
            embed_urls.extend(_extract_embed_urls(str(soup), page_url))

        streams: list[ProviderStream] = []
        seen_embed_urls: set[str] = set()
        for embed_url in embed_urls:
            if embed_url in seen_embed_urls:
                continue
            seen_embed_urls.add(embed_url)
            streams.extend(await self._extractor_core.load_extractor(embed_url, referer=page_url))

        return dedupe_streams(streams)

    async def resolve_subtitles(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderSubtitle]:
        streams = await self.resolve_streams(item, season=season, episode=episode)
        dedup: dict[str, ProviderSubtitle] = {}
        for stream in streams:
            for subtitle in stream.subtitles:
                dedup[subtitle.url] = subtitle
        return list(dedup.values())

    async def _resolve_playback_page(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> tuple[BeautifulSoup, str, dict[str, Any]]:
        soup, page_url = await self._load_soup(item.page_url)
        analysis = self._analyze_document(soup, page_url)
        self._apply_analysis(item, analysis)

        episodes = list(analysis.get('episodes') or [])
        if not episodes:
            return soup, page_url, analysis

        selected_episode = _select_episode_entry(episodes, season=season, episode=episode)
        if not selected_episode:
            return soup, page_url, analysis

        selected_url = str(selected_episode.get('url') or '').strip()
        if not selected_url or selected_url == page_url:
            return soup, page_url, analysis

        episode_soup, episode_page_url = await self._load_soup(selected_url, referer=page_url)
        episode_analysis = self._analyze_document(episode_soup, episode_page_url)
        episode_analysis['selected_episode'] = dict(selected_episode)
        return episode_soup, episode_page_url, episode_analysis

    async def _resolve_subject_type(self, item: ProviderSearchResult) -> SubjectType:
        if not item.payload.get('subject_type_inferred', False):
            return item.subject_type

        soup, page_url = await self._load_soup(item.page_url)
        analysis = self._analyze_document(soup, page_url)
        self._apply_analysis(item, analysis)
        return item.subject_type

    def _apply_analysis(self, item: ProviderSearchResult, analysis: dict[str, Any]) -> None:
        if analysis.get('title'):
            item.title = str(analysis['title'])
        if item.year is None and isinstance(analysis.get('year'), int):
            item.year = int(analysis['year'])
        if analysis.get('subject_type'):
            item.subject_type = analysis['subject_type']
            item.payload['subject_type_inferred'] = False
        item.payload.update({
            'poster_url': analysis.get('poster_url') or item.payload.get('poster_url'),
            'description': analysis.get('description') or item.payload.get('description'),
            'genres': list(analysis.get('genres') or item.payload.get('genres') or []),
            'episodes': list(analysis.get('episodes') or item.payload.get('episodes') or []),
            'page_url': analysis.get('page_url') or item.page_url,
        })

    def _analyze_document(self, soup: BeautifulSoup, page_url: str) -> dict[str, Any]:
        raw_title = soup.select_one('h1.entry-title')
        title_text = raw_title.get_text(' ', strip=True) if raw_title else ''
        title = _clean_title(title_text) or _title_from_path(page_url)
        year = parse_year(_extract_detail_year(soup) or title)
        poster_element = soup.select_one('figure.pull-left img, div.content-thumbnail img, img')
        poster_url = _image_url(poster_element, page_url)
        description = _node_text(soup.select_one('div[itemprop=description] p'))
        genres = _extract_detail_genres(soup)
        episodes = _extract_episode_entries(soup, page_url, page_title=title)
        subject_type = SubjectType.TV_SERIES if episodes else SubjectType.MOVIES
        return {
            'title': title,
            'year': year,
            'poster_url': poster_url,
            'description': description,
            'genres': genres,
            'episodes': episodes,
            'page_url': page_url,
            'subject_type': subject_type,
        }

    def _search_result_from_article(
        self,
        article: Any,
        *,
        resolved_base_url: str,
        requested_subject_type: SubjectType,
    ) -> ProviderSearchResult | None:
        anchor = article.select_one('h2.entry-title > a[href]') or article.select_one('a[href]')
        if anchor is None:
            return None

        title = str(anchor.get_text(' ', strip=True) or '').strip()
        href = str(anchor.get('href') or '').strip()
        if not title or not href:
            return None

        page_url = urljoin(resolved_base_url, href)
        quality_node = article.select_one('div.gmr-qual, div.gmr-quality-item > a')
        quality_text = quality_node.get_text(' ', strip=True) if quality_node else ''
        quality_hint = str(quality_text).replace('-', '').strip()
        rating_text = _node_text(article.select_one('div.gmr-rating-item'))
        rating = _parse_rating(rating_text)
        episode_badge = _extract_episode_number(_node_text(article.select_one('div.gmr-numbeps > span')))

        if episode_badge or _is_series_title(title) or _is_series_url(page_url):
            subject_type = SubjectType.TV_SERIES
            inferred = False
        elif quality_hint:
            subject_type = SubjectType.MOVIES
            inferred = False
        elif requested_subject_type != SubjectType.ALL:
            subject_type = requested_subject_type
            inferred = True
        else:
            subject_type = SubjectType.MOVIES
            inferred = True

        poster_url = _image_url(article.select_one('a > img, img'), resolved_base_url)
        search_result = ProviderSearchResult(
            id=page_url,
            title=_clean_title(title) or title,
            page_url=page_url,
            subject_type=subject_type,
            year=parse_year(title),
            payload={
                'page_url': page_url,
                'relative_path': _relative_path(page_url),
                'poster_url': poster_url,
                'rating': rating,
                'quality_hint': quality_hint or None,
                'episode_hint': episode_badge,
                'subject_type_inferred': inferred,
            },
        )
        return search_result

    def _score_result(
        self,
        query: str,
        item: ProviderSearchResult,
        *,
        requested_subject_type: SubjectType,
        year: int | None,
    ) -> float:
        candidates = [item.title]
        if item.payload.get('page_url'):
            candidates.append(_title_from_path(str(item.payload['page_url'])))
        score = title_match_score(query, candidates)

        if requested_subject_type != SubjectType.ALL:
            if item.subject_type is requested_subject_type:
                score += 0.1
            elif not item.payload.get('subject_type_inferred', False):
                score -= 0.2

        if year is not None:
            if item.year == year:
                score += 0.08
            elif item.year is not None:
                score -= 0.08

        if item.payload.get('episode_hint'):
            score -= 0.04
        return score

    async def _load_soup(
        self,
        path_or_url: str,
        *,
        referer: str | None = None,
    ) -> tuple[BeautifulSoup, str]:
        response, _base_url = await self._request(path_or_url, referer=referer)
        return BeautifulSoup(response.text, 'html.parser'), str(response.url)

    async def _load_player_tab(self, post_id: str, tab_id: str, referer: str) -> str:
        response, _base_url = await self._request(
            '/wp-admin/admin-ajax.php',
            method='POST',
            referer=referer,
            data={
                'action': 'muvipro_player_content',
                'tab': tab_id,
                'post_id': post_id,
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
            },
        )
        return response.text

    async def _request_text(
        self,
        path_or_url: str,
        *,
        referer: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        response, base_url = await self._request(path_or_url, referer=referer, headers=headers)
        return response.text, base_url

    async def _request(
        self,
        path_or_url: str,
        *,
        method: str = 'GET',
        referer: str | None = None,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> tuple[httpx.Response, str]:
        errors: list[str] = []
        for candidate_url in self._candidate_urls(path_or_url):
            request_headers = dict(_DEFAULT_HEADERS)
            if referer:
                request_headers['Referer'] = referer
            for key, value in dict(headers or {}).items():
                if key and value:
                    request_headers[str(key)] = str(value)
            try:
                if method.upper() == 'POST':
                    response = await self._client.post(
                        candidate_url,
                        data=data or {},
                        headers=request_headers,
                    )
                else:
                    response = await self._client.get(candidate_url, headers=request_headers)
                response.raise_for_status()
                base_url = _base_url(str(response.url))
                self._active_base_url = base_url
                return response, base_url
            except Exception as exc:
                errors.append(f'{candidate_url}: {exc}')
        raise RuntimeError('; '.join(errors) or f'Failed to fetch {path_or_url}')

    def _candidate_urls(self, path_or_url: str) -> list[str]:
        raw_value = str(path_or_url or '').strip()
        if not raw_value:
            return []

        parsed = urlparse(raw_value)
        if parsed.scheme and parsed.netloc:
            relative_path = parsed.path or '/'
            if parsed.query:
                relative_path = f'{relative_path}?{parsed.query}'
            candidates = [raw_value]
            for base_url in self._ordered_base_urls():
                alternate_url = urljoin(f'{base_url.rstrip("/")}/', relative_path.lstrip('/'))
                if alternate_url not in candidates:
                    candidates.append(alternate_url)
            return candidates

        return [
            urljoin(f'{base_url.rstrip("/")}/', raw_value.lstrip('/'))
            for base_url in self._ordered_base_urls()
        ]

    def _ordered_base_urls(self) -> list[str]:
        ordered: list[str] = []
        if self._active_base_url:
            ordered.append(self._active_base_url)
        for base_url in self._base_urls:
            if base_url not in ordered:
                ordered.append(base_url)
        return ordered


def _search_variants(query: str) -> list[str]:
    variants = [str(query).strip()]
    simplified = re.sub(r'[^a-zA-Z0-9]+', ' ', variants[0]).strip()
    if simplified and simplified.lower() != variants[0].lower():
        variants.append(simplified)
    return variants


def _node_text(node: Any) -> str:
    if node is None:
        return ''
    return str(node.get_text(' ', strip=True) or '').strip()


def _extract_detail_year(soup: BeautifulSoup) -> str:
    for container in soup.select('div.gmr-moviedata'):
        text = container.get_text(' ', strip=True)
        matched = re.search(r'Year:?\s*((?:19|20)\d{2})', text, flags=re.I)
        if matched:
            return matched.group(1)
    published = soup.select_one('span[property="datePublished"]')
    return _node_text(published)


def _extract_detail_genres(soup: BeautifulSoup) -> list[str]:
    genres: list[str] = []
    for container in soup.select('div.gmr-moviedata, p, li'):
        text = container.get_text(' ', strip=True)
        if 'genre' not in text.lower():
            continue
        for anchor in container.select('a[href]'):
            label = anchor.get_text(' ', strip=True)
            if label and label not in genres:
                genres.append(label)
        if genres:
            break
    return genres


def _image_url(node: Any, base_url: str) -> str:
    if node is None:
        return ''
    for attribute in ('data-src', 'src', 'srcset'):
        raw_value = str(node.get(attribute) or '').strip()
        if not raw_value:
            continue
        if attribute == 'srcset':
            raw_value = raw_value.split(',', maxsplit=1)[0].split(' ', maxsplit=1)[0]
        return urljoin(base_url, raw_value)
    return ''


def _parse_rating(text: str) -> float | None:
    matched = _RESULT_RATING_PATTERN.search(str(text or ''))
    if not matched:
        return None
    try:
        return float(matched.group(1))
    except ValueError:
        return None


def _clean_title(value: str) -> str:
    cleaned = str(value or '').strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'\bepisode\s+[0-9]{1,4}\b', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\bseason\s+[0-9]{1,3}\b', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned.strip(' -:')


def _title_from_path(url: str) -> str:
    path = urlparse(url).path.strip('/')
    slug = path.rsplit('/', maxsplit=1)[-1] if path else ''
    return slug.replace('-', ' ').title().strip()


def _relative_path(url: str) -> str:
    parsed = urlparse(url)
    relative_path = parsed.path or '/'
    if parsed.query:
        return f'{relative_path}?{parsed.query}'
    return relative_path


def _base_url(url: str) -> str:
    parsed = urlparse(url)
    return f'{parsed.scheme}://{parsed.netloc}' if parsed.scheme and parsed.netloc else ''


def _is_series_title(title: str) -> bool:
    lowered = str(title or '').lower()
    return any(token in lowered for token in (' season ', ' episode ', ' s1', ' s2', ' s3', ' ep '))


def _is_series_url(url: str) -> bool:
    lowered = str(url or '').lower()
    return any(token in lowered for token in ('season-', 'episode-', '/tv/', '-season-', '-episode-'))


def _extract_episode_entries(soup: BeautifulSoup, base_url: str, *, page_title: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    default_season = _extract_season_number(page_title) or 1
    seen: set[str] = set()
    episode_links = soup.select('div.vid-episodes a[href], div.gmr-listseries a[href]')
    for index, anchor in enumerate(episode_links, start=1):
        href = str(anchor.get('href') or '').strip()
        if not href:
            continue
        episode_url = urljoin(base_url, href)
        if episode_url in seen:
            continue
        seen.add(episode_url)
        label = anchor.get_text(' ', strip=True)
        season = _extract_season_number(label) or _extract_season_number(episode_url) or default_season
        episode = _extract_episode_number(label) or _extract_episode_number(episode_url) or index
        entries.append(
            {
                'title': label or f'Episode {episode}',
                'season': season,
                'episode': episode,
                'url': episode_url,
            }
        )
    return sorted(entries, key=lambda entry: (int(entry.get('season') or 1), int(entry.get('episode') or 0)))


def _extract_season_number(value: str) -> int | None:
    text = str(value or '')
    matched = _SEASON_PATTERN.search(text)
    if matched:
        try:
            return int(matched.group(1))
        except ValueError:
            return None
    return None


def _extract_episode_number(value: str) -> int | None:
    text = str(value or '')
    matched = _EPISODE_PATTERN.search(text)
    if matched:
        try:
            return int(matched.group(1))
        except ValueError:
            return None
    trailing = _TRAILING_NUMBER_PATTERN.search(text.strip())
    if trailing:
        try:
            return int(trailing.group(1))
        except ValueError:
            return None
    return None


def _select_episode_entry(
    entries: list[dict[str, Any]],
    *,
    season: int = 0,
    episode: int = 0,
) -> dict[str, Any] | None:
    if not entries:
        return None
    if season <= 0 and episode <= 0:
        return entries[0]

    season_candidates = entries
    if season > 0:
        season_candidates = [entry for entry in entries if int(entry.get('season') or 0) == season] or entries
    if episode > 0:
        exact = [entry for entry in season_candidates if int(entry.get('episode') or 0) == episode]
        if exact:
            return exact[0]
    return season_candidates[0] if season_candidates else entries[0]


def _extract_embed_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or '', 'html.parser')
    urls: list[str] = []
    seen: set[str] = set()
    for selector, attribute in (
        ('iframe[src]', 'src'),
        ('iframe[data-src]', 'data-src'),
        ('video[src]', 'src'),
        ('source[src]', 'src'),
    ):
        for element in soup.select(selector):
            raw_value = str(element.get(attribute) or '').strip()
            if not raw_value:
                continue
            candidate_url = urljoin(base_url, raw_value)
            if candidate_url in seen:
                continue
            seen.add(candidate_url)
            urls.append(candidate_url)

    for matched in _DIRECT_MEDIA_PATTERN.findall(html or ''):
        candidate_url = urljoin(base_url, matched)
        if candidate_url in seen:
            continue
        seen.add(candidate_url)
        urls.append(candidate_url)
    return urls
