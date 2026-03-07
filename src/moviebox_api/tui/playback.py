"""Playback adapters for Textual TUI sessions."""

from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlparse


def is_termux_environment() -> bool:
    """Return True when running inside Termux on Android."""

    if os.getenv("TERMUX_VERSION"):
        return True
    if os.getenv("PREFIX", "").startswith("/data/data/com.termux"):
        return True
    return shutil.which("termux-open-url") is not None


def should_use_android_chooser() -> bool:
    """Return whether playback should default to Android app chooser."""

    target = os.getenv("MOVIEBOX_PLAYBACK_TARGET", "auto").strip().lower()
    if target == "android":
        return True
    if target in {"mpv", "vlc", "desktop"}:
        return False
    return is_termux_environment()


def _is_direct_media_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith((".m3u8", ".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpd", ".ts"))


def _open_android_chooser(url: str) -> bool:
    if shutil.which("termux-open-url"):
        subprocess.run(["termux-open-url", url], check=False)
        return True

    if shutil.which("am"):
        subprocess.run(
            ["am", "start", "-a", "android.intent.action.VIEW", "-d", url],
            check=False,
        )
        return True

    return False


def _open_url_fallback(url: str) -> None:
    if webbrowser.open(url, new=2):
        return
    if shutil.which("xdg-open"):
        subprocess.run(["xdg-open", url], check=False)
        return
    raise RuntimeError(f"Unable to open URL automatically: {url}")


def play_stream(
    stream_url: str,
    headers: dict[str, str],
    subtitle_paths: list[Path] | None = None,
) -> str:
    """Play stream URL based on environment and available players.

    Returns a short status message to show in the UI.
    """

    subtitle_paths = subtitle_paths or []

    if should_use_android_chooser():
        if _open_android_chooser(stream_url):
            return "Opened Android app chooser"
        _open_url_fallback(stream_url)
        return "Opened URL via browser fallback"

    if shutil.which("mpv"):
        if _run_mpv(stream_url, headers, subtitle_paths):
            return "Launched mpv"

    if shutil.which("vlc"):
        _run_vlc(stream_url, headers, subtitle_paths)
        return "Launched VLC"

    _open_url_fallback(stream_url)
    return "Opened URL via browser fallback"


def _run_mpv(stream_url: str, headers: dict[str, str], subtitle_paths: list[Path]) -> bool:
    base_command = ["mpv"]
    for key, value in headers.items():
        key_value = str(key).strip()
        value_text = str(value).strip()
        if key_value and value_text:
            base_command.append(f"--http-header-fields={key_value}: {value_text}")

    if subtitle_paths:
        base_command.append("--sid=auto")
        for subtitle_path in subtitle_paths:
            base_command.append(f"--sub-file={subtitle_path.as_posix()}")

    if _is_direct_media_url(stream_url):
        command = [*base_command, "--no-ytdl", stream_url]
        return subprocess.run(command, check=False).returncode == 0

    direct_command = [*base_command, "--no-ytdl", stream_url]
    if subprocess.run(direct_command, check=False).returncode == 0:
        return True

    ytdl_command = [*base_command, "--ytdl=yes"]
    if shutil.which("yt-dlp"):
        ytdl_command.append("--script-opts=ytdl_hook-ytdl_path=yt-dlp")
    ytdl_command.append(stream_url)
    return subprocess.run(ytdl_command, check=False).returncode == 0


def _run_vlc(stream_url: str, headers: dict[str, str], subtitle_paths: list[Path]) -> None:
    command = ["vlc"]
    user_agent = headers.get("User-Agent")
    referer = headers.get("Referer")
    if user_agent:
        command.append(f":http-user-agent={user_agent}")
    if referer:
        command.append(f"--http-referrer={referer}")
    for subtitle_path in subtitle_paths:
        command.append(f"--sub-file={subtitle_path.as_posix()}")
    command.append(stream_url)
    subprocess.run(command, check=False)
