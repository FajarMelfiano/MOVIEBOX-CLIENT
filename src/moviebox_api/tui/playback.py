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
    """Return whether playback should run through Android intent path."""

    return _android_playback_mode() in {"mpv_app", "chooser"}


def _android_playback_mode() -> str:
    """Return Android playback mode: mpv_app, chooser, or none."""

    target = os.getenv("MOVIEBOX_PLAYBACK_TARGET", "auto").strip().lower()
    is_termux = is_termux_environment()

    if target in {"android", "chooser"}:
        return "chooser"
    if target in {"android-mpv", "mpv-android"}:
        return "mpv_app"
    if target == "mpv":
        return "mpv_app" if is_termux else "none"
    if target in {"mpv-cli", "desktop", "vlc"}:
        return "none"
    if target == "auto":
        return "mpv_app" if is_termux else "none"
    return "mpv_app" if is_termux else "none"


def _is_direct_media_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith((".m3u8", ".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpd", ".ts"))


def _open_android_chooser(url: str) -> bool:
    if shutil.which("termux-open-url"):
        return subprocess.run(["termux-open-url", url], check=False).returncode == 0

    if shutil.which("am"):
        return _run_android_intent(["am", "start", "-a", "android.intent.action.VIEW", "-d", url])

    return False


def _run_android_intent(command: list[str]) -> bool:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    combined_output = f"{result.stdout}\n{result.stderr}".lower()
    if "error:" in combined_output or "exception" in combined_output:
        return False
    return result.returncode == 0


def _open_android_mpv_app(url: str) -> bool:
    if not shutil.which("am"):
        return False

    commands = [
        ["am", "start", "-a", "android.intent.action.VIEW", "-d", url, "-n", "is.xyz.mpv/.MPVActivity"],
        ["am", "start", "-a", "android.intent.action.VIEW", "-d", url, "-n", "is.xyz.mpv/.MainActivity"],
        ["am", "start", "-a", "android.intent.action.VIEW", "-d", url, "-p", "is.xyz.mpv"],
    ]
    for command in commands:
        if _run_android_intent(command):
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

    android_mode = _android_playback_mode()

    if android_mode == "mpv_app":
        if _open_android_mpv_app(stream_url):
            return "Opened MPV Android app"
        if _open_android_chooser(stream_url):
            return "Opened Android chooser (MPV app unavailable)"
        _open_url_fallback(stream_url)
        return "Opened URL via browser fallback"

    if android_mode == "chooser":
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
