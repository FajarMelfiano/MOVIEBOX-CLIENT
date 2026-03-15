import pytest

from moviebox_api.constants import SubjectType
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle
from moviebox_api.source import SourceResolver


class _FakeProvider:
    def __init__(
        self,
        item: ProviderSearchResult | None,
        streams: list[ProviderStream],
        subtitles: list[ProviderSubtitle],
    ):
        self._item = item
        self._streams = streams
        self._subtitles = subtitles

    async def search_best_match(self, query: str, subject_type: SubjectType, *, year: int | None = None):
        return self._item

    async def resolve_streams(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderStream]:
        return self._streams

    async def resolve_subtitles(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderSubtitle]:
        return self._subtitles


class _FakeProviderWithIdBuilder(_FakeProvider):
    def __init__(
        self,
        item: ProviderSearchResult | None,
        streams: list[ProviderStream],
        subtitles: list[ProviderSubtitle],
    ):
        super().__init__(item=item, streams=streams, subtitles=subtitles)
        self.search_calls = 0
        self.id_builder_calls = 0

    async def search_best_match(self, query: str, subject_type: SubjectType, *, year: int | None = None):
        self.search_calls += 1
        return await super().search_best_match(query, subject_type, year=year)

    async def build_item_from_ids(
        self,
        *,
        subject_type: SubjectType,
        imdb_id: str | None = None,
        tmdb_id: int | None = None,
        title: str = "",
        year: int | None = None,
    ):
        self.id_builder_calls += 1
        return self._item


@pytest.mark.asyncio
async def test_resolve_returns_empty_when_no_item(monkeypatch):
    fake_provider = _FakeProvider(item=None, streams=[], subtitles=[])
    monkeypatch.setattr("moviebox_api.source.get_provider", lambda _name=None: fake_provider)

    resolver = SourceResolver()
    item, streams, subtitles = await resolver.resolve("Avatar", SubjectType.MOVIES)

    assert item is None
    assert streams == []
    assert subtitles == []


@pytest.mark.asyncio
async def test_resolve_uses_provider_subtitles(monkeypatch):
    item = ProviderSearchResult(
        id="1",
        title="Avatar",
        page_url="https://example.com/avatar",
        subject_type=SubjectType.MOVIES,
    )
    subtitles = [ProviderSubtitle(url="https://example.com/sub.vtt", language="en")]
    streams = [
        ProviderStream(
            url="https://example.com/stream.m3u8",
            source="fake",
            subtitles=[],
        )
    ]
    fake_provider = _FakeProvider(item=item, streams=streams, subtitles=subtitles)
    monkeypatch.setattr("moviebox_api.source.get_provider", lambda _name=None: fake_provider)

    resolver = SourceResolver("moviebox")
    _, resolved_streams, resolved_subtitles = await resolver.resolve("Avatar", SubjectType.MOVIES)

    assert resolved_streams == streams
    assert resolved_subtitles == subtitles


@pytest.mark.asyncio
async def test_resolve_falls_back_to_stream_subtitles(monkeypatch):
    item = ProviderSearchResult(
        id="1",
        title="Avatar",
        page_url="https://example.com/avatar",
        subject_type=SubjectType.MOVIES,
    )
    stream_subtitle = ProviderSubtitle(url="https://example.com/sub.srt", language="en")
    streams = [
        ProviderStream(
            url="https://example.com/stream.m3u8",
            source="fake",
            subtitles=[stream_subtitle],
        )
    ]
    fake_provider = _FakeProvider(item=item, streams=streams, subtitles=[])
    monkeypatch.setattr("moviebox_api.source.get_provider", lambda _name=None: fake_provider)

    resolver = SourceResolver("moviebox")
    _, resolved_streams, resolved_subtitles = await resolver.resolve("Avatar", SubjectType.MOVIES)

    assert resolved_streams == streams
    assert resolved_subtitles == [stream_subtitle]


@pytest.mark.asyncio
async def test_resolve_prefers_id_builder_when_available(monkeypatch):
    item = ProviderSearchResult(
        id="157336",
        title="Interstellar",
        page_url="https://example.com/interstellar",
        subject_type=SubjectType.MOVIES,
    )
    streams = [ProviderStream(url="https://example.com/stream.m3u8", source="fake")]
    fake_provider = _FakeProviderWithIdBuilder(item=item, streams=streams, subtitles=[])
    monkeypatch.setattr("moviebox_api.source.get_provider", lambda _name=None: fake_provider)

    resolver = SourceResolver("vega")
    _, resolved_streams, _ = await resolver.resolve(
        "Interstellar",
        SubjectType.MOVIES,
        imdb_id="tt0816692",
        tmdb_id=157336,
    )

    assert resolved_streams == streams
    assert fake_provider.id_builder_calls == 1
    assert fake_provider.search_calls == 0


@pytest.mark.asyncio
async def test_resolve_delegates_anime_subjects_to_anime_helper(monkeypatch):
    item = ProviderSearchResult(
        id="anime-1",
        title="One Piece",
        page_url="https://example.com/one-piece",
        subject_type=SubjectType.ANIME,
    )
    streams = [ProviderStream(url="https://example.com/stream.mp4", source="samehadaku")]
    subtitles = [ProviderSubtitle(url="https://example.com/sub.ass", language="id")]

    async def _fake_resolve_anime_source_query(title: str, **kwargs):
        assert title == "One Piece"
        assert kwargs["provider_name"] == "samehadaku"
        return item, streams, subtitles, "samehadaku"

    monkeypatch.setattr(
        "moviebox_api.anime.resolve_anime_source_query",
        _fake_resolve_anime_source_query,
    )

    resolver = SourceResolver("samehadaku")
    resolved_item, resolved_streams, resolved_subtitles = await resolver.resolve(
        "One Piece",
        SubjectType.ANIME,
        season=1,
        episode=1,
    )

    assert resolved_item == item
    assert resolved_streams == streams
    assert resolved_subtitles == subtitles
