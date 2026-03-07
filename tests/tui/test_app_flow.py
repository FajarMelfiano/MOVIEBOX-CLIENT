from datetime import date
from types import SimpleNamespace

import pytest
from textual.widgets import ContentSwitcher, Input, Select

from moviebox_api.constants import SubjectType
from moviebox_api.stremio.catalog import StremioSearchItem
from moviebox_api.tui.app import InteractiveTextualApp


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
