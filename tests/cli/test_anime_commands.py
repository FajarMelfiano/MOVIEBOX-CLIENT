from datetime import date

from click.testing import CliRunner

from moviebox_api.cli.anime_commands import (
    _AnimeResolutionContext,
    _resolve_anime_context,
    download_anime_command,
    source_anime_command,
)
from moviebox_api.constants import SubjectType
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle
from moviebox_api.stremio.catalog import StremioSearchItem


def _anime_item() -> StremioSearchItem:
    return StremioSearchItem(
        subjectId="anime:samehadaku:one-piece",
        subjectType=SubjectType.ANIME,
        title="One Piece",
        description="",
        releaseDate=date(1999, 1, 1),
        imdbRatingValue=0.0,
        genre=["Action"],
        imdbId="anime:samehadaku:one-piece",
        releaseInfo="1999",
        page_url="https://samehadaku.ac/anime/one-piece/",
        stremioType="series",
        metadata={
            "anime_payload": {
                "provider_name": "samehadaku",
                "episode_count": 1,
                "season_map": {1: 1},
                "content_subject_type": SubjectType.TV_SERIES,
            }
        },
    )


def _resolution_context() -> _AnimeResolutionContext:
    provider_item = ProviderSearchResult(
        id="anime-1",
        title="One Piece",
        page_url="https://samehadaku.ac/anime/one-piece/",
        subject_type=SubjectType.ANIME,
        year=1999,
        payload={"provider_name": "samehadaku", "status": "Ongoing"},
    )
    stream = ProviderStream(
        url="https://cdn.example/one-piece-1.mp4",
        source="samehadaku:iframe",
        quality="720p",
        subtitles=[ProviderSubtitle(url="https://cdn.example/one-piece-1.ass", language="id")],
        headers={"Referer": "https://samehadaku.ac/one-piece-episode-1-subtitle-indonesia/"},
    )
    return _AnimeResolutionContext(
        item=_anime_item(),
        provider_item=provider_item,
        provider_name="samehadaku",
        season=1,
        episode=1,
        streams=[stream],
        provider_subtitles=[],
    )


def test_source_anime_command_json(monkeypatch):
    runner = CliRunner()
    context = _resolution_context()

    monkeypatch.setattr(
        "moviebox_api.cli.anime_commands._resolve_anime_context",
        lambda **_kwargs: context,
    )
    monkeypatch.setattr(
        "moviebox_api.cli.anime_commands._resolve_subtitles",
        lambda **_kwargs: [
            {
                "url": "https://example.com/sub.ass",
                "language_id": "ind",
                "source": "provider",
                "label": "Indonesian",
                "language": "id",
            }
        ],
    )

    result = runner.invoke(source_anime_command, ["One Piece", "--json"])

    assert result.exit_code == 0
    assert '"provider": "samehadaku"' in result.output
    assert '"selected_stream"' in result.output


def test_resolve_anime_context_uses_direct_provider_query(monkeypatch):
    provider_item = ProviderSearchResult(
        id="anime-otakudesu",
        title="Jujutsu Kaisen Season 3",
        page_url="https://otakudesu.example/jujutsu-kaisen-season-3/",
        subject_type=SubjectType.ANIME,
        year=2026,
        payload={
            "provider_name": "otakudesu",
            "episode_count": 10,
            "season_map": {1: 10},
            "content_subject_type": SubjectType.TV_SERIES,
        },
    )
    stream = ProviderStream(url="https://cdn.example/master.m3u8", source="otakudesu:hls", quality="720p")

    async def _fake_resolve_anime_source_query(*args, **kwargs):
        return provider_item, [stream], [], "otakudesu"

    async def _fake_search_best_anime_item(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "moviebox_api.cli.anime_commands.resolve_anime_source_query",
        _fake_resolve_anime_source_query,
    )
    monkeypatch.setattr(
        "moviebox_api.cli.anime_commands.search_best_anime_item",
        _fake_search_best_anime_item,
    )

    context = _resolve_anime_context(
        title="jujutsu kaisen shimetsu kaiyuu zenpen",
        provider="otakudesu",
        year=2026,
        season=1,
        episode=9,
    )

    assert context.provider_name == "otakudesu"
    assert context.provider_item.title == "Jujutsu Kaisen Season 3"
    assert context.item.title == "Jujutsu Kaisen Season 3"
    assert context.season == 1
    assert context.episode == 9


def test_download_anime_command_json(monkeypatch):
    runner = CliRunner()
    context = _resolution_context()

    monkeypatch.setattr(
        "moviebox_api.cli.anime_commands._resolve_anime_context",
        lambda **_kwargs: context,
    )
    monkeypatch.setattr(
        "moviebox_api.cli.anime_commands._resolve_subtitles",
        lambda **_kwargs: [
            {
                "url": "https://example.com/sub.ass",
                "language_id": "ind",
                "source": "provider",
                "label": "Indonesian",
                "language": "id",
            }
        ],
    )
    monkeypatch.setattr(
        "moviebox_api.cli.anime_commands.select_stream_by_quality",
        lambda *args, **kwargs: context.streams[0],
    )

    result = runner.invoke(download_anime_command, ["One Piece", "--json"])

    assert result.exit_code == 0
    assert '"requested_episode"' in result.output
    assert '"subtitles"' in result.output
