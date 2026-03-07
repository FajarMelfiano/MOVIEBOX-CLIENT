from datetime import date
from types import SimpleNamespace

import pytest
from textual.widgets import ContentSwitcher, DataTable, Input, Select, Static

from moviebox_api.constants import SubjectType
from moviebox_api.stremio.catalog import StremioSearchItem
from moviebox_api.tui.app import ContinuePromptScreen, InteractiveTextualApp, SubtitleChoice


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
