"""Interactive terminal UI for code-first stream resolution."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

import httpx
from pydantic import HttpUrl
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from moviebox_api.constants import CURRENT_WORKING_DIR, DOWNLOAD_REQUEST_HEADERS, SubjectType
from moviebox_api.download import CaptionFileDownloader, MediaFileDownloader
from moviebox_api.helpers import get_event_loop
from moviebox_api.models import CaptionFileMetadata, MediaFileMetadata
from moviebox_api.providers import SUPPORTED_PROVIDERS, normalize_provider_name
from moviebox_api.providers.models import ProviderStream, ProviderSubtitle
from moviebox_api.providers.vega_provider import ENV_VEGA_PROVIDER_KEY
from moviebox_api.source import SourceResolver
from moviebox_api.stremio.catalog import (
    StremioSearchItem,
    build_stremio_video_id,
    extract_series_seasons,
    fetch_cinemeta_meta,
    search_cinemeta_catalog,
)
from moviebox_api.stremio.subtitle_sources import (
    ExternalSubtitle,
    SUBDL_API_KEY_ENV,
    SUBSOURCE_API_KEY_ENV,
    fetch_external_subtitles,
    subtitle_source_is_configured,
)

console = Console()


@dataclass(slots=True)
class _SubtitleChoice:
    url: str
    language: str
    language_id: str
    label: str
    source: str


def _sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._\- ()]+", "", value).strip()
    return cleaned or "media"


def _normalise_resolution(value: str | int | None, default: int = 720) -> int:
    if isinstance(value, int) and value > 0:
        return value

    if isinstance(value, str):
        matched = re.search(r"(\d{3,4})", value)
        if matched:
            return int(matched.group(1))

    return default


def _normalise_language_id(language: str | None) -> str:
    if not language:
        return "unknown"

    lowered = language.strip().lower()
    if not lowered:
        return "unknown"

    alias_map = {
        "english": "eng",
        "indonesian": "ind",
        "spanish": "spa",
        "french": "fre",
        "portuguese": "por",
        "russian": "rus",
        "arabic": "ara",
        "turkish": "tur",
        "japanese": "jpn",
        "korean": "kor",
        "chinese": "zho",
    }
    if lowered in alias_map:
        return alias_map[lowered]

    if lowered.isascii() and len(lowered) in {2, 3}:
        return lowered

    compact = re.sub(r"[^a-z]", "", lowered)
    if len(compact) >= 3:
        return compact[:3]
    if compact:
        return compact
    return "unknown"


def _is_direct_media_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return path.endswith(
        (
            ".m3u8",
            ".mp4",
            ".mkv",
            ".webm",
            ".avi",
            ".mov",
            ".m4v",
            ".mpd",
            ".ts",
        )
    )


def _pick_from_table(title: str, headers: list[str], rows: list[list[str]], default: str = "1") -> int:
    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan")
    for header in headers:
        table.add_column(header)
    for row in rows:
        table.add_row(*row)
    console.print(table)

    max_index = str(len(rows))
    choice = Prompt.ask("Choose", default=default)
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(rows):
        raise ValueError(f"Invalid choice '{choice}'. Pick between 1 and {max_index}.")
    return int(choice) - 1


class MovieBoxTUI:
    def show_header(self) -> None:
        console.print(
            Panel("MOVIEBOX interactive", subtitle="Cinemeta search + provider streams", border_style="cyan")
        )

    def run(self) -> None:
        while True:
            console.clear()
            self.show_header()
            console.print("1) Movies")
            console.print("2) TV series")
            console.print("0) Exit")
            choice = Prompt.ask("Select", choices=["0", "1", "2"], default="1")

            if choice == "0":
                console.print("Bye.")
                return

            subject_type = SubjectType.MOVIES if choice == "1" else SubjectType.TV_SERIES
            try:
                self._run_search_flow(subject_type)
            except KeyboardInterrupt:
                console.print("Interrupted.")
                return
            except Exception as exc:
                console.print(f"[red]Error:[/red] {exc}")
                Prompt.ask("Press Enter to continue", default="")

    def _run_search_flow(self, subject_type: SubjectType) -> None:
        query = Prompt.ask("Search query").strip()
        if not query:
            raise ValueError("Search query cannot be empty")

        items = get_event_loop().run_until_complete(search_cinemeta_catalog(query, subject_type))
        if not items:
            console.print("No results found.")
            return

        selected = self._choose_item(items)
        season = 0
        episode = 0
        if selected.subjectType == SubjectType.TV_SERIES:
            season, episode = self._choose_episode(selected)

        provider_name = self._choose_provider()
        action = Prompt.ask("Action", choices=["stream", "download"], default="stream")

        item, streams, subtitles = get_event_loop().run_until_complete(
            SourceResolver(provider_name=provider_name).resolve(
                title=selected.title,
                subject_type=selected.subjectType,
                year=selected.year,
                season=season,
                episode=episode,
                imdb_id=selected.imdbId,
                tmdb_id=selected.tmdbId,
            )
        )
        if item is None or not streams:
            console.print("No stream found for selected provider.")
            return

        stream = self._choose_stream(streams)
        subtitle_choices = self._choose_subtitle(
            action=action,
            item=selected,
            stream_subtitles=stream.subtitles,
            provider_subtitles=subtitles,
            season=season,
            episode=episode,
        )

        if action == "stream":
            self._stream(stream.url, stream.headers, subtitle_choices)
            return

        self._download(
            selected,
            stream.url,
            stream.quality,
            stream.headers,
            subtitle_choices,
            season,
            episode,
        )

    def _choose_item(self, items: list[StremioSearchItem]) -> StremioSearchItem:
        rows: list[list[str]] = []
        top_items = items[:20]
        for index, item in enumerate(top_items, start=1):
            rows.append(
                [
                    str(index),
                    item.title,
                    str(item.year or "-"),
                    f"{item.imdbRatingValue:.1f}",
                    ", ".join(item.genre[:2]) or "-",
                ]
            )
        selected_index = _pick_from_table("Search Results", ["#", "Title", "Year", "Rating", "Genre"], rows)
        return top_items[selected_index]

    def _choose_episode(self, item: StremioSearchItem) -> tuple[int, int]:
        meta = get_event_loop().run_until_complete(fetch_cinemeta_meta(item))
        seasons = extract_series_seasons(meta)
        if not seasons:
            raise RuntimeError("Could not load season/episode information from Cinemeta")

        season_rows = [
            [str(index), f"Season {season}", f"{episodes} episodes"]
            for index, (season, episodes) in enumerate(seasons.items(), start=1)
        ]
        season_idx = _pick_from_table("Seasons", ["#", "Season", "Episodes"], season_rows)
        season_number = list(seasons.keys())[season_idx]
        max_episode = seasons[season_number]
        episode_number = int(Prompt.ask("Episode number", default="1"))
        if episode_number < 1 or episode_number > max_episode:
            raise ValueError(f"Episode out of range. Season {season_number} has 1..{max_episode}")
        return season_number, episode_number

    def _choose_provider(self) -> str:
        rows = [[str(index), provider] for index, provider in enumerate(SUPPORTED_PROVIDERS, start=1)]
        provider_index = _pick_from_table("Providers", ["#", "Provider"], rows)
        base_provider = SUPPORTED_PROVIDERS[provider_index]

        if base_provider == "vega":
            default_value = os.getenv(ENV_VEGA_PROVIDER_KEY, "autoEmbed").strip() or "autoEmbed"
            dynamic_value = Prompt.ask("Vega module value", default=default_value).strip()
            return normalize_provider_name(f"vega:{dynamic_value}")

        return normalize_provider_name(base_provider)

    def _choose_stream(self, streams: list[ProviderStream]) -> ProviderStream:
        rows: list[list[str]] = []
        for index, stream in enumerate(streams, start=1):
            rows.append(
                [
                    str(index),
                    stream.source,
                    stream.quality or "-",
                    "yes" if stream.headers else "no",
                    stream.url[:72],
                ]
            )
        selected_index = _pick_from_table("Streams", ["#", "Source", "Quality", "Headers", "URL"], rows)
        return streams[selected_index]

    def _choose_subtitle(
        self,
        *,
        action: str,
        item: StremioSearchItem,
        stream_subtitles: list[ProviderSubtitle],
        provider_subtitles: list[ProviderSubtitle],
        season: int,
        episode: int,
    ) -> list[_SubtitleChoice]:
        options = ["none", "provider", "opensubtitles", "subdl", "subsource", "all"]
        console.print("Subtitle source options: " + ", ".join(options))
        source_choice = Prompt.ask("Subtitle source", choices=options, default="provider")
        if source_choice == "none":
            return []

        preferred_language_id = Prompt.ask(
            "Preferred subtitle language id (optional, for example eng/ind)",
            default="",
        ).strip()
        preferred_language = preferred_language_id or None

        subtitle_entries: list[_SubtitleChoice] = []
        if source_choice in {"provider", "all"}:
            subtitle_entries.extend(self._collect_provider_subtitles(stream_subtitles, provider_subtitles))

        if source_choice in {"opensubtitles", "subdl", "subsource", "all"}:
            external_sources = self._resolve_external_sources(source_choice)
            if external_sources:
                external_items = self._fetch_external_subtitles(
                    item,
                    season,
                    episode,
                    external_sources,
                    preferred_languages=[preferred_language] if preferred_language else None,
                )
                subtitle_entries.extend(external_items)

        deduped: dict[str, _SubtitleChoice] = {}
        for subtitle in subtitle_entries:
            deduped[subtitle.url] = subtitle
        subtitle_entries = list(deduped.values())

        if not subtitle_entries:
            return []

        selected_language_id = self._choose_subtitle_language(subtitle_entries, preferred_language)
        filtered_entries = [
            subtitle for subtitle in subtitle_entries if subtitle.language_id == selected_language_id
        ]
        if not filtered_entries:
            return []

        if action == "stream":
            console.print(
                f"Using {len(filtered_entries)} subtitle tracks for language '{selected_language_id}'."
            )
            return filtered_entries

        rows = [
            [str(index), subtitle.source, subtitle.language_id, subtitle.label[:40], subtitle.url[:70]]
            for index, subtitle in enumerate(filtered_entries, start=1)
        ]
        selected_index = _pick_from_table("Subtitles", ["#", "Source", "Lang", "Label", "URL"], rows)
        return [filtered_entries[selected_index]]

    def _choose_subtitle_language(
        self,
        subtitle_entries: list[_SubtitleChoice],
        preferred_language: str | None,
    ) -> str:
        counts: dict[str, int] = {}
        for subtitle in subtitle_entries:
            counts[subtitle.language_id] = counts.get(subtitle.language_id, 0) + 1

        language_ids = sorted(counts.keys(), key=lambda language_id: (-counts[language_id], language_id))

        if preferred_language:
            normalized_preferred = _normalise_language_id(preferred_language)
            if normalized_preferred in counts:
                return normalized_preferred

        rows = [
            [str(index), language_id, str(counts[language_id])]
            for index, language_id in enumerate(language_ids, start=1)
        ]
        selected_index = _pick_from_table("Subtitle Languages", ["#", "Lang", "Count"], rows)
        return language_ids[selected_index]

    def _collect_provider_subtitles(
        self,
        stream_subtitles: list[ProviderSubtitle],
        provider_subtitles: list[ProviderSubtitle],
    ) -> list[_SubtitleChoice]:
        entries: list[_SubtitleChoice] = []
        for subtitle in [*provider_subtitles, *stream_subtitles]:
            url = str(getattr(subtitle, "url", "")).strip()
            if not url:
                continue
            language = str(getattr(subtitle, "language", "unknown")).strip() or "unknown"
            label = str(getattr(subtitle, "label", "")).strip() or language
            entries.append(
                _SubtitleChoice(
                    url=url,
                    language=language,
                    language_id=_normalise_language_id(language),
                    label=label,
                    source="provider",
                )
            )
        return entries

    def _resolve_external_sources(self, source_choice: str) -> list[str]:
        if source_choice == "opensubtitles":
            return ["opensubtitles"]
        if source_choice == "subdl":
            if not subtitle_source_is_configured("subdl"):
                console.print(
                    "[yellow]SubDL secret is missing. "
                    f"Set {SUBDL_API_KEY_ENV} or run `moviebox secret-set {SUBDL_API_KEY_ENV}`.[/yellow]"
                )
                return []
            return ["subdl"] if subtitle_source_is_configured("subdl") else []
        if source_choice == "subsource":
            if not subtitle_source_is_configured("subsource"):
                console.print(
                    "[yellow]SubSource secret is missing. "
                    f"Set {SUBSOURCE_API_KEY_ENV} or run `moviebox secret-set {SUBSOURCE_API_KEY_ENV}`.[/yellow]"
                )
                return []
            return ["subsource"] if subtitle_source_is_configured("subsource") else []

        if source_choice == "all":
            selected = ["opensubtitles"]
            for source_name in ("subdl", "subsource"):
                if subtitle_source_is_configured(source_name):
                    selected.append(source_name)
            if "subdl" not in selected:
                console.print(
                    "[yellow]SubDL secret is missing; skipping subdl "
                    f"({SUBDL_API_KEY_ENV} or `moviebox secret-set {SUBDL_API_KEY_ENV}`).[/yellow]"
                )
            if "subsource" not in selected:
                console.print(
                    "[yellow]SubSource secret is missing; skipping subsource "
                    f"({SUBSOURCE_API_KEY_ENV} or `moviebox secret-set {SUBSOURCE_API_KEY_ENV}`).[/yellow]"
                )
            return selected

        return []

    def _merged_request_headers(self, stream_headers: dict[str, str]) -> dict[str, str]:
        merged = dict(DOWNLOAD_REQUEST_HEADERS)
        for key, value in stream_headers.items():
            key_value = str(key).strip()
            header_value = str(value).strip()
            if not key_value or not header_value:
                continue
            merged[key_value] = header_value
        return merged

    def _fetch_external_subtitles(
        self,
        item: StremioSearchItem,
        season: int,
        episode: int,
        sources: list[str],
        preferred_languages: list[str] | None = None,
    ) -> list[_SubtitleChoice]:
        content_type = "series" if item.subjectType == SubjectType.TV_SERIES else "movie"
        video_id = build_stremio_video_id(item, season=season, episode=episode)
        fetched: list[ExternalSubtitle] = get_event_loop().run_until_complete(
            fetch_external_subtitles(
                video_id=video_id,
                content_type=content_type,
                sources=sources,
                preferred_languages=preferred_languages,
            )
        )
        return [
            _SubtitleChoice(
                url=subtitle.url,
                language=subtitle.language,
                language_id=_normalise_language_id(subtitle.language),
                label=subtitle.label,
                source=subtitle.source,
            )
            for subtitle in fetched
        ]

    def _stream(
        self,
        stream_url: str,
        headers: dict[str, str],
        subtitles: list[_SubtitleChoice],
    ) -> None:
        merged_headers = self._merged_request_headers(headers)

        if not _is_direct_media_url(stream_url):
            self._stream_unknown_url(stream_url, merged_headers, subtitles)
            return

        player = self._choose_player(force_mpv=bool(subtitles))
        subtitle_paths: list[str] = []
        temp_dir: tempfile.TemporaryDirectory[str] | None = None

        if subtitles:
            temp_dir = tempfile.TemporaryDirectory(prefix="moviebox-subtitle-")
            for subtitle in subtitles:
                try:
                    subtitle_path = self._download_subtitle_file(
                        subtitle,
                        Path(temp_dir.name),
                        merged_headers,
                    )
                except Exception as exc:
                    console.print(
                        f"[yellow]Could not attach subtitle '{subtitle.label}' ({subtitle.language_id}): {exc}[/yellow]"
                    )
                    continue
                subtitle_paths.append(subtitle_path)

        try:
            command: list[str]
            if player == "mpv":
                command = ["mpv", "--no-ytdl"]
                for key, value in merged_headers.items():
                    command.append(f"--http-header-fields={key}: {value}")
                if subtitle_paths:
                    command.append("--sid=auto")
                    for subtitle_path in subtitle_paths:
                        command.append(f"--sub-file={subtitle_path}")
                command.append(stream_url)
            else:
                command = ["vlc"]
                user_agent = merged_headers.get("User-Agent")
                referer = merged_headers.get("Referer")
                if user_agent:
                    command.append(f":http-user-agent={user_agent}")
                if referer:
                    command.append(f"--http-referrer={referer}")
                for subtitle_path in subtitle_paths:
                    command.append(f"--sub-file={subtitle_path}")
                command.append(stream_url)

            console.print(f"Launching {player}...")
            subprocess.run(command, check=False)
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()

    def _stream_unknown_url(
        self,
        stream_url: str,
        headers: dict[str, str],
        subtitles: list[_SubtitleChoice],
    ) -> None:
        if not shutil.which("mpv"):
            console.print("[yellow]mpv not found, opening URL in browser...[/yellow]")
            self._open_in_browser(stream_url)
            return

        subtitle_paths: list[str] = []
        temp_dir: tempfile.TemporaryDirectory[str] | None = None
        if subtitles:
            temp_dir = tempfile.TemporaryDirectory(prefix="moviebox-subtitle-")
            for subtitle in subtitles:
                try:
                    subtitle_path = self._download_subtitle_file(subtitle, Path(temp_dir.name), headers)
                except Exception as exc:
                    console.print(
                        f"[yellow]Could not attach subtitle '{subtitle.label}' ({subtitle.language_id}): {exc}[/yellow]"
                    )
                    continue
                subtitle_paths.append(subtitle_path)

        try:

            def _build_base_command() -> list[str]:
                command = ["mpv"]
                for key, value in headers.items():
                    command.append(f"--http-header-fields={key}: {value}")
                if subtitle_paths:
                    command.append("--sid=auto")
                    for subtitle_path in subtitle_paths:
                        command.append(f"--sub-file={subtitle_path}")
                return command

            console.print("Trying to load URL in mpv (direct mode)...")
            direct_command = [*_build_base_command(), "--no-ytdl", stream_url]
            direct_result = subprocess.run(direct_command, check=False)
            if direct_result.returncode == 0:
                return

            console.print("Trying mpv with yt-dlp fallback...")
            ytdl_command = [*_build_base_command(), "--ytdl=yes"]
            if shutil.which("yt-dlp"):
                ytdl_command.append("--script-opts=ytdl_hook-ytdl_path=yt-dlp")
            ytdl_command.append(stream_url)
            ytdl_result = subprocess.run(ytdl_command, check=False)
            if ytdl_result.returncode == 0:
                return

            console.print("[yellow]mpv could not load this URL. Opening browser fallback...[/yellow]")
            if not shutil.which("yt-dlp"):
                console.print("[yellow]Tip: install yt-dlp to improve fallback support.[/yellow]")
            self._open_in_browser(stream_url)
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()

    def _open_in_browser(self, url: str) -> None:
        opened = webbrowser.open(url, new=2)
        if opened:
            return
        if shutil.which("xdg-open"):
            subprocess.run(["xdg-open", url], check=False)
            return
        raise RuntimeError("Could not open browser automatically. Open this URL manually: " + url)

    def _choose_player(self, *, force_mpv: bool = False) -> str:
        available_players = [name for name in ("mpv", "vlc") if shutil.which(name)]
        if not available_players:
            raise RuntimeError("No supported player found. Install mpv or vlc.")
        if force_mpv and "mpv" in available_players:
            console.print("[green]Using mpv so you can switch subtitle tracks in-player.[/green]")
            return "mpv"
        if len(available_players) == 1:
            return available_players[0]

        rows = [[str(index), name] for index, name in enumerate(available_players, start=1)]
        selected_index = _pick_from_table("Players", ["#", "Name"], rows)
        return available_players[selected_index]

    def _download(
        self,
        item: StremioSearchItem,
        stream_url: str,
        quality: str | None,
        headers: dict[str, str],
        subtitles: list[_SubtitleChoice],
        season: int,
        episode: int,
    ) -> None:
        output_dir = Path(Prompt.ask("Output directory", default=str(CURRENT_WORKING_DIR))).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        merged_headers = self._merged_request_headers(headers)

        title_bits = [item.title]
        if item.year:
            title_bits.append(f"({item.year})")
        if item.subjectType == SubjectType.TV_SERIES:
            title_bits.append(f"S{season:02d}E{episode:02d}")
        base_filename = _sanitize_filename(" ".join(title_bits))

        media_file = MediaFileMetadata(
            id=hashlib.sha1(stream_url.encode(), usedforsecurity=False).hexdigest(),
            url=cast(HttpUrl, stream_url),
            resolution=_normalise_resolution(quality),
            size=0,
        )

        media_filename = f"{base_filename}.{media_file.ext or 'mp4'}"
        media_downloader = MediaFileDownloader(dir=output_dir, request_headers=merged_headers)
        media_result = get_event_loop().run_until_complete(
            media_downloader.run(media_file=media_file, filename=media_filename)
        )
        saved_media_to = getattr(media_result, "saved_to", None)
        if saved_media_to is None:
            raise RuntimeError("Media download did not return a file path")
        console.print(f"Saved media: {saved_media_to}")

        if not subtitles:
            return

        try:
            subtitle_path = self._download_subtitle_file(
                subtitles[0], output_dir, merged_headers, filename_prefix=base_filename
            )
            console.print(f"Saved subtitle: {subtitle_path}")
        except Exception as exc:
            console.print(f"[yellow]Failed to save subtitle: {exc}[/yellow]")

    def _download_subtitle_file(
        self,
        subtitle: _SubtitleChoice,
        output_dir: Path,
        headers: dict[str, str],
        filename_prefix: str | None = None,
    ) -> str:
        caption_file = CaptionFileMetadata(
            id=hashlib.sha1(subtitle.url.encode(), usedforsecurity=False).hexdigest(),
            lan=subtitle.language_id or (subtitle.language[:3] if subtitle.language else "sub"),
            lanName=subtitle.label,
            url=cast(HttpUrl, subtitle.url),
            size=0,
            delay=0,
        )
        filename_root = filename_prefix or _sanitize_filename(subtitle.label or "subtitle")
        caption_filename = f"{filename_root}.{caption_file.lan}.{caption_file.ext or 'srt'}"
        target_path = output_dir / caption_filename

        caption_downloader = CaptionFileDownloader(
            dir=output_dir,
            request_headers=headers,
            tasks=1,
        )
        try:
            result = get_event_loop().run_until_complete(
                caption_downloader.run(
                    caption_file=caption_file,
                    filename=caption_filename,
                    suppress_incompatible_error=True,
                    file_size=1,
                )
            )
            saved_to = getattr(result, "saved_to", None)
            if saved_to is not None:
                return str(saved_to)
        except Exception:
            pass

        try:
            self._download_subtitle_via_httpx(subtitle.url, target_path, headers)
            return str(target_path)
        except Exception as exc:
            raise RuntimeError(f"Subtitle download failed for {subtitle.url}: {exc}") from exc

    def _download_subtitle_via_httpx(
        self,
        url: str,
        target_path: Path,
        headers: dict[str, str],
    ) -> None:
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
            response = client.get(url)
            response.raise_for_status()
            content = response.content

        if not content:
            raise RuntimeError("received empty subtitle content")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)


def run_interactive_menu() -> None:
    MovieBoxTUI().run()


if __name__ == "__main__":
    run_interactive_menu()
