from datetime import date
from types import SimpleNamespace

import pytest
from textual.widgets import ContentSwitcher, DataTable, Input, Select, Static

from moviebox_api.constants import SubjectType
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream
from moviebox_api.stremio.catalog import StremioSearchItem
from moviebox_api.tui.app import ContinuePromptScreen, InteractiveTextualApp, SubtitleChoice
from moviebox_api.tui.playback import WEB_PLAYER_TARGET


@pytest.mark.asyncio
async def test_result_selection_preserves_selected_item_state():
    app = InteractiveTextualApp()

    selected_item = StremioSearchItem(
        subjectId="tt0816692",
        subjectType=SubjectType.MOVIES,
        title="Interstellar",
        description="",
        releaseDate=date(2014, 1, 1),
        imdbRatingValue=8.7,
        genre=["Sci-Fi"],
        imdbId="tt0816692",
        tmdbId=157336,
        releaseInfo="2014",
        page_url="https://www.imdb.com/title/tt0816692/",
        stremioType="movie",
        metadata={},
    )
    app.search_items = [selected_item]
    app.displayed_search_items = [selected_item]

    async with app.run_test() as _pilot:
        await app._handle_result_selected(0)
        assert app.selected_item is not None
        assert app.selected_item.imdbId == "tt0816692"


@pytest.mark.asyncio
async def test_action_select_toggles_output_dir_visibility():
    app = InteractiveTextualApp()

    async with app.run_test() as _pilot:
        output_dir_input = app.query_one("#output_dir_input", Input)
        assert output_dir_input.has_class("hidden")

        app._apply_action_ui_state("download")
        assert not output_dir_input.has_class("hidden")

        app._apply_action_ui_state("stream")
        assert output_dir_input.has_class("hidden")


@pytest.mark.asyncio
async def test_tv_episode_auto_advance_moves_to_next_season():
    app = InteractiveTextualApp()

    tv_item = StremioSearchItem(
        subjectId="tt0903747",
        subjectType=SubjectType.TV_SERIES,
        title="Breaking Bad",
        description="",
        releaseDate=date(2008, 1, 1),
        imdbRatingValue=9.4,
        genre=["Crime"],
        imdbId="tt0903747",
        releaseInfo="2008",
        page_url="https://www.imdb.com/title/tt0903747/",
        stremioType="series",
        metadata={},
    )

    async with app.run_test() as _pilot:
        app.selected_item = tv_item
        app.season_map = {1: 2, 2: 1}
        app._setup_episode_selects(selected_season=1, selected_episode=2)

        assert app._advance_episode_selector() is True
        assert app.query_one("#season_select", Select).value == "2"
        assert app.query_one("#episode_select", Select).value == "1"


@pytest.mark.asyncio
async def test_movie_execute_returns_to_home_page(monkeypatch: pytest.MonkeyPatch):
    app = InteractiveTextualApp()

    movie_item = StremioSearchItem(
        subjectId="tt0816692",
        subjectType=SubjectType.MOVIES,
        title="Interstellar",
        description="",
        releaseDate=date(2014, 1, 1),
        imdbRatingValue=8.7,
        genre=["Sci-Fi"],
        imdbId="tt0816692",
        releaseInfo="2014",
        page_url="https://www.imdb.com/title/tt0816692/",
        stremioType="movie",
        metadata={},
    )

    async with app.run_test() as _pilot:
        app.selected_item = movie_item
        app.selected_stream = SimpleNamespace(url="https://example.com/video.mp4", headers={})

        async def _fake_handle_play() -> bool:
            return True

        monkeypatch.setattr(app, "_handle_play", _fake_handle_play)

        app._set_page("run")
        await app._handle_execute()

        switcher = app.query_one("#page_switcher", ContentSwitcher)
        assert switcher.current == "page_home"


@pytest.mark.asyncio
async def test_tv_execute_stops_when_user_declines_next_episode(monkeypatch: pytest.MonkeyPatch):
    app = InteractiveTextualApp()

    tv_item = StremioSearchItem(
        subjectId="tt0903747",
        subjectType=SubjectType.TV_SERIES,
        title="Breaking Bad",
        description="",
        releaseDate=date(2008, 1, 1),
        imdbRatingValue=9.4,
        genre=["Crime"],
        imdbId="tt0903747",
        releaseInfo="2008",
        page_url="https://www.imdb.com/title/tt0903747/",
        stremioType="series",
        metadata={},
    )

    async with app.run_test() as _pilot:
        app.selected_item = tv_item
        app.selected_stream = SimpleNamespace(
            url="https://example.com/video.mp4",
            headers={},
            source="provider",
            quality="1080p",
            audio="Indonesian",
            audio_tracks=["Indonesian"],
            subtitles=[],
        )
        app.season_map = {1: 2}
        app._setup_episode_selects(selected_season=1, selected_episode=1)

        async def _fake_handle_play() -> bool:
            return True

        async def _deny_continue(*, default_continue: bool, **_kwargs) -> bool:
            return False

        monkeypatch.setattr(app, "_handle_play", _fake_handle_play)
        monkeypatch.setattr(app, "_confirm_continue_next_episode", _deny_continue)

        await app._handle_execute()
        assert app.query_one("#episode_select", Select).value == "1"


@pytest.mark.asyncio
async def test_continue_prompt_stop_dismisses_without_continue_callback():
    app = InteractiveTextualApp()
    callback_calls: list[str] = []
    dismiss_results: list[bool] = []

    async def _on_continue() -> bool:
        callback_calls.append("continue")
        return True

    async def _on_stop() -> bool:
        callback_calls.append("stop")
        return False

    async with app.run_test() as pilot:
        await app.push_screen(
            ContinuePromptScreen(
                "Continue to next episode?",
                on_continue=_on_continue,
                on_stop=_on_stop,
            ),
            callback=lambda result: dismiss_results.append(bool(result)),
        )
        await pilot.click("#continue_stop_button")
        await pilot.pause()

        assert dismiss_results == [False]
        assert callback_calls == ["stop"]


@pytest.mark.asyncio
async def test_confirm_continue_cancels_when_prompt_raises(monkeypatch: pytest.MonkeyPatch):
    app = InteractiveTextualApp()

    monkeypatch.setattr(app, "_read_season_episode", lambda: (1, 1))

    captured_status: list[str] = []
    monkeypatch.setattr(app, "_set_status", lambda message: captured_status.append(message))

    async def _raise_prompt(*_args, **_kwargs):
        raise RuntimeError("prompt failure")

    monkeypatch.setattr(app, "push_screen_wait", _raise_prompt)

    result = await app._confirm_continue_next_episode(default_continue=True)

    assert result is False
    assert any("Auto-continue cancelled" in message for message in captured_status)


@pytest.mark.asyncio
async def test_subtitle_preference_persists_between_episode_fetches(monkeypatch: pytest.MonkeyPatch):
    app = InteractiveTextualApp()

    tv_item = StremioSearchItem(
        subjectId="tt0903747",
        subjectType=SubjectType.TV_SERIES,
        title="Breaking Bad",
        description="",
        releaseDate=date(2008, 1, 1),
        imdbRatingValue=9.4,
        genre=["Crime"],
        imdbId="tt0903747",
        releaseInfo="2008",
        page_url="https://www.imdb.com/title/tt0903747/",
        stremioType="series",
        metadata={},
    )

    async with app.run_test() as _pilot:
        app.selected_item = tv_item
        app.selected_stream = SimpleNamespace(
            url="https://example.com/video.mp4",
            headers={},
            source="provider",
            quality="1080p",
            audio="Indonesian",
            audio_tracks=["Indonesian"],
            subtitles=[],
        )
        app.preferred_subtitle_language_id = "ind"

        subtitle_entries = [
            SubtitleChoice(
                url="https://example.com/sub-ind.srt",
                language="Indonesian",
                language_id="ind",
                label="Indonesian",
                source="provider",
            ),
            SubtitleChoice(
                url="https://example.com/sub-ar-1.srt",
                language="Arabic",
                language_id="ara",
                label="Arabic 1",
                source="provider",
            ),
            SubtitleChoice(
                url="https://example.com/sub-ar-2.srt",
                language="Arabic",
                language_id="ara",
                label="Arabic 2",
                source="provider",
            ),
        ]

        monkeypatch.setattr(app, "_collect_provider_subtitles", lambda: subtitle_entries)

        loaded = await app._handle_subtitle_fetch(silent=True)
        assert loaded is True
        assert app.selected_subtitles
        assert all(subtitle.language_id == "ind" for subtitle in app.selected_subtitles)


@pytest.mark.asyncio
async def test_subtitle_selection_status_uses_full_language_name():
    app = InteractiveTextualApp()

    async with app.run_test() as _pilot:
        app.subtitle_language_order = ["ind"]
        app.subtitles_by_language = {
            "ind": [
                SubtitleChoice(
                    url="https://example.com/sub-ind.srt",
                    language="Indonesian",
                    language_id="ind",
                    label="Indonesian",
                    source="provider",
                )
            ]
        }

        app._handle_subtitle_language_selected(0)
        table = app.query_one("#subtitle_tracks_table", DataTable)
        row = table.get_row_at(0)
        assert row[2] == "Indonesian"


@pytest.mark.asyncio
async def test_android_subtitle_attempts_fallback_to_provider_language_priority():
    app = InteractiveTextualApp()

    async with app.run_test() as _pilot:
        app.preferred_subtitle_language_id = "ind"
        app.selected_subtitles = [
            SubtitleChoice(
                url="https://external.example/sub-ind.srt",
                language="Indonesian",
                language_id="ind",
                label="External Indonesian",
                source="subdl",
            )
        ]
        app.resolved_subtitles = [
            SimpleNamespace(url="https://provider.example/sub-ar.srt", language="Arabic"),
            SimpleNamespace(url="https://provider.example/sub-ind.srt", language="Indonesian"),
        ]
        stream = SimpleNamespace(
            subtitles=[SimpleNamespace(url="https://provider.example/sub-ind.srt", language="Indonesian")]
        )

        attempts = app._build_android_subtitle_attempts(stream, target_id="android_mpv")

        assert attempts[0] == ["https://external.example/sub-ind.srt"]
        assert attempts[1][0] == "https://provider.example/sub-ind.srt"
        assert attempts[-1] == []


@pytest.mark.asyncio
async def test_android_subtitle_attempts_vlc_prioritizes_provider_subtitles():
    app = InteractiveTextualApp()

    async with app.run_test() as _pilot:
        app.preferred_subtitle_language_id = "ind"
        app.selected_subtitles = [
            SubtitleChoice(
                url="https://external.example/sub-ind.srt",
                language="Indonesian",
                language_id="ind",
                label="External Indonesian",
                source="subdl",
            )
        ]
        app.resolved_subtitles = [
            SimpleNamespace(url="https://provider.example/sub-ind.srt", language="Indonesian")
        ]
        stream = SimpleNamespace(subtitles=[])

        attempts = app._build_android_subtitle_attempts(stream, target_id="android_vlc")

        assert attempts[0] == ["https://provider.example/sub-ind.srt"]
        assert attempts[1] == ["https://external.example/sub-ind.srt"]
        assert attempts[-1] == []


@pytest.mark.asyncio
async def test_subtitle_fetch_preserves_external_error_status(monkeypatch: pytest.MonkeyPatch):
    app = InteractiveTextualApp()

    movie_item = StremioSearchItem(
        subjectId="tt0816692",
        subjectType=SubjectType.MOVIES,
        title="Interstellar",
        description="",
        releaseDate=date(2014, 1, 1),
        imdbRatingValue=8.7,
        genre=["Sci-Fi"],
        imdbId="tt0816692",
        releaseInfo="2014",
        page_url="https://www.imdb.com/title/tt0816692/",
        stremioType="movie",
        metadata={},
    )

    async with app.run_test() as _pilot:
        app.selected_item = movie_item
        app.selected_stream = SimpleNamespace(
            url="https://example.com/video.mp4",
            headers={},
            source="provider",
            quality="1080p",
            audio="English",
            audio_tracks=["English"],
            subtitles=[],
        )
        app.query_one("#subtitle_source_select", Select).value = "subdl"

        captured_status: list[str] = []

        def _capture_status(message: str) -> None:
            captured_status.append(message)

        monkeypatch.setattr(app, "_set_status", _capture_status)

        monkeypatch.setattr(app, "_resolve_external_sources", lambda *_args, **_kwargs: ["subdl"])

        async def _raise_external(*_args, **_kwargs):
            raise RuntimeError("subdl: SubDL API key is invalid or expired")

        monkeypatch.setattr(app, "_fetch_external_subtitles", _raise_external)

        loaded = await app._handle_subtitle_fetch(silent=False)
        assert loaded is False
        assert any("External subtitle fetch failed" in status for status in captured_status)


@pytest.mark.asyncio
async def test_anime_selection_uses_provider_episode_map():
    app = InteractiveTextualApp()

    anime_item = StremioSearchItem(
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
                "status": "Ongoing",
                "episode_count": 2,
                "season_map": {1: 2},
                "content_subject_type": SubjectType.TV_SERIES,
                "genres": ["Action"],
            }
        },
    )

    async with app.run_test() as _pilot:
        await app._select_item(anime_item)

        assert app.query_one("#provider_select", Select).value == "samehadaku"
        assert not app.query_one("#source_episode_row").has_class("hidden")
        assert app.query_one("#season_select", Select).has_class("hidden")
        assert app.query_one("#episode_select", Select).value == "1"
        assert app._read_season_episode() == (1, 1)
        assert app.query_one("#subtitle_language_input", Input).value == "Indonesian"


@pytest.mark.asyncio
async def test_anime_selection_prefers_item_provider_in_source_select():
    app = InteractiveTextualApp()

    anime_item = StremioSearchItem(
        subjectId="anime:oplovers:jujutsu-kaisen",
        subjectType=SubjectType.ANIME,
        title="Jujutsu Kaisen",
        description="",
        releaseDate=date(2020, 1, 1),
        imdbRatingValue=0.0,
        genre=["Action"],
        imdbId="anime:oplovers:jujutsu-kaisen",
        releaseInfo="2020",
        page_url="https://coba.oploverz.ltd/series/jujutsu-kaisen",
        stremioType="series",
        metadata={
            "anime_payload": {
                "provider_name": "oplovers",
                "episode_count": 24,
                "season_map": {1: 24},
                "content_subject_type": SubjectType.TV_SERIES,
            }
        },
    )

    async with app.run_test() as _pilot:
        await app._select_item(anime_item)
        assert app.query_one("#provider_select", Select).value == "oplovers"



@pytest.mark.asyncio
async def test_provider_change_clears_stale_anime_streams(monkeypatch: pytest.MonkeyPatch):
    app = InteractiveTextualApp()

    async def _fake_load_trending(*args, **kwargs):
        return None

    monkeypatch.setattr(app, '_load_trending', _fake_load_trending)

    anime_item = StremioSearchItem(
        subjectId="anime:oplovers:jujutsu-kaisen",
        subjectType=SubjectType.ANIME,
        title="Jujutsu Kaisen",
        description="",
        releaseDate=date(2020, 1, 1),
        imdbRatingValue=0.0,
        genre=["Action"],
        imdbId="anime:oplovers:jujutsu-kaisen",
        releaseInfo="2020",
        page_url="https://coba.oploverz.ltd/series/jujutsu-kaisen",
        stremioType="series",
        metadata={
            "anime_payload": {
                "provider_name": "oplovers",
                "episode_count": 24,
                "season_map": {1: 24},
                "content_subject_type": SubjectType.TV_SERIES,
            }
        },
    )

    async with app.run_test() as _pilot:
        await app._select_item(anime_item)
        app.resolved_streams = [
            SimpleNamespace(
                url="https://example.com/video.mp4",
                source="oplovers",
                quality="1080p",
                headers={},
            )
        ]
        app.query_one("#streams_table", DataTable).add_row("1", "oplovers", "1080p", "-", "no", "https://example.com/video.mp4")

        app.query_one("#provider_select", Select).value = "otakudesu"
        await _pilot.pause()

        assert app.resolved_streams == []
        assert app.query_one("#streams_table", DataTable).row_count == 0


@pytest.mark.asyncio
async def test_anime_external_subtitle_fetch_uses_anime_helper(monkeypatch: pytest.MonkeyPatch):
    app = InteractiveTextualApp()

    anime_item = StremioSearchItem(
        subjectId="anime:samehadaku:solo-leveling",
        subjectType=SubjectType.ANIME,
        title="Solo Leveling",
        description="",
        releaseDate=date(2024, 1, 1),
        imdbRatingValue=0.0,
        genre=["Action"],
        imdbId="anime:samehadaku:solo-leveling",
        releaseInfo="2024",
        page_url="https://samehadaku.ac/anime/solo-leveling/",
        stremioType="series",
        metadata={
            "anime_payload": {
                "provider_name": "samehadaku",
                "episode_count": 12,
                "season_map": {1: 12},
                "content_subject_type": SubjectType.TV_SERIES,
            }
        },
    )

    async with app.run_test() as _pilot:
        app.selected_item = anime_item
        app.selected_stream = SimpleNamespace(
            url="https://example.com/video.mp4",
            headers={},
            source="samehadaku",
            quality="720p",
            audio="Japanese",
            audio_tracks=["Japanese"],
            subtitles=[],
        )
        app.season_map = {1: 12}
        app._setup_episode_selects(selected_season=1, selected_episode=1)

        async def _fake_fetch(item, *, season, episode, sources, preferred_languages):
            assert item is anime_item
            assert season == 1
            assert episode == 1
            assert sources == ["opensubtitles"]
            return [
                SimpleNamespace(
                    url="https://example.com/anime-id.srt",
                    language="Indonesian",
                    label="Anime Indonesian",
                    source="opensubtitles",
                )
            ]

        monkeypatch.setattr("moviebox_api.tui.app.fetch_anime_external_subtitles", _fake_fetch)

        result = await app._fetch_external_subtitles(
            sources=["opensubtitles"],
            preferred_language_id="ind",
        )

        assert len(result) == 1
        assert result[0].language_id == "ind"
        assert result[0].source == "opensubtitles"


@pytest.mark.asyncio
async def test_anime_execute_download_uses_episode_prompt(monkeypatch: pytest.MonkeyPatch):
    app = InteractiveTextualApp()

    anime_item = StremioSearchItem(
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
                "episode_count": 2,
                "season_map": {1: 2},
                "content_subject_type": SubjectType.TV_SERIES,
            }
        },
    )

    async with app.run_test() as _pilot:
        app.selected_item = anime_item
        app.selected_stream = SimpleNamespace(
            url="https://example.com/video.mp4",
            headers={},
            source="samehadaku",
            quality="720p",
            audio="Japanese",
            audio_tracks=["Japanese"],
            subtitles=[],
        )
        app.season_map = {1: 2}
        app._setup_episode_selects(selected_season=1, selected_episode=1)
        app.query_one("#action_select", Select).value = "download"

        prompted: list[bool] = []

        async def _fake_handle_download() -> bool:
            return True

        async def _fake_confirm(*, default_continue: bool, **_kwargs) -> bool:
            prompted.append(default_continue)
            return False

        monkeypatch.setattr(app, "_handle_download", _fake_handle_download)
        monkeypatch.setattr(app, "_confirm_continue_next_episode", _fake_confirm)

        await app._handle_execute()

        assert prompted == [False]


@pytest.mark.asyncio
async def test_resolve_streams_syncs_tui_item_when_provider_matches_series(monkeypatch: pytest.MonkeyPatch):
    app = InteractiveTextualApp()

    selected_movie = StremioSearchItem(
        subjectId="tt1468737",
        subjectType=SubjectType.MOVIES,
        title="Stranger Things",
        description="",
        releaseDate=date(2010, 1, 1),
        imdbRatingValue=0.0,
        genre=["Drama"],
        imdbId="tt1468737",
        releaseInfo="2010",
        page_url="https://www.imdb.com/title/tt1468737/",
        stremioType="movie",
        metadata={},
    )
    resolved_provider_item = ProviderSearchResult(
        id="netflix:80057281",
        title="Stranger Things",
        page_url="https://net52.cc/post/80057281",
        subject_type=SubjectType.TV_SERIES,
        year=2016,
    )
    matched_series = StremioSearchItem(
        subjectId="tt4574334",
        subjectType=SubjectType.TV_SERIES,
        title="Stranger Things",
        description="",
        releaseDate=date(2016, 1, 1),
        imdbRatingValue=8.7,
        genre=["Sci-Fi"],
        imdbId="tt4574334",
        releaseInfo="2016",
        page_url="https://www.imdb.com/title/tt4574334/",
        stremioType="series",
        metadata={},
    )

    class _FakeResolver:
        def __init__(self, provider_name: str | None = None):
            self.provider_name = provider_name

        async def resolve(self, **_kwargs):
            return (
                resolved_provider_item,
                [ProviderStream(url="https://example.com/stream.m3u8", source="cloudstream")],
                [],
            )

    async def _fake_fetch_cinemeta_meta(_item):
        return {"videos": [{"season": 1, "episode": 8}]}

    async with app.run_test() as _pilot:
        app.selected_item = selected_movie
        app.query_one("#provider_select", Select).value = "cloudstream"

        async def _fake_search_cinemeta_catalog(*_args, **_kwargs):
            return [matched_series]

        monkeypatch.setattr("moviebox_api.tui.app.SourceResolver", _FakeResolver)
        monkeypatch.setattr("moviebox_api.tui.app.search_cinemeta_catalog", _fake_search_cinemeta_catalog)
        monkeypatch.setattr("moviebox_api.tui.app.fetch_cinemeta_meta", _fake_fetch_cinemeta_meta)

        resolved = await app._handle_resolve_streams(silent=True)

        assert resolved is True
        assert app.selected_item is not None
        assert app.selected_item.subjectType == SubjectType.TV_SERIES
        assert app.selected_item.imdbId == "tt4574334"
        assert not app.query_one("#source_episode_row").has_class("hidden")
        assert app.query_one("#episode_select", Select).value == "1"
        assert app.query_one("#streams_table", DataTable).row_count == 1


@pytest.mark.asyncio
async def test_web_player_selection_disables_browser_fallback_in_tui(monkeypatch: pytest.MonkeyPatch):
    app = InteractiveTextualApp()

    movie_item = StremioSearchItem(
        subjectId="tt0816692",
        subjectType=SubjectType.MOVIES,
        title="Interstellar",
        description="",
        releaseDate=date(2014, 1, 1),
        imdbRatingValue=8.7,
        genre=["Sci-Fi"],
        imdbId="tt0816692",
        releaseInfo="2014",
        page_url="https://www.imdb.com/title/tt0816692/",
        stremioType="movie",
        metadata={},
    )

    captured = {'allow_browser_fallback': None}

    def _fake_play_stream(
        stream_url,
        headers,
        subtitle_paths,
        *,
        subtitle_urls=None,
        target_id=None,
        media_title=None,
        allow_browser_fallback=True,
    ):
        captured['allow_browser_fallback'] = allow_browser_fallback
        return SimpleNamespace(success=False, message='web player preflight failed', target_id=target_id)

    async with app.run_test() as _pilot:
        app.selected_item = movie_item
        app.selected_stream = SimpleNamespace(
            url='https://example.com/master.m3u8',
            headers={},
            source='provider',
            quality='1080p',
            audio='English',
            audio_tracks=['English'],
            subtitles=[],
        )
        app.query_one('#player_select', Select).value = WEB_PLAYER_TARGET

        async def _fake_collect_candidates(_stream):
            return [app.selected_stream]

        monkeypatch.setattr('moviebox_api.tui.app.play_stream', _fake_play_stream)
        monkeypatch.setattr(app, '_collect_playback_stream_candidates', _fake_collect_candidates)

        result = await app._handle_play()

        assert result is False
        assert captured['allow_browser_fallback'] is False
