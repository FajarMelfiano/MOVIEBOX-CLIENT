"""Samehadaku anime provider."""

from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from moviebox_api.constants import SubjectType
from moviebox_api.providers.anime_common import (
    BaseAnimeProvider,
    build_anime_payload,
    decoded_iframe_url,
    dedupe_streams,
    extract_episode_number,
    extract_subtitle_links,
    parse_year,
    provider_result_from_payload,
    title_match_score,
)
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle


class SamehadakuProvider(BaseAnimeProvider):
    """Scrape Samehadaku search, metadata, and episode pages."""

    name = 'samehadaku'
    env_keys = ('MOVIEBOX_SAMEHADAKU_URLS', 'MOVIEBOX_SAMEHADAKU_URL')
    default_base_urls = ('https://samehadaku.ac',)

    async def search(
        self,
        query: str,
        subject_type: SubjectType,
        *,
        year: int | None = None,
        limit: int = 20,
    ) -> list[ProviderSearchResult]:
        if subject_type != SubjectType.ANIME:
            return []

        search_path = f'/?s={query.strip().replace(" ", "+")}'
        html, base_url = await self._request_text(search_path, referer=self.base_urls()[0])
        soup = BeautifulSoup(html, 'html.parser')
        series_urls: list[str] = []
        for anchor in soup.select('.listupd .bs a[href], article .bsx a[href]'):
            href = str(anchor.get('href') or '').strip()
            if '/anime/' not in href:
                continue
            absolute_url = self.absolute_url(base_url, href)
            if absolute_url not in series_urls:
                series_urls.append(absolute_url)
            if len(series_urls) >= limit:
                break

        results = await self._load_series_results(series_urls)
        if year is not None:
            results = [item for item in results if item.year == year]
        results.sort(key=lambda item: self._result_score(query, item), reverse=True)
        return results[:limit]

    async def list_trending(self, *, limit: int = 20) -> list[ProviderSearchResult]:
        html, base_url = await self._request_text('/anime/?status=&type=&order=update')
        soup = BeautifulSoup(html, 'html.parser')
        series_urls: list[str] = []
        for anchor in soup.select('.listupd .bs a[href]'):
            href = str(anchor.get('href') or '').strip()
            if '/anime/' not in href:
                continue
            absolute_url = self.absolute_url(base_url, href)
            if absolute_url not in series_urls:
                series_urls.append(absolute_url)
            if len(series_urls) >= limit:
                break
        return await self._load_series_results(series_urls)

    async def resolve_streams(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderStream]:
        episode_entry = self._episode_entry(item, episode=episode)
        episode_url = episode_entry.get('url') if episode_entry else item.page_url
        html, _base_url = await self._request_text(episode_url, referer=item.page_url)
        soup = BeautifulSoup(html, 'html.parser')

        subtitles = extract_subtitle_links(html)
        streams: list[ProviderStream] = []

        iframe = soup.select_one('.player-embed iframe[src]')
        if iframe and iframe.get('src'):
            iframe_url = str(iframe.get('src')).strip()
            streams.extend(
                await self.expand_streams(
                    url=iframe_url,
                    source=f"samehadaku:{self._stream_source_name(iframe_url, 'iframe')}",
                    referer=episode_url,
                    subtitles=subtitles,
                )
            )

        for option in soup.select('.mobius option[value]'):
            candidate_url = decoded_iframe_url(str(option.get('value') or ''))
            if not candidate_url:
                continue
            label = ' '.join(option.get_text(' ', strip=True).split()) or self._stream_source_name(
                candidate_url,
                'video',
            )
            streams.extend(
                await self.expand_streams(
                    url=candidate_url,
                    source=f'samehadaku:{label.lower()}',
                    referer=episode_url,
                    subtitles=subtitles,
                )
            )

        return dedupe_streams(streams)

    async def resolve_subtitles(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderSubtitle]:
        episode_entry = self._episode_entry(item, episode=episode)
        episode_url = episode_entry.get('url') if episode_entry else item.page_url
        html, _base_url = await self._request_text(episode_url, referer=item.page_url)
        return extract_subtitle_links(html)

    async def _load_series_results(self, urls: list[str]) -> list[ProviderSearchResult]:
        results: list[ProviderSearchResult] = []
        for url in urls:
            try:
                results.append(await self._load_series_result(url))
            except Exception:
                continue
        return results

    async def _load_series_result(self, url: str) -> ProviderSearchResult:
        html, base_url = await self._request_text(url, referer=self.base_urls()[0])
        soup = BeautifulSoup(html, 'html.parser')

        title = self._first_text(soup, '.infox h1.entry-title', 'title') or url.rstrip('/').split('/')[-1]
        alt_titles_text = self._first_text(soup, '.infox .alter')
        alt_titles = [value.strip() for value in alt_titles_text.split(',') if value.strip()]
        specs = self._parse_specs(soup)
        genres = [
            anchor.get_text(' ', strip=True)
            for anchor in soup.select('.genxed a')
            if anchor.get_text(' ', strip=True)
        ]
        description = self._first_text(soup, '.entry-content')
        poster_url = ''
        poster_selectors = (
            '.thumb img[src]',
            '.thumbook img[src]',
            '.bigcontent img[src]',
            'meta[property="og:image"]',
        )
        for selector in poster_selectors:
            element = soup.select_one(selector)
            if not element:
                continue
            if element.name == 'meta':
                poster_url = str(element.get('content') or '').strip()
            else:
                poster_url = str(element.get('src') or '').strip()
            if poster_url:
                break

        episodes = []
        for anchor in soup.select('.eplister ul li a[href]'):
            episode_url = self.absolute_url(base_url, str(anchor.get('href') or '').strip())
            episode_title = ' '.join(anchor.get_text(' ', strip=True).split())
            episodes.append(
                {
                    'number': (
                        extract_episode_number(episode_title)
                        or extract_episode_number(episode_url)
                        or 1
                    ),
                    'title': episode_title,
                    'url': episode_url,
                }
            )

        payload = build_anime_payload(
            provider_name=self.name,
            title=title,
            page_url=url,
            description=description,
            year=parse_year(specs.get('released')),
            rating=None,
            status=specs.get('status', ''),
            anime_type=specs.get('type', ''),
            thumbnail_url=poster_url,
            alt_titles=alt_titles,
            genres=genres,
            episodes=episodes,
            total_episodes=len(episodes),
            extra={
                'studio': specs.get('studio', ''),
                'season_name': specs.get('season', ''),
                'duration': specs.get('duration', ''),
            },
        )
        return provider_result_from_payload(item_id=url, title=title, page_url=url, payload=payload)

    @staticmethod
    def _parse_specs(soup: BeautifulSoup) -> dict[str, str]:
        specs: dict[str, str] = {}
        for bold in soup.select('.infox .spe span b'):
            key = bold.get_text(' ', strip=True).strip().rstrip(':').lower()
            parent_text = bold.parent.get_text(' ', strip=True)
            value = parent_text.split(':', maxsplit=1)[1].strip() if ':' in parent_text else ''
            specs[key] = value
        return specs

    @staticmethod
    def _first_text(soup: BeautifulSoup, selector: str, fallback: str = '') -> str:
        element = soup.select_one(selector)
        return element.get_text(' ', strip=True) if element else fallback

    @staticmethod
    def _stream_source_name(url: str, fallback: str) -> str:
        host = urlparse(url).netloc.lower()
        if 'blogger.com' in host:
            return 'blogger'
        if host:
            return host.split('.')[0]
        return fallback

    @staticmethod
    def _episode_entry(item: ProviderSearchResult, *, episode: int) -> dict[str, str] | None:
        episodes = item.payload.get('episodes') if isinstance(item.payload, dict) else None
        if not isinstance(episodes, list) or not episodes:
            return None

        target_episode = episode if episode > 0 else 1
        for entry in episodes:
            try:
                if int(entry.get('number') or 0) == target_episode:
                    return entry
            except (TypeError, ValueError):
                continue
        return episodes[0]

    @staticmethod
    def _result_score(query: str, item: ProviderSearchResult) -> float:
        candidates = [item.title]
        alt_titles = item.payload.get('alt_titles') if isinstance(item.payload, dict) else None
        if isinstance(alt_titles, list):
            candidates.extend(str(value).strip() for value in alt_titles if str(value).strip())
        return title_match_score(query, candidates)
