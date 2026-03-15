from datetime import date

import pytest

from moviebox_api.anime import (
    anime_item_from_provider_result,
    anime_requires_season_selection,
    resolve_anime_sources,
    search_anime_catalog,
    stream_is_direct_download,
)
from moviebox_api.constants import SubjectType
from moviebox_api.providers.anime_common import build_anime_payload
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream


class _FakeAnimeProvider:
    def __init__(
        self,
        *,
        results: list[ProviderSearchResult],
        streams: list[ProviderStream] | None = None,
        stream_map: dict[str, list[ProviderStream]] | None = None,
        filter_by_year: bool = False,
    ) -> None:
        self._results = results
        self._streams = streams or []
        self._stream_map = stream_map or {}
        self._filter_by_year = filter_by_year

    async def search(
        self,
        query: str,
        subject_type: SubjectType,
        *,
        year: int | None = None,
        limit: int = 20,
    ) -> list[ProviderSearchResult]:
        results = self._results
        if self._filter_by_year and year is not None:
            results = [item for item in results if item.year == year]
        return results[:limit]

    async def resolve_streams(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderStream]:
        stream_key = str(item.page_url or item.id)
        if stream_key in self._stream_map:
            return list(self._stream_map[stream_key])
        return list(self._streams)

    async def resolve_subtitles(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list:
        return []


def _provider_result(
    provider_name: str,
    title: str,
    *,
    year: int,
    page_url: str,
    anime_type: str = 'TV',
    episode_count: int = 12,
) -> ProviderSearchResult:
    payload = build_anime_payload(
        provider_name=provider_name,
        title=title,
        page_url=page_url,
        description='',
        year=year,
        rating=8.0,
        status='Completed',
        anime_type=anime_type,
        thumbnail_url='',
        alt_titles=[],
        genres=['Action'],
        episodes=[
            {
                'number': episode_number,
                'title': f'Episode {episode_number}',
                'url': f'{page_url}episode-{episode_number}',
            }
            for episode_number in range(1, episode_count + 1)
        ],
        total_episodes=episode_count,
    )
    return ProviderSearchResult(
        id=f'{provider_name}:{title}',
        title=title,
        page_url=page_url,
        subject_type=SubjectType.ANIME,
        year=year,
        payload=payload,
    )


@pytest.mark.asyncio
async def test_search_anime_catalog_prefers_exact_match(monkeypatch: pytest.MonkeyPatch):
    exact = _provider_result(
        'oplovers',
        'Jujutsu Kaisen',
        year=2020,
        page_url='https://example.com/jujutsu-kaisen/',
    )
    sequel = _provider_result(
        'samehadaku',
        'Jujutsu Kaisen: Shimetsu Kaiyuu - Zenpen',
        year=2026,
        page_url='https://example.com/jujutsu-kaisen-shimetsu/',
    )
    unrelated = _provider_result(
        'samehadaku',
        'Another',
        year=2012,
        page_url='https://example.com/another/',
    )
    providers = {
        'samehadaku': _FakeAnimeProvider(results=[sequel, unrelated]),
        'oplovers': _FakeAnimeProvider(results=[exact]),
    }

    monkeypatch.setattr(
        'moviebox_api.anime.anime_provider_order',
        lambda _provider_name=None: ('samehadaku', 'oplovers'),
    )
    monkeypatch.setattr('moviebox_api.anime.get_provider', lambda name: providers[name])

    results = await search_anime_catalog('jujutsu kaisen', limit=5)

    assert results[0].title == 'Jujutsu Kaisen'
    assert results[1].title.startswith('Jujutsu Kaisen:')


@pytest.mark.asyncio
async def test_resolve_anime_sources_falls_back_when_first_provider_only_returns_wrapper(
    monkeypatch: pytest.MonkeyPatch,
):
    samehadaku_result = _provider_result(
        'samehadaku',
        'Jujutsu Kaisen',
        year=2020,
        page_url='https://samehadaku.example/jujutsu-kaisen/',
    )
    oplovers_result = _provider_result(
        'oplovers',
        'Jujutsu Kaisen',
        year=2020,
        page_url='https://oplovers.example/jujutsu-kaisen/',
    )
    item = anime_item_from_provider_result(samehadaku_result)
    item.releaseDate = date(2020, 1, 1)

    providers = {
        'samehadaku': _FakeAnimeProvider(
            results=[samehadaku_result],
            streams=[ProviderStream(url='https://example.com/embed/jujutsu', source='samehadaku:iframe')],
        ),
        'oplovers': _FakeAnimeProvider(
            results=[oplovers_result],
            streams=[ProviderStream(url='https://example.com/master.m3u8', source='oplovers:hls')],
        ),
    }

    monkeypatch.setattr(
        'moviebox_api.anime.anime_provider_order',
        lambda _provider_name=None: ('samehadaku', 'oplovers'),
    )
    monkeypatch.setattr('moviebox_api.anime.get_provider', lambda name: providers[name])

    provider_item, streams, subtitles, provider_name = await resolve_anime_sources(
        item,
        episode=1,
    )

    assert provider_name == 'oplovers'
    assert provider_item is oplovers_result
    assert [stream.url for stream in streams] == ['https://example.com/master.m3u8']
    assert subtitles == []


@pytest.mark.asyncio
async def test_resolve_anime_sources_keeps_explicit_provider(monkeypatch: pytest.MonkeyPatch):
    samehadaku_result = _provider_result(
        'samehadaku',
        'Jujutsu Kaisen',
        year=2020,
        page_url='https://samehadaku.example/jujutsu-kaisen/',
    )
    oplovers_result = _provider_result(
        'oplovers',
        'Jujutsu Kaisen',
        year=2020,
        page_url='https://oplovers.example/jujutsu-kaisen/',
    )
    item = anime_item_from_provider_result(samehadaku_result)
    item.releaseDate = date(2020, 1, 1)

    providers = {
        'samehadaku': _FakeAnimeProvider(
            results=[samehadaku_result],
            streams=[ProviderStream(url='https://example.com/embed/jujutsu', source='samehadaku:iframe')],
        ),
        'oplovers': _FakeAnimeProvider(
            results=[oplovers_result],
            streams=[ProviderStream(url='https://example.com/master.m3u8', source='oplovers:hls')],
        ),
    }

    monkeypatch.setattr(
        'moviebox_api.anime.anime_provider_order',
        lambda _provider_name=None: ('samehadaku', 'oplovers'),
    )
    monkeypatch.setattr('moviebox_api.anime.get_provider', lambda name: providers[name])

    provider_item, streams, subtitles, provider_name = await resolve_anime_sources(
        item,
        provider_name='samehadaku',
        episode=1,
    )

    assert provider_name == 'samehadaku'
    assert provider_item is not None
    assert provider_item.page_url == samehadaku_result.page_url
    assert [stream.url for stream in streams] == ['https://example.com/embed/jujutsu']
    assert subtitles == []


@pytest.mark.asyncio
async def test_resolve_anime_sources_tries_next_same_provider_match(monkeypatch: pytest.MonkeyPatch):
    empty_series = _provider_result(
        'otakudesu',
        'Jujutsu Kaisen - Otaku Desu',
        year=2020,
        page_url='https://otakudesu.example/jujutsu-kaisen/',
        episode_count=0,
    )
    playable_series = _provider_result(
        'otakudesu',
        'Jujutsu Kaisen Season 3 - Otaku Desu',
        year=2026,
        page_url='https://otakudesu.example/jujutsu-kaisen-season-3/',
        episode_count=10,
    )
    item = anime_item_from_provider_result(empty_series)
    item.releaseDate = date(2020, 1, 1)

    playable_stream = ProviderStream(
        url='https://example.com/jujutsu-season-3.m3u8',
        source='otakudesu:hls',
        quality='1080p',
    )
    providers = {
        'otakudesu': _FakeAnimeProvider(
            results=[empty_series, playable_series],
            stream_map={
                empty_series.page_url: [],
                playable_series.page_url: [playable_stream],
            },
            filter_by_year=True,
        ),
    }

    monkeypatch.setattr(
        'moviebox_api.anime.anime_provider_order',
        lambda _provider_name=None: ('otakudesu',),
    )
    monkeypatch.setattr('moviebox_api.anime.get_provider', lambda name: providers[name])

    provider_item, streams, subtitles, provider_name = await resolve_anime_sources(
        item,
        provider_name='otakudesu',
        episode=1,
    )

    assert provider_name == 'otakudesu'
    assert provider_item is not None
    assert provider_item.page_url == playable_series.page_url
    assert [stream.url for stream in streams] == [playable_stream.url]
    assert subtitles == []



@pytest.mark.asyncio
async def test_resolve_anime_sources_accepts_hls_direct_markers_without_url_suffix(
    monkeypatch: pytest.MonkeyPatch,
):
    result = _provider_result(
        'otakudesu',
        'Jujutsu Kaisen Season 3',
        year=2026,
        page_url='https://otakudesu.example/jujutsu-kaisen-season-3/',
    )
    item = anime_item_from_provider_result(result)
    item.releaseDate = date(2026, 1, 1)

    providers = {
        'otakudesu': _FakeAnimeProvider(
            results=[result],
            streams=[
                ProviderStream(
                    url='https://cdn.example/playlist',
                    source='otakudesu:embed:hls:direct',
                    quality='720p',
                )
            ],
        ),
    }

    monkeypatch.setattr(
        'moviebox_api.anime.anime_provider_order',
        lambda _provider_name=None: ('otakudesu',),
    )
    monkeypatch.setattr('moviebox_api.anime.get_provider', lambda name: providers[name])

    provider_item, streams, subtitles, provider_name = await resolve_anime_sources(
        item,
        provider_name='otakudesu',
        episode=1,
    )

    assert provider_name == 'otakudesu'
    assert provider_item is not None
    assert [stream.url for stream in streams] == ['https://cdn.example/playlist']
    assert subtitles == []


@pytest.mark.asyncio
async def test_resolve_anime_sources_keeps_pixeldrain_api_downloads(
    monkeypatch: pytest.MonkeyPatch,
):
    result = _provider_result(
        'oplovers',
        'Jujutsu Kaisen',
        year=2020,
        page_url='https://oplovers.example/jujutsu-kaisen/',
    )
    item = anime_item_from_provider_result(result)
    item.releaseDate = date(2020, 1, 1)

    providers = {
        'oplovers': _FakeAnimeProvider(
            results=[result],
            streams=[
                ProviderStream(
                    url='https://pixeldrain.com/api/file/Jjy1SRhd',
                    source='oplovers:one drive:direct',
                    quality='720p',
                ),
                ProviderStream(
                    url='https://pixeldrain.com/api/file/myELqLdy',
                    source='oplovers:one drive:direct',
                    quality='1080p',
                ),
            ],
        ),
    }

    monkeypatch.setattr(
        'moviebox_api.anime.anime_provider_order',
        lambda _provider_name=None: ('oplovers',),
    )
    monkeypatch.setattr('moviebox_api.anime.get_provider', lambda name: providers[name])

    provider_item, streams, subtitles, provider_name = await resolve_anime_sources(
        item,
        provider_name='oplovers',
        episode=1,
    )

    assert provider_name == 'oplovers'
    assert provider_item is not None
    assert provider_item.page_url == result.page_url
    assert [stream.quality for stream in streams] == ['720p', '1080p']
    assert [stream.url for stream in streams] == [
        'https://pixeldrain.com/api/file/Jjy1SRhd',
        'https://pixeldrain.com/api/file/myELqLdy',
    ]
    assert subtitles == []


def test_anime_requires_season_selection_only_for_multi_season_items():
    single_season = anime_item_from_provider_result(
        _provider_result(
            'samehadaku',
            'Jujutsu Kaisen Season 3',
            year=2026,
            page_url='https://example.com/jujutsu-kaisen-season-3/',
            episode_count=10,
        )
    )
    multi_season = anime_item_from_provider_result(
        _provider_result(
            'oplovers',
            'One Piece',
            year=1999,
            page_url='https://example.com/one-piece/',
            episode_count=24,
        )
    )
    multi_season.metadata['anime_payload']['season_map'] = {1: 24, 2: 12}

    assert anime_requires_season_selection(single_season) is False
    assert anime_requires_season_selection(multi_season) is True


def test_stream_is_direct_download_accepts_googleusercontent_download_urls():
    assert (
        stream_is_direct_download(
            'https://drive.usercontent.google.com/download?id=abc123&export=download'
        )
        is True
    )
