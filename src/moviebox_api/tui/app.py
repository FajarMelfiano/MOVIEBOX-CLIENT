"""Paged Textual TUI for interactive stream and subtitle workflows."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Footer,
    Header,
    Input,
    LoadingIndicator,
    Select,
    Static,
)

from moviebox_api.constants import CURRENT_WORKING_DIR, DOWNLOAD_REQUEST_HEADERS, SubjectType
from moviebox_api.language import language_display_name, normalize_language_id
from moviebox_api.providers import SUPPORTED_PROVIDERS, normalize_provider_name
from moviebox_api.source import SourceResolver
from moviebox_api.stremio.catalog import (
    StremioSearchItem,
    build_stremio_video_id,
    extract_series_seasons,
    fetch_cinemeta_meta,
    fetch_cinemeta_top_catalog,
    search_cinemeta_catalog,
)
from moviebox_api.stremio.subtitle_sources import (
    SUBDL_API_KEY_ENV,
    SUBSOURCE_API_KEY_ENV,
    fetch_external_subtitles,
    subtitle_source_is_configured,
)
from moviebox_api.tui.playback import (
    AUTO_TARGET,
    default_playback_target_id,
    is_android_target,
    is_termux_environment,
    list_playback_targets,
    play_stream,
    probe_stream_access,
)


@dataclass(slots=True)
class SubtitleChoice:
    url: str
    language: str
    language_id: str
    label: str
    source: str


class ContinuePromptScreen(ModalScreen[bool]):
    """Simple yes/no dialog used for TV episode continuation."""

    CSS = """
    ContinuePromptScreen {
      align: center middle;
      background: rgba(3, 22, 37, 0.75);
    }

    #continue_prompt_dialog {
      width: 72;
      height: auto;
      border: round #22d3ee;
      background: #0f1a30;
      padding: 1;
    }

    #continue_prompt_message {
      margin: 0 0 1 0;
      color: #dbe7ff;
    }

    #continue_prompt_buttons {
      height: auto;
    }

    #continue_prompt_buttons Button {
      margin-right: 1;
      min-width: 12;
    }

    #continue_prompt_loading_row {
      height: auto;
      margin: 1 0 0 0;
    }

    #continue_prompt_loading_label {
      margin-left: 1;
      color: #93c5fd;
    }
    """

    def __init__(
        self,
        message: str,
        *,
        on_continue: Callable[[], Awaitable[bool]],
        on_stop: Callable[[], Awaitable[bool]],
    ) -> None:
        super().__init__()
        self._message = message
        self._on_continue = on_continue
        self._on_stop = on_stop
        self._busy = False

    def compose(self) -> ComposeResult:
        with Vertical(id="continue_prompt_dialog"):
            yield Static(self._message, id="continue_prompt_message")
            with Horizontal(id="continue_prompt_buttons"):
                yield Button("Stop", id="continue_stop_button")
                yield Button("Continue", id="continue_yes_button", variant="success")
            with Horizontal(id="continue_prompt_loading_row", classes="hidden"):
                yield LoadingIndicator(id="continue_prompt_loading")
                yield Static("Processing...", id="continue_prompt_loading_label")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._busy:
            return
        self._busy = True

        continue_selected = event.button.id == "continue_yes_button"
        self._set_busy_state(continue_selected)

        try:
            if continue_selected:
                result = await self._on_continue()
            else:
                result = await self._on_stop()
        except Exception:
            result = False

        self.dismiss(bool(result))

    def _set_busy_state(self, continue_selected: bool) -> None:
        self.query_one("#continue_yes_button", Button).disabled = True
        self.query_one("#continue_stop_button", Button).disabled = True

        if continue_selected:
            self.query_one("#continue_prompt_message", Static).update("Preparing next episode...")
            self.query_one("#continue_prompt_loading_label", Static).update(
                "Loading streams and subtitles..."
            )
        else:
            self.query_one("#continue_prompt_message", Static).update("Stopping...")
            self.query_one("#continue_prompt_loading_label", Static).update("Applying your choice...")

        self.query_one("#continue_prompt_loading_row").remove_class("hidden")


class InteractiveTextualApp(App[None]):
    """Modern page-based TUI for movie/series flow."""

    TITLE = "MOVIEBOX TUI"
    SUB_TITLE = "Home -> Search -> Source -> Subtitle -> Run"
    CSS = """
    Screen {
      layout: vertical;
      background: #0b1220;
      color: #dbe7ff;
    }

    Header {
      background: #111c34;
    }

    Footer {
      background: #111c34;
    }

    #root {
      height: 1fr;
      padding: 1 2;
      overflow-y: auto;
    }

    #status_card {
      border: round #2dd4bf;
      background: #0f1a30;
      padding: 0 1;
      height: auto;
      margin: 0 0 1 0;
    }

    #status {
      color: #bfdbfe;
      height: auto;
    }

    #loading_row {
      height: auto;
      margin: 0 0 1 0;
    }

    #loading_label {
      margin-left: 1;
      color: #93c5fd;
    }

    #nav_row {
      height: auto;
      margin: 0 0 1 0;
    }

    #nav_row Button {
      min-width: 12;
      margin-right: 1;
    }

    .active-nav {
      background: #22d3ee;
      color: #031625;
      text-style: bold;
    }

    #page_switcher {
      height: 1fr;
    }

    .page {
      border: round #334155;
      background: #0f172a;
      padding: 1;
      height: 1fr;
    }

    .page_title {
      color: #22d3ee;
      text-style: bold;
      margin: 0 0 1 0;
      height: auto;
    }

    .row {
      height: auto;
      margin: 0 0 1 0;
    }

    .flex_input {
      width: 1fr;
      margin-right: 1;
    }

    DataTable {
      height: 1fr;
      margin: 0 0 1 0;
    }

    .hint {
      color: #93c5fd;
      height: auto;
    }

    .hidden {
      display: none;
    }
    """
    BINDINGS = [
        Binding("q", "request_quit", "Quit"),
        Binding("ctrl+r", "reset_flow", "Reset"),
        Binding("f1", "goto_home", "Home"),
        Binding("f2", "goto_search", "Search"),
        Binding("f3", "goto_source", "Source"),
        Binding("f4", "goto_subtitle", "Subtitle"),
        Binding("f5", "goto_run", "Run"),
    ]

    PAGES = ("home", "search", "source", "subtitle", "run")

    def __init__(self) -> None:
        super().__init__()
        self.trending_items: list[StremioSearchItem] = []
        self.search_items: list[StremioSearchItem] = []
        self.displayed_search_items: list[StremioSearchItem] = []
        self.selected_item: StremioSearchItem | None = None
        self.season_map: dict[int, int] = {}
        self.selected_provider_name: str = ""
        self.resolved_streams: list = []
        self.selected_stream = None
        self.resolved_subtitles: list = []
        self.subtitles_by_language: dict[str, list[SubtitleChoice]] = {}
        self.subtitle_language_order: list[str] = []
        self.selected_subtitles: list[SubtitleChoice] = []
        self.preferred_subtitle_language_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            with Vertical(id="status_card"):
                yield Static(
                    "Use pages to navigate workflow. Termux defaults to MPV Android app playback.",
                    id="status",
                )

            with Horizontal(id="loading_row", classes="hidden"):
                yield LoadingIndicator(id="loading_indicator")
                yield Static("Loading...", id="loading_label")

            with Horizontal(id="nav_row"):
                yield Button("Home", id="nav_home_button")
                yield Button("Search", id="nav_search_button")
                yield Button("Source", id="nav_source_button")
                yield Button("Subtitle", id="nav_subtitle_button")
                yield Button("Run", id="nav_run_button")

            with ContentSwitcher(initial="page_home", id="page_switcher"):
                with Vertical(id="page_home", classes="page"):
                    yield Static("Home - Trending Movies", classes="page_title")
                    with Horizontal(classes="row"):
                        yield Button("Refresh Trending", id="home_refresh_button", variant="primary")
                        yield Button("Go To Search", id="home_go_search_button")
                    yield DataTable(id="trending_table")
                    yield Static(
                        "Select a trending row to jump directly into Source page.",
                        classes="hint",
                    )

                with Vertical(id="page_search", classes="page"):
                    yield Static("Search - Choose Movies or TV Series", classes="page_title")
                    with Horizontal(classes="row"):
                        yield Select(
                            options=[("Movies", "MOVIES"), ("TV Series", "TV_SERIES")],
                            value="MOVIES",
                            id="subject_type_select",
                            allow_blank=False,
                            prompt="Subject",
                        )
                        yield Input(placeholder="Search title", id="query_input", classes="flex_input")
                        yield Button("Search", id="search_button", variant="primary")
                        yield Button("Type (Termux)", id="search_dialog_button")
                    yield DataTable(id="results_table")
                    yield Static(
                        "Select a search result row to continue to Source page.",
                        classes="hint",
                    )

                with Vertical(id="page_source", classes="page"):
                    yield Static("Source - Resolve Stream Provider", classes="page_title")
                    yield Static("No selected item.", id="source_item_label", classes="hint")
                    with Horizontal(id="source_episode_row", classes="row hidden"):
                        yield Select(
                            options=[("Season 1", "1")],
                            value="1",
                            id="season_select",
                            allow_blank=False,
                            prompt="Season",
                        )
                        yield Select(
                            options=[("Episode 1", "1")],
                            value="1",
                            id="episode_select",
                            allow_blank=False,
                            prompt="Episode",
                        )
                    with Horizontal(classes="row"):
                        yield Select(
                            options=[(provider, provider) for provider in SUPPORTED_PROVIDERS],
                            value="moviebox",
                            id="provider_select",
                            allow_blank=False,
                            prompt="Provider",
                        )
                        yield Input(
                            placeholder="Vega module (optional)",
                            id="vega_provider_input",
                            classes="flex_input",
                        )
                        yield Button("Resolve", id="resolve_button", variant="success")
                    yield DataTable(id="streams_table")
                    yield Static(
                        "Select a stream row to continue to Subtitle page.",
                        classes="hint",
                    )

                with Vertical(id="page_subtitle", classes="page"):
                    yield Static("Subtitle - Provider and Language", classes="page_title")
                    yield Static("No selected stream.", id="subtitle_stream_label", classes="hint")
                    with Horizontal(classes="row"):
                        yield Select(
                            options=[
                                ("none", "none"),
                                ("provider", "provider"),
                                ("opensubtitles", "opensubtitles"),
                                ("subdl", "subdl"),
                                ("subsource", "subsource"),
                                ("all", "all"),
                            ],
                            value="provider",
                            id="subtitle_source_select",
                            allow_blank=False,
                            prompt="Subtitle source",
                        )
                        yield Input(
                            placeholder="Preferred subtitle language (optional, ex: Indonesian)",
                            id="subtitle_language_input",
                            classes="flex_input",
                        )
                        yield Button("Load", id="subtitle_button", variant="primary")
                        yield Button("Skip", id="subtitle_skip_button")
                    yield DataTable(id="subtitle_languages_table")
                    yield DataTable(id="subtitle_tracks_table")
                    with Horizontal(classes="row"):
                        yield Button("Go To Run", id="subtitle_to_run_button", variant="success")

                with Vertical(id="page_run", classes="page"):
                    yield Static("Run - Stream or Download", classes="page_title")
                    yield Static("No selection yet.", id="run_summary", classes="hint")
                    with Horizontal(classes="row"):
                        yield Select(
                            options=[("stream", "stream"), ("download", "download")],
                            value="stream",
                            id="action_select",
                            allow_blank=False,
                            prompt="Action",
                        )
                        yield Select(
                            options=[("Auto (Recommended)", AUTO_TARGET)],
                            value=AUTO_TARGET,
                            id="player_select",
                            allow_blank=False,
                            prompt="Player",
                        )
                        yield Input(
                            value=str(CURRENT_WORKING_DIR),
                            placeholder="Output directory",
                            id="output_dir_input",
                            classes="flex_input",
                        )
                        yield Button("Run", id="run_button", variant="primary")
                    yield Static("Tip: choose subtitle language before run.", id="run_hint", classes="hint")
        yield Footer()

    def on_mount(self) -> None:
        self._configure_tables()
        self._configure_player_options()
        self._set_page("home")
        self._apply_action_ui_state("stream")
        self.query_one("#query_input", Input).focus()
        self.run_worker(self._load_trending(), exclusive=False, group="home")

    def _configure_tables(self) -> None:
        table_defs = {
            "#trending_table": ("#", "Title", "Year", "Rating", "Genre"),
            "#results_table": ("#", "Title", "Year", "Rating", "Genre"),
            "#streams_table": ("#", "Source", "Quality", "Audio", "Headers", "URL"),
            "#subtitle_languages_table": ("#", "Language", "Count"),
            "#subtitle_tracks_table": ("#", "Source", "Language", "Label", "URL"),
        }

        for table_id, columns in table_defs.items():
            table = self.query_one(table_id, DataTable)
            table.cursor_type = "row"
            table.zebra_stripes = True
            table.add_columns(*columns)

    def _configure_player_options(self) -> None:
        player_select = self.query_one("#player_select", Select)
        options = [(target.label, target.id) for target in list_playback_targets()]
        if not options:
            options = [("Auto (Recommended)", AUTO_TARGET)]
        player_select.set_options(options)

        default_target = default_playback_target_id()
        available_values = {str(value) for _, value in options}
        if default_target in available_values:
            player_select.value = default_target
        else:
            player_select.value = str(options[0][1])

    def action_request_quit(self) -> None:
        self.exit()

    def action_reset_flow(self) -> None:
        self._reset_from_item_selection()
        self.selected_item = None
        self._update_source_item_label()
        self._update_run_summary()
        self._set_page("home")
        self._set_status("Flow reset. Trending and search results are still available.")

    def action_goto_home(self) -> None:
        self._set_page("home")

    def action_goto_search(self) -> None:
        self._set_page("search")

    def action_goto_source(self) -> None:
        if self.selected_item is None:
            self._set_status("Select a trending/search item first.")
            return
        self._set_page("source")

    def action_goto_subtitle(self) -> None:
        if self.selected_stream is None:
            self._set_status("Resolve and select a stream first.")
            return
        self._set_page("subtitle")

    def action_goto_run(self) -> None:
        if self.selected_stream is None:
            self._set_status("Resolve and select a stream first.")
            return
        self._set_page("run")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "nav_home_button":
            self._set_page("home")
            return
        if button_id == "nav_search_button":
            self._set_page("search")
            return
        if button_id == "nav_source_button":
            self.action_goto_source()
            return
        if button_id == "nav_subtitle_button":
            self.action_goto_subtitle()
            return
        if button_id == "nav_run_button":
            self.action_goto_run()
            return

        if button_id == "home_refresh_button":
            await self._load_trending()
            return
        if button_id == "home_go_search_button":
            self._set_page("search")
            return

        if button_id == "search_button":
            await self._handle_search()
            return
        if button_id == "search_dialog_button":
            await self._prompt_search_query_termux()
            return
        if button_id == "resolve_button":
            await self._handle_resolve_streams()
            return

        if button_id == "subtitle_button":
            await self._handle_subtitle_fetch()
            return
        if button_id == "subtitle_skip_button":
            self.selected_subtitles = []
            self._fill_subtitle_tracks_table([])
            self._update_run_summary()
            self._set_page("run")
            return
        if button_id == "subtitle_to_run_button":
            self._update_run_summary()
            self._set_page("run")
            return

        if button_id == "run_button":
            await self._handle_execute()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "action_select":
            self._apply_action_ui_state(str(event.value or "stream"))
            return

        if event.select.id == "player_select":
            self._update_run_summary()
            return

        if event.select.id == "season_select":
            try:
                season = int(str(event.value or "1"))
            except ValueError:
                season = 1
            self._setup_episode_options(season)
            self._update_run_summary()

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id
        if table_id == "trending_table":
            await self._handle_trending_selected(event.cursor_row)
            return
        if table_id == "results_table":
            await self._handle_result_selected(event.cursor_row)
            return
        if table_id == "streams_table":
            self._handle_stream_selected(event.cursor_row)
            return
        if table_id == "subtitle_languages_table":
            self._handle_subtitle_language_selected(event.cursor_row)

    async def _load_trending(self) -> None:
        self._set_loading(True, "Loading trending movies...")
        try:
            items = await fetch_cinemeta_top_catalog(SubjectType.MOVIES, limit=60)
        except Exception as exc:
            self._set_status(f"Failed to load trending: {exc}")
            return
        finally:
            self._set_loading(False)

        self.trending_items = items[:50]
        table = self.query_one("#trending_table", DataTable)
        table.clear(columns=False)
        for index, item in enumerate(self.trending_items, start=1):
            table.add_row(
                str(index),
                item.title,
                str(item.year or "-"),
                f"{item.imdbRatingValue:.1f}",
                ", ".join(item.genre[:2]) or "-",
            )

        self._set_status("Trending loaded. Select a row or go to Search page.")

    async def _handle_search(self) -> None:
        query_input = self.query_one("#query_input", Input)
        query = query_input.value.strip()

        if not query and is_termux_environment():
            prompted_query = await self._prompt_search_query_termux()
            if prompted_query is not None:
                query = prompted_query.strip()

        if not query:
            self._set_status(
                "Search query is required. On Termux install `termux-api` and use 'Type (Termux)'."
            )
            return

        selected_subject = self.query_one("#subject_type_select", Select).value
        subject_type = SubjectType.TV_SERIES if selected_subject == "TV_SERIES" else SubjectType.MOVIES

        self._set_loading(True, "Searching catalog...")
        self._set_status(f"Searching Cinemeta for '{query}'...")
        try:
            results = await search_cinemeta_catalog(query, subject_type)
        except Exception as exc:
            self._set_status(f"Search failed: {exc}")
            return
        finally:
            self._set_loading(False)

        self.search_items = results
        self.displayed_search_items = results[:80]

        table = self.query_one("#results_table", DataTable)
        table.clear(columns=False)
        for index, item in enumerate(self.displayed_search_items, start=1):
            table.add_row(
                str(index),
                item.title,
                str(item.year or "-"),
                f"{item.imdbRatingValue:.1f}",
                ", ".join(item.genre[:2]) or "-",
            )

        if not self.displayed_search_items:
            self._set_status("No search results found.")
            return

        self._set_status("Search finished. Select a row to continue.")

    async def _prompt_search_query_termux(self) -> str | None:
        prompted = await self._prompt_termux_text_dialog(
            title="Moviebox Search",
            hint="Type title",
        )
        if prompted is None:
            return None

        query_input = self.query_one("#query_input", Input)
        query_input.value = prompted
        query_input.focus()

        if prompted.strip():
            self._set_status("Query updated from Termux dialog. Press Search.")
        return prompted

    async def _prompt_termux_text_dialog(self, *, title: str, hint: str) -> str | None:
        if not is_termux_environment():
            self._set_status("Termux dialog input is only available in Termux environment.")
            return None

        if shutil.which("termux-dialog") is None:
            self._set_status("`termux-dialog` not found. Install it with `pkg install termux-api` in Termux.")
            return None

        command = ["termux-dialog", "text", "-t", title]
        if hint:
            command.extend(["-i", hint])

        self._set_loading(True, "Opening Termux input dialog...")
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await process.communicate()
        except Exception as exc:
            self._set_status(f"Failed to open Termux dialog: {exc}")
            return None
        finally:
            self._set_loading(False)

        if process.returncode != 0:
            error_text = stderr_data.decode("utf-8", errors="ignore").strip()
            self._set_status(f"Termux dialog failed: {error_text or 'unknown error'}")
            return None

        raw_text = stdout_data.decode("utf-8", errors="ignore").strip()
        if not raw_text:
            return ""

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return raw_text

        text_value = str(payload.get("text", ""))
        return text_value

    async def _handle_trending_selected(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self.trending_items):
            return
        await self._select_item(self.trending_items[row_index])

    async def _handle_result_selected(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self.displayed_search_items):
            return
        await self._select_item(self.displayed_search_items[row_index])

    async def _select_item(self, item: StremioSearchItem) -> None:
        self._reset_from_item_selection()
        self.selected_item = item
        self._update_source_item_label()

        episode_row = self.query_one("#source_episode_row")
        if item.subjectType == SubjectType.TV_SERIES:
            episode_row.remove_class("hidden")
            self._set_loading(True, "Loading season metadata...")
            try:
                meta = await fetch_cinemeta_meta(item)
                self.season_map = extract_series_seasons(meta)
            except Exception:
                self.season_map = {}
            finally:
                self._set_loading(False)

            self._setup_episode_selects()
        else:
            episode_row.add_class("hidden")

        self._set_page("source")
        self._update_run_summary()
        self._set_status(f"Selected '{item.title}'. Resolve streams in Source page.")

    def _setup_episode_selects(
        self, selected_season: int | None = None, selected_episode: int | None = None
    ) -> None:
        seasons = sorted(self.season_map.keys())
        if not seasons:
            seasons = [1]

        season_select = self.query_one("#season_select", Select)
        season_select.set_options([(f"Season {season}", str(season)) for season in seasons])

        chosen_season = selected_season if selected_season in seasons else seasons[0]
        season_select.value = str(chosen_season)
        self._setup_episode_options(chosen_season, selected_episode)

    def _setup_episode_options(self, season: int, selected_episode: int | None = None) -> None:
        if self.season_map:
            max_episode = self.season_map.get(season, 1)
        else:
            max_episode = selected_episode or 1
        if max_episode < 1:
            max_episode = 1

        episode_select = self.query_one("#episode_select", Select)
        episode_select.set_options(
            [(f"Episode {episode}", str(episode)) for episode in range(1, max_episode + 1)]
        )

        chosen_episode = selected_episode if selected_episode and 1 <= selected_episode <= max_episode else 1
        episode_select.value = str(chosen_episode)

    async def _handle_resolve_streams(self, *, silent: bool = False) -> bool:
        if self.selected_item is None:
            if not silent:
                self._set_status("Select a title first from Home or Search.")
            return False

        season, episode = self._read_season_episode()
        if season is None or episode is None:
            return False

        provider_value = str(self.query_one("#provider_select", Select).value or "moviebox")
        if provider_value == "vega":
            vega_module = self.query_one("#vega_provider_input", Input).value.strip()
            if vega_module:
                provider_value = f"vega:{vega_module}"

        try:
            provider_name = normalize_provider_name(provider_value)
        except Exception as exc:
            if not silent:
                self._set_status(f"Invalid provider: {exc}")
            return False

        self._set_loading(True, "Resolving provider streams...")
        if not silent:
            self._set_status(f"Resolving streams via {provider_name}...")
        try:
            _, streams, subtitles = await SourceResolver(provider_name=provider_name).resolve(
                title=self.selected_item.title,
                subject_type=self.selected_item.subjectType,
                year=self.selected_item.year,
                season=season,
                episode=episode,
                imdb_id=self.selected_item.imdbId,
                tmdb_id=self.selected_item.tmdbId,
            )
        except Exception as exc:
            if not silent:
                self._set_status(f"Provider resolution failed: {exc}")
            return False
        finally:
            self._set_loading(False)

        self.selected_provider_name = provider_name
        self.resolved_streams = streams
        self.resolved_subtitles = subtitles
        self.selected_stream = None
        self.selected_subtitles = []
        self.subtitles_by_language = {}
        self.subtitle_language_order = []
        self._clear_subtitle_tables()

        table = self.query_one("#streams_table", DataTable)
        table.clear(columns=False)
        for index, stream in enumerate(self.resolved_streams, start=1):
            audio_label = self._stream_audio_label(stream)
            table.add_row(
                str(index),
                stream.source,
                stream.quality or "-",
                audio_label,
                "yes" if stream.headers else "no",
                stream.url[:90],
            )

        if not self.resolved_streams:
            if not silent:
                self._set_status("No streams found for selected provider.")
            return False

        if not silent:
            self._set_status("Streams resolved. Select a stream row to continue.")
        return True

    def _handle_stream_selected(self, row_index: int, *, navigate: bool = True) -> None:
        if row_index < 0 or row_index >= len(self.resolved_streams):
            return

        self.selected_stream = self.resolved_streams[row_index]
        self.selected_subtitles = []
        self.subtitles_by_language = {}
        self.subtitle_language_order = []
        self._clear_subtitle_tables()
        self._update_subtitle_stream_label()
        self._update_run_summary()
        if navigate:
            self._set_page("subtitle")
            self._set_status("Load subtitles, choose preferred language, then go to Run page.")

    async def _handle_subtitle_fetch(self, *, silent: bool = False) -> bool:
        if self.selected_item is None or self.selected_stream is None:
            if not silent:
                self._set_status("Select title and stream first.")
            return False

        source_choice = str(self.query_one("#subtitle_source_select", Select).value or "provider")
        language_text = self.query_one("#subtitle_language_input", Input).value.strip()
        preferred_language_id = ""
        if language_text:
            candidate = normalize_language_id(language_text)
            if candidate != "unknown":
                preferred_language_id = candidate
                self.preferred_subtitle_language_id = candidate
        elif self.preferred_subtitle_language_id:
            preferred_language_id = self.preferred_subtitle_language_id

        if source_choice == "none":
            self.selected_subtitles = []
            self._clear_subtitle_tables()
            self._update_run_summary()
            if not silent:
                self._set_status("Subtitle disabled. Continue to Run page.")
            return True

        subtitles: list[SubtitleChoice] = []
        if source_choice in {"provider", "all"}:
            subtitles.extend(self._collect_provider_subtitles())

        if source_choice in {"opensubtitles", "subdl", "subsource", "all"}:
            sources = self._resolve_external_sources(source_choice)
            if sources:
                self._set_loading(True, "Fetching external subtitles...")
                try:
                    fetched_external = await self._fetch_external_subtitles(
                        sources=sources,
                        preferred_language_id=preferred_language_id,
                    )
                    subtitles.extend(fetched_external)
                except Exception as exc:
                    if not silent:
                        self._set_status(f"External subtitle fetch failed: {exc}")
                finally:
                    self._set_loading(False)

        deduped: dict[str, SubtitleChoice] = {}
        for subtitle in subtitles:
            deduped[subtitle.url] = subtitle
        subtitles = list(deduped.values())

        self.subtitles_by_language = {}
        for subtitle in subtitles:
            self.subtitles_by_language.setdefault(subtitle.language_id, []).append(subtitle)

        self.subtitle_language_order = sorted(
            self.subtitles_by_language.keys(),
            key=lambda language_id: (-len(self.subtitles_by_language[language_id]), language_id),
        )
        self._fill_subtitle_languages_table()

        if not self.subtitle_language_order:
            self.selected_subtitles = []
            self._fill_subtitle_tracks_table([])
            self._update_run_summary()
            if not silent:
                self._set_status("No subtitle matches found.")
            return False

        if preferred_language_id and preferred_language_id in self.subtitles_by_language:
            selected = self.subtitles_by_language[preferred_language_id]
            self.selected_subtitles = selected
            self._fill_subtitle_tracks_table(selected)
            self._update_run_summary()
            if not silent:
                display_name = language_display_name(preferred_language_id)
                self._set_status(f"Using {len(selected)} subtitles for '{display_name}'.")
            return True

        first_language = self.subtitle_language_order[0]
        if self.preferred_subtitle_language_id is None:
            self.preferred_subtitle_language_id = first_language
        selected = self.subtitles_by_language[first_language]
        self.selected_subtitles = selected
        self._fill_subtitle_tracks_table(selected)
        self._update_run_summary()
        if not silent:
            display_name = language_display_name(first_language)
            self._set_status(f"Choose subtitle language row (default '{display_name}').")
        return True

    def _handle_subtitle_language_selected(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self.subtitle_language_order):
            return

        language_id = self.subtitle_language_order[row_index]
        selected = self.subtitles_by_language.get(language_id, [])
        self.preferred_subtitle_language_id = language_id
        self.selected_subtitles = selected
        self._fill_subtitle_tracks_table(selected)
        self._update_run_summary()
        display_name = language_display_name(language_id)
        self._set_status(f"Using {len(selected)} subtitles for '{display_name}'.")

    async def _handle_execute(self) -> None:
        action = str(self.query_one("#action_select", Select).value or "stream")
        is_tv_series = bool(self.selected_item and self.selected_item.subjectType == SubjectType.TV_SERIES)
        selected_player_target = self._selected_player_target_id()
        uses_android_external_player = is_android_target(selected_player_target)

        if action == "download":
            success = await self._handle_download()
            if not success:
                return

            if is_tv_series:

                async def _on_continue_download() -> bool:
                    if not self._advance_episode_selector():
                        self._set_status("Download finished. No more episodes in selected series metadata.")
                        return False
                    self._set_status("Download finished. Moved to next episode selector.")
                    return False

                async def _on_stop_download() -> bool:
                    self._set_status("Download finished. Stopped at current episode by user choice.")
                    return False

                await self._confirm_continue_next_episode(
                    default_continue=False,
                    on_continue=_on_continue_download,
                    on_stop=_on_stop_download,
                )
                return

            self._set_page("home")
            self._set_status("Movie download finished. Returned to Home page.")
            return

        if not is_tv_series:
            success = await self._handle_play()
            if success:
                self._set_page("home")
                self._set_status("Movie playback finished. Returned to Home page.")
            return

        if uses_android_external_player:
            current_stream = self.selected_stream
            success = await self._handle_play()
            if not success:
                return

            if current_stream is None:
                self._set_status("Cannot prepare next episode: current stream unavailable.")
                return

            async def _on_continue_android() -> bool:
                await self._prepare_next_episode_from_current(current_stream, auto_start=False)
                return False

            async def _on_stop_android() -> bool:
                self._set_status("Playback launched. Stopped at current episode by user choice.")
                return False

            await self._confirm_continue_next_episode(
                default_continue=False,
                on_continue=_on_continue_android,
                on_stop=_on_stop_android,
            )
            return

        while True:
            current_stream = self.selected_stream
            if current_stream is None:
                self._set_status("No selected stream to continue auto-play.")
                return

            success = await self._handle_play()
            if not success:
                return

            async def _on_continue_desktop() -> bool:
                return await self._prepare_next_episode_from_current(current_stream, auto_start=True)

            async def _on_stop_desktop() -> bool:
                self._set_status("Playback stopped by user after current episode.")
                return False

            continue_next = await self._confirm_continue_next_episode(
                default_continue=True,
                on_continue=_on_continue_desktop,
                on_stop=_on_stop_desktop,
            )
            if not continue_next:
                return

    async def _handle_play(self) -> bool:
        if self.selected_stream is None:
            self._set_status("Select stream first.")
            return False

        selected_stream = self.selected_stream
        selected_target = self._selected_player_target_id()
        stream_candidates = await self._collect_playback_stream_candidates(selected_stream)
        allow_browser_fallback = not is_termux_environment()
        media_title = self.selected_item.title if self.selected_item else ""
        last_failure = "all stream and player attempts failed"

        self._set_loading(True, "Running action...")
        try:
            for candidate_index, stream in enumerate(stream_candidates, start=1):
                headers = self._merged_request_headers(stream.headers)
                subtitle_paths: list[Path] = []
                temp_dir: tempfile.TemporaryDirectory[str] | None = None
                attempt_status_suffix = ""

                try:
                    if is_android_target(selected_target):
                        self.query_one("#loading_label", Static).update(
                            f"Checking stream access ({candidate_index}/{len(stream_candidates)})..."
                        )
                        is_reachable, reason = await asyncio.to_thread(
                            probe_stream_access, stream.url, headers
                        )
                        if not is_reachable:
                            last_failure = f"{stream.source}: {reason}"
                            continue

                        subtitle_attempts = self._build_android_subtitle_attempts(
                            stream,
                            target_id=selected_target,
                        )
                        for subtitle_attempt_index, subtitle_urls in enumerate(subtitle_attempts, start=1):
                            self.query_one("#loading_label", Static).update(
                                f"Launching player (stream {candidate_index}/{len(stream_candidates)})..."
                            )
                            result = await asyncio.to_thread(
                                play_stream,
                                stream.url,
                                headers,
                                [],
                                subtitle_urls=subtitle_urls,
                                target_id=selected_target,
                                media_title=media_title,
                                allow_browser_fallback=allow_browser_fallback,
                            )

                            if result.success:
                                if subtitle_attempt_index == 2 and subtitle_urls:
                                    attempt_status_suffix = " (subtitle fallback: provider)"
                                elif subtitle_attempt_index > 2 or not subtitle_urls:
                                    attempt_status_suffix = " (without subtitles)"

                                self.selected_stream = stream
                                self._update_subtitle_stream_label()
                                self._update_run_summary()
                                suffix = (
                                    f" (fallback stream #{candidate_index})" if candidate_index > 1 else ""
                                )
                                self._set_status(f"{result.message}{suffix}{attempt_status_suffix}")
                                return True

                            last_failure = result.message

                        continue

                    if self.selected_subtitles:
                        self.query_one("#loading_label", Static).update("Preparing subtitles...")
                        temp_dir = tempfile.TemporaryDirectory(prefix="moviebox-tui-subtitles-")
                        subtitle_paths = await asyncio.to_thread(
                            self._download_subtitles_for_playback,
                            self.selected_subtitles,
                            Path(temp_dir.name),
                            headers,
                        )

                    subtitle_urls = [subtitle.url for subtitle in self.selected_subtitles if subtitle.url]
                    self.query_one("#loading_label", Static).update(
                        f"Launching player (stream {candidate_index}/{len(stream_candidates)})..."
                    )
                    result = await asyncio.to_thread(
                        play_stream,
                        stream.url,
                        headers,
                        subtitle_paths,
                        subtitle_urls=subtitle_urls,
                        target_id=selected_target,
                        media_title=media_title,
                        allow_browser_fallback=allow_browser_fallback,
                    )

                    if result.success:
                        self.selected_stream = stream
                        self._update_subtitle_stream_label()
                        self._update_run_summary()
                        suffix = f" (fallback stream #{candidate_index})" if candidate_index > 1 else ""
                        self._set_status(f"{result.message}{suffix}")
                        return True

                    last_failure = result.message

                    if self.selected_subtitles:
                        self.query_one("#loading_label", Static).update(
                            "Retrying launch without subtitles..."
                        )
                        no_subtitle_result = await asyncio.to_thread(
                            play_stream,
                            stream.url,
                            headers,
                            [],
                            subtitle_urls=[],
                            target_id=selected_target,
                            media_title=media_title,
                            allow_browser_fallback=allow_browser_fallback,
                        )
                        if no_subtitle_result.success:
                            self.selected_stream = stream
                            self._update_subtitle_stream_label()
                            self._update_run_summary()
                            suffix = f" (fallback stream #{candidate_index})" if candidate_index > 1 else ""
                            self._set_status(f"{no_subtitle_result.message}{suffix} (without subtitles)")
                            return True
                        last_failure = no_subtitle_result.message
                finally:
                    if temp_dir is not None:
                        temp_dir.cleanup()
        finally:
            self._set_loading(False)

        self._set_status(f"Playback failed: {last_failure}")
        return False

    async def _handle_download(self) -> bool:
        if self.selected_item is None or self.selected_stream is None:
            self._set_status("Select title and stream first.")
            return False

        season, episode = self._read_season_episode()
        if season is None or episode is None:
            return False

        output_dir_text = self.query_one("#output_dir_input", Input).value.strip() or str(CURRENT_WORKING_DIR)
        output_dir = Path(output_dir_text).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._set_status(f"Invalid output directory: {exc}")
            return False

        stream_url = self.selected_stream.url
        extension = self._guess_media_extension(stream_url)
        if extension in {"m3u8", "mpd"}:
            self._set_status(
                "Selected stream is HLS/DASH playlist. Use stream action or choose direct file stream."
            )
            return False

        base_name = self._build_media_basename(
            item=self.selected_item,
            season=season,
            episode=episode,
            quality=self.selected_stream.quality,
        )
        media_path = output_dir / f"{base_name}.{extension}"
        headers = self._merged_request_headers(self.selected_stream.headers)

        self._set_loading(True, "Downloading media...")
        try:
            await self._download_stream_to_path(stream_url, media_path, headers)
        except Exception as exc:
            self._set_status(f"Media download failed: {exc}")
            return False
        finally:
            self._set_loading(False)

        subtitle_count = 0
        if self.selected_subtitles:
            self._set_loading(True, "Downloading subtitles...")
            try:
                subtitle_paths = await asyncio.to_thread(
                    self._download_subtitles_for_playback,
                    self.selected_subtitles,
                    output_dir,
                    headers,
                    filename_prefix=base_name,
                )
                subtitle_count = len(subtitle_paths)
            finally:
                self._set_loading(False)

        self._set_status(f"Saved media: {media_path} | subtitles: {subtitle_count}")
        return True

    def _advance_episode_selector(self) -> bool:
        if self.selected_item is None or self.selected_item.subjectType != SubjectType.TV_SERIES:
            return False

        season, episode = self._read_season_episode()
        if season is None or episode is None:
            return False

        if self.season_map:
            max_episode = self.season_map.get(season, 0)
            if episode < max_episode:
                self._setup_episode_options(season, selected_episode=episode + 1)
                self._update_run_summary()
                return True

            season_keys = sorted(self.season_map.keys())
            for next_season in season_keys:
                if next_season > season:
                    self._setup_episode_selects(selected_season=next_season, selected_episode=1)
                    self._update_run_summary()
                    return True
            return False

        self._setup_episode_options(season, selected_episode=episode + 1)
        self._update_run_summary()
        return True

    def _select_stream_for_auto_continue(
        self,
        preferred_source: str,
        preferred_quality: str | None,
        preferred_audio: str | None,
    ) -> None:
        if not self.resolved_streams:
            self.selected_stream = None
            self._update_subtitle_stream_label()
            self._update_run_summary()
            return

        ranked_streams = self._rank_stream_candidates(
            self.resolved_streams,
            preferred_source=preferred_source,
            preferred_quality=preferred_quality,
            preferred_audio=preferred_audio,
        )
        chosen_stream = ranked_streams[0]
        for index, stream in enumerate(self.resolved_streams):
            if stream is chosen_stream:
                self._handle_stream_selected(index, navigate=False)
                return

        self._handle_stream_selected(0, navigate=False)

    async def _download_stream_to_path(
        self,
        stream_url: str,
        target_path: Path,
        headers: dict[str, str],
    ) -> None:
        request_headers = {
            str(key).strip(): str(value).strip()
            for key, value in headers.items()
            if str(key).strip() and str(value).strip()
        }

        target_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(
            headers=request_headers,
            follow_redirects=True,
            timeout=httpx.Timeout(120.0),
        ) as client:
            async with client.stream("GET", stream_url) as response:
                response.raise_for_status()

                content_type = str(response.headers.get("content-type", "")).lower()
                if "text/html" in content_type:
                    raise RuntimeError("server returned HTML page instead of media content")

                with target_path.open("wb") as output_file:
                    async for chunk in response.aiter_bytes(512 * 1024):
                        if chunk:
                            output_file.write(chunk)

    def _download_subtitles_for_playback(
        self,
        subtitles: list[SubtitleChoice],
        output_dir: Path,
        headers: dict[str, str],
        filename_prefix: str | None = None,
    ) -> list[Path]:
        saved_paths: list[Path] = []
        request_headers = {
            str(key).strip(): str(value).strip()
            for key, value in headers.items()
            if str(key).strip() and str(value).strip()
        }

        with httpx.Client(
            headers=request_headers,
            follow_redirects=True,
            timeout=httpx.Timeout(45.0),
        ) as client:
            for index, subtitle in enumerate(subtitles, start=1):
                safe_label = self._sanitize_filename(subtitle.label)
                if filename_prefix:
                    path = output_dir / f"{filename_prefix}.{index:02d}.{subtitle.language_id}.srt"
                else:
                    path = output_dir / f"{index:02d}_{safe_label}.{subtitle.language_id}.srt"

                try:
                    response = client.get(subtitle.url)
                    response.raise_for_status()
                except Exception:
                    continue

                if not response.content:
                    continue

                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(response.content)
                saved_paths.append(path)

        return saved_paths

    async def _fetch_external_subtitles(
        self,
        *,
        sources: list[str],
        preferred_language_id: str,
    ) -> list[SubtitleChoice]:
        if self.selected_item is None:
            return []

        season, episode = self._read_season_episode()
        if season is None or episode is None:
            return []

        content_type = "series" if self.selected_item.subjectType == SubjectType.TV_SERIES else "movie"
        video_id = build_stremio_video_id(self.selected_item, season=season, episode=episode)
        fetched = await fetch_external_subtitles(
            video_id=video_id,
            content_type=content_type,
            sources=sources,
            preferred_languages=[preferred_language_id] if preferred_language_id else None,
        )

        return [
            SubtitleChoice(
                url=subtitle.url,
                language=subtitle.language,
                language_id=normalize_language_id(subtitle.language),
                label=subtitle.label,
                source=subtitle.source,
            )
            for subtitle in fetched
        ]

    def _resolve_external_sources(self, source_choice: str) -> list[str]:
        if source_choice == "opensubtitles":
            return ["opensubtitles"]

        if source_choice == "subdl":
            if subtitle_source_is_configured("subdl"):
                return ["subdl"]
            self._set_status(
                "SubDL secret missing. "
                f"Set {SUBDL_API_KEY_ENV} or run `moviebox secret-set {SUBDL_API_KEY_ENV}`"
            )
            return []

        if source_choice == "subsource":
            if subtitle_source_is_configured("subsource"):
                return ["subsource"]
            self._set_status(
                "SubSource secret missing. "
                f"Set {SUBSOURCE_API_KEY_ENV} or run `moviebox secret-set {SUBSOURCE_API_KEY_ENV}`"
            )
            return []

        if source_choice == "all":
            selected = ["opensubtitles"]
            missing: list[str] = []
            if subtitle_source_is_configured("subdl"):
                selected.append("subdl")
            else:
                missing.append(SUBDL_API_KEY_ENV)
            if subtitle_source_is_configured("subsource"):
                selected.append("subsource")

            if missing:
                missing_text = ", ".join(missing)
                self._set_status(
                    f"Using OpenSubtitles only for external sources. Missing secrets: {missing_text}"
                )
            return selected

        return []

    def _collect_provider_subtitles(self) -> list[SubtitleChoice]:
        if self.selected_stream is None:
            return []

        collected: list[SubtitleChoice] = []
        all_candidates = [*self.resolved_subtitles, *self.selected_stream.subtitles]
        for subtitle in all_candidates:
            subtitle_url = str(getattr(subtitle, "url", "")).strip()
            if not subtitle_url:
                continue

            language = str(getattr(subtitle, "language", "unknown")).strip() or "unknown"
            label = str(getattr(subtitle, "label", "")).strip() or language
            collected.append(
                SubtitleChoice(
                    url=subtitle_url,
                    language=language,
                    language_id=normalize_language_id(language),
                    label=label,
                    source="provider",
                )
            )

        return collected

    def _read_season_episode(self) -> tuple[int | None, int | None]:
        if self.selected_item is None:
            return (None, None)

        if self.selected_item.subjectType != SubjectType.TV_SERIES:
            return (0, 0)

        season_value = self.query_one("#season_select", Select).value
        episode_value = self.query_one("#episode_select", Select).value

        try:
            season = int(str(season_value or "1"))
            episode = int(str(episode_value or "1"))
        except ValueError:
            self._set_status("Invalid season/episode selection.")
            return (None, None)

        if season < 1 or episode < 1:
            self._set_status("Season and episode must be >= 1.")
            return (None, None)

        if self.season_map:
            if season not in self.season_map:
                available = ", ".join(map(str, sorted(self.season_map.keys())))
                self._set_status(f"Season {season} unavailable. Available: {available}")
                return (None, None)

            max_episode = self.season_map[season]
            if episode > max_episode:
                self._set_status(f"Season {season} has episodes 1..{max_episode}")
                return (None, None)

        return (season, episode)

    def _fill_subtitle_languages_table(self) -> None:
        table = self.query_one("#subtitle_languages_table", DataTable)
        table.clear(columns=False)
        for index, language_id in enumerate(self.subtitle_language_order, start=1):
            table.add_row(
                str(index),
                language_display_name(language_id),
                str(len(self.subtitles_by_language[language_id])),
            )

    def _fill_subtitle_tracks_table(self, tracks: list[SubtitleChoice]) -> None:
        table = self.query_one("#subtitle_tracks_table", DataTable)
        table.clear(columns=False)
        for index, subtitle in enumerate(tracks, start=1):
            table.add_row(
                str(index),
                subtitle.source,
                language_display_name(subtitle.language_id),
                subtitle.label[:46],
                subtitle.url[:90],
            )

    def _clear_subtitle_tables(self) -> None:
        self.query_one("#subtitle_languages_table", DataTable).clear(columns=False)
        self.query_one("#subtitle_tracks_table", DataTable).clear(columns=False)

    def _reset_from_item_selection(self) -> None:
        self.season_map = {}
        self.selected_provider_name = ""
        self.resolved_streams = []
        self.selected_stream = None
        self.resolved_subtitles = []
        self.subtitles_by_language = {}
        self.subtitle_language_order = []
        self.selected_subtitles = []
        self.preferred_subtitle_language_id = None

        self.query_one("#streams_table", DataTable).clear(columns=False)
        self._clear_subtitle_tables()
        self._update_subtitle_stream_label()

    def _update_source_item_label(self) -> None:
        label = self.query_one("#source_item_label", Static)
        if self.selected_item is None:
            label.update("No selected item.")
            return

        title = self.selected_item.title
        year_text = f" ({self.selected_item.year})" if self.selected_item.year else ""
        media_type = "TV Series" if self.selected_item.subjectType == SubjectType.TV_SERIES else "Movie"
        label.update(f"Selected: {title}{year_text} | {media_type} | IMDB: {self.selected_item.imdbId}")

    def _update_subtitle_stream_label(self) -> None:
        label = self.query_one("#subtitle_stream_label", Static)
        if self.selected_stream is None:
            label.update("No selected stream.")
            return

        quality = self.selected_stream.quality or "-"
        audio = self._stream_audio_label(self.selected_stream)
        label.update(f"Selected stream: {self.selected_stream.source} | quality={quality} | audio={audio}")

    def _update_run_summary(self) -> None:
        summary = self.query_one("#run_summary", Static)

        if self.selected_item is None:
            summary.update("No title selected yet.")
            return
        if self.selected_stream is None:
            summary.update(f"Title selected: {self.selected_item.title}. Resolve and choose stream first.")
            return

        action = str(self.query_one("#action_select", Select).value or "stream")
        player_target = self._selected_player_label()
        subtitle_count = len(self.selected_subtitles)
        provider_text = self.selected_provider_name or "-"
        quality = self.selected_stream.quality or "-"
        audio = self._stream_audio_label(self.selected_stream)
        episode_info = ""
        if self.selected_item.subjectType == SubjectType.TV_SERIES:
            season, episode = self._read_season_episode()
            if season is not None and episode is not None:
                episode_info = f" | Episode: S{season:02d}E{episode:02d}"
        summary.update(
            f"Title: {self.selected_item.title} | Provider: {provider_text} | "
            f"Stream: {self.selected_stream.source} [{quality}] | Audio: {audio} | "
            f"Subtitles selected: {subtitle_count} | Player: {player_target} | Action: {action}{episode_info}"
        )

    def _selected_player_target_id(self) -> str:
        return str(self.query_one("#player_select", Select).value or AUTO_TARGET)

    def _selected_player_label(self) -> str:
        target_id = self._selected_player_target_id()
        for target in list_playback_targets():
            if target.id == target_id:
                return target.label
        return target_id

    @staticmethod
    def _stream_audio_label(stream) -> str:
        audio_value = str(getattr(stream, "audio", "")).strip()
        if audio_value:
            return audio_value

        audio_tracks = getattr(stream, "audio_tracks", [])
        if isinstance(audio_tracks, list) and audio_tracks:
            first_track = str(audio_tracks[0]).strip()
            if first_track:
                return first_track

        source = str(getattr(stream, "source", "")).strip()
        matched = re.search(r"\[([^\]]+)\]\s*$", source)
        if matched:
            return matched.group(1).split("/")[0].strip()

        return "-"

    def _stream_fallback_candidates(self, selected_stream) -> list:
        if not self.resolved_streams:
            return [selected_stream]

        return self._rank_stream_candidates(
            self.resolved_streams,
            preferred_source=str(getattr(selected_stream, "source", "") or ""),
            preferred_quality=getattr(selected_stream, "quality", None),
            preferred_audio=self._stream_audio_label(selected_stream),
            preferred_url=str(getattr(selected_stream, "url", "") or ""),
        )

    def _rank_stream_candidates(
        self,
        streams: list,
        *,
        preferred_source: str,
        preferred_quality: str | None,
        preferred_audio: str | None,
        preferred_url: str | None = None,
    ) -> list:
        normalized_preferred_audio = normalize_language_id(preferred_audio)
        preferred_source_text = preferred_source.strip().lower()
        preferred_quality_text = str(preferred_quality or "").strip().lower()
        preferred_url_text = str(preferred_url or "").strip()

        scored: list[tuple[int, int, object]] = []
        for index, stream in enumerate(streams):
            stream_url = str(getattr(stream, "url", "") or "").strip()
            stream_source = str(getattr(stream, "source", "") or "").strip().lower()
            stream_quality = str(getattr(stream, "quality", "") or "").strip().lower()
            stream_audio = normalize_language_id(self._stream_audio_label(stream))

            rank = 100
            if preferred_url_text and stream_url == preferred_url_text:
                rank -= 60
            if stream_source == preferred_source_text:
                rank -= 20
            if stream_quality and stream_quality == preferred_quality_text:
                rank -= 12
            if normalized_preferred_audio != "unknown" and stream_audio == normalized_preferred_audio:
                rank -= 15
            elif stream_audio != "unknown":
                rank -= 3

            scored.append((rank, index, stream))

        scored.sort(key=lambda item: (item[0], item[1]))
        return [stream for _, _, stream in scored]

    async def _collect_playback_stream_candidates(self, selected_stream) -> list:
        candidates = list(self._stream_fallback_candidates(selected_stream))
        seen_urls = {str(getattr(stream, "url", "") or "").strip() for stream in candidates}

        if self.selected_item is None or self.selected_provider_name == "moviebox":
            return candidates

        season, episode = self._read_season_episode()
        if season is None or episode is None:
            return candidates

        try:
            _, moviebox_streams, _ = await SourceResolver(provider_name="moviebox").resolve(
                title=self.selected_item.title,
                subject_type=self.selected_item.subjectType,
                year=self.selected_item.year,
                season=season,
                episode=episode,
                imdb_id=self.selected_item.imdbId,
                tmdb_id=self.selected_item.tmdbId,
            )
        except Exception:
            return candidates

        ranked_moviebox_streams = self._rank_stream_candidates(
            moviebox_streams,
            preferred_source=str(getattr(selected_stream, "source", "") or ""),
            preferred_quality=getattr(selected_stream, "quality", None),
            preferred_audio=self._stream_audio_label(selected_stream),
            preferred_url=str(getattr(selected_stream, "url", "") or ""),
        )

        for stream in ranked_moviebox_streams:
            stream_url = str(getattr(stream, "url", "") or "").strip()
            if not stream_url or stream_url in seen_urls:
                continue
            candidates.append(stream)
            seen_urls.add(stream_url)

        return candidates

    @staticmethod
    def _dedupe_urls(urls: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for url in urls:
            cleaned = str(url).strip()
            if not cleaned or cleaned in seen:
                continue
            deduped.append(cleaned)
            seen.add(cleaned)
        return deduped

    def _build_android_subtitle_attempts(self, stream, *, target_id: str) -> list[list[str]]:
        selected_urls = self._dedupe_urls(
            [subtitle.url for subtitle in self.selected_subtitles if subtitle.url]
        )

        preferred_language = self.preferred_subtitle_language_id
        if not preferred_language and self.selected_subtitles:
            preferred_language = self.selected_subtitles[0].language_id

        provider_subtitles = []
        provider_subtitles.extend(getattr(stream, "subtitles", []))
        provider_subtitles.extend(self.resolved_subtitles)

        ranked_provider_urls: list[tuple[int, int, str]] = []
        for index, subtitle in enumerate(provider_subtitles):
            subtitle_url = str(getattr(subtitle, "url", "") or "").strip()
            if not subtitle_url or subtitle_url in selected_urls:
                continue

            language_id = normalize_language_id(getattr(subtitle, "language", None))
            score = 1
            if preferred_language and language_id == preferred_language:
                score = 0
            ranked_provider_urls.append((score, index, subtitle_url))

        ranked_provider_urls.sort(key=lambda item: (item[0], item[1]))
        provider_urls = self._dedupe_urls([url for _, _, url in ranked_provider_urls])

        attempts: list[list[str]] = []

        prefer_provider_first = target_id in {"android_vlc", "android_mx_pro", "android_mx_free"}
        if prefer_provider_first:
            if provider_urls:
                attempts.append(provider_urls)
            if selected_urls:
                attempts.append(selected_urls)
        else:
            if selected_urls:
                attempts.append(selected_urls)
            if provider_urls:
                attempts.append(provider_urls)

        attempts.append([])
        return attempts

    async def _confirm_continue_next_episode(
        self,
        *,
        default_continue: bool,
        on_continue: Callable[[], Awaitable[bool]] | None = None,
        on_stop: Callable[[], Awaitable[bool]] | None = None,
    ) -> bool:
        season, episode = self._read_season_episode()
        if season is None or episode is None:
            return default_continue

        async def _default_on_continue() -> bool:
            return True

        async def _default_on_stop() -> bool:
            return False

        message = f"Current selection S{season:02d}E{episode:02d}. Continue to next episode?"
        try:
            answer = await self.push_screen_wait(
                ContinuePromptScreen(
                    message,
                    on_continue=on_continue or _default_on_continue,
                    on_stop=on_stop or _default_on_stop,
                )
            )
            return bool(answer)
        except Exception:
            return default_continue

    async def _prepare_next_episode_from_current(self, current_stream, *, auto_start: bool) -> bool:
        if not self._advance_episode_selector():
            self._set_status("Reached last known episode in metadata.")
            return False

        next_resolved = await self._handle_resolve_streams(silent=True)
        if not next_resolved:
            self._set_status("Unable to resolve next episode streams.")
            return False

        self._select_stream_for_auto_continue(
            current_stream.source,
            current_stream.quality,
            self._stream_audio_label(current_stream),
        )

        await self._handle_subtitle_fetch(silent=True)
        self._set_page("run")
        if auto_start:
            self._set_status("Auto-continue: starting next episode...")
        else:
            self._set_status("Prepared next episode. Press Run when ready.")
        return True

    def _set_page(self, page: str) -> None:
        if page not in self.PAGES:
            return

        switcher = self.query_one("#page_switcher", ContentSwitcher)
        switcher.current = f"page_{page}"

        for known_page in self.PAGES:
            button = self.query_one(f"#nav_{known_page}_button", Button)
            if known_page == page:
                button.add_class("active-nav")
            else:
                button.remove_class("active-nav")

        if page == "search":
            self.query_one("#query_input", Input).focus()

    def _set_loading(self, loading: bool, label: str = "") -> None:
        try:
            loading_row = self.query_one("#loading_row")
            loading_label = self.query_one("#loading_label", Static)
        except NoMatches:
            return

        if loading:
            loading_row.remove_class("hidden")
            if label:
                loading_label.update(label)
            return

        loading_row.add_class("hidden")
        loading_label.update("Loading...")

    def _set_status(self, message: str) -> None:
        try:
            self.query_one("#status", Static).update(message)
        except NoMatches:
            return

    def _apply_action_ui_state(self, action: str) -> None:
        output_dir_input = self.query_one("#output_dir_input", Input)
        player_select = self.query_one("#player_select", Select)
        run_hint = self.query_one("#run_hint", Static)
        if action == "download":
            output_dir_input.remove_class("hidden")
            player_select.add_class("hidden")
            run_hint.update("Download mode: saves media and selected subtitle files.")
        else:
            output_dir_input.add_class("hidden")
            player_select.remove_class("hidden")
            run_hint.update("Stream mode: pick player target and run with stream fallback.")

        self._update_run_summary()

    def _merged_request_headers(self, stream_headers: dict[str, str]) -> dict[str, str]:
        merged = dict(DOWNLOAD_REQUEST_HEADERS)
        for key, value in stream_headers.items():
            key_text = str(key).strip()
            value_text = str(value).strip()
            if key_text and value_text:
                merged[key_text] = value_text
        return merged

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._\- ()]+", "", value).strip()
        return cleaned or "media"

    def _build_media_basename(
        self,
        *,
        item: StremioSearchItem,
        season: int,
        episode: int,
        quality: str | None,
    ) -> str:
        parts = [item.title]
        if item.year:
            parts.append(f"({item.year})")
        if item.subjectType == SubjectType.TV_SERIES:
            parts.append(f"S{season:02d}E{episode:02d}")
        if quality:
            parts.append(str(quality))
        return self._sanitize_filename(" ".join(parts))

    @staticmethod
    def _guess_media_extension(url: str) -> str:
        suffix = Path(urlparse(url).path).suffix.strip().lower()
        if suffix.startswith("."):
            suffix = suffix[1:]
        if suffix and len(suffix) <= 8:
            return suffix
        return "mp4"


def run_interactive_tui() -> None:
    """Run page-based Textual TUI app."""

    InteractiveTextualApp().run()
