"""Playback adapters for Textual TUI sessions."""

from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

AUTO_TARGET = "auto"

ANDROID_MPV_TARGET = "android_mpv"
ANDROID_MX_PRO_TARGET = "android_mx_pro"
ANDROID_MX_FREE_TARGET = "android_mx_free"
ANDROID_VLC_TARGET = "android_vlc"
ANDROID_CHOOSER_TARGET = "android_chooser"

CLI_MPV_TARGET = "mpv_cli"
CLI_VLC_TARGET = "vlc_cli"
BROWSER_TARGET = "browser"

_ANDROID_TARGET_IDS = {
    ANDROID_MPV_TARGET,
    ANDROID_MX_PRO_TARGET,
    ANDROID_MX_FREE_TARGET,
    ANDROID_VLC_TARGET,
    ANDROID_CHOOSER_TARGET,
}


@dataclass(frozen=True, slots=True)
class PlaybackTarget:
    id: str
    label: str
    kind: str
    package: str | None = None


@dataclass(frozen=True, slots=True)
class PlaybackResult:
    success: bool
    message: str
    target_id: str


def is_termux_environment() -> bool:
    """Return True when running inside Termux on Android."""

    if os.getenv("TERMUX_VERSION"):
        return True
    if os.getenv("PREFIX", "").startswith("/data/data/com.termux"):
        return True
    return shutil.which("termux-open-url") is not None


def _is_direct_media_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith((".m3u8", ".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpd", ".ts"))


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _run_android_intent(command: list[str]) -> bool:
    result = _run_command(command)
    output = f"{result.stdout}\n{result.stderr}".lower()
    if "error:" in output or "exception" in output:
        return False
    return result.returncode == 0


def _list_installed_android_packages() -> set[str]:
    commands = []
    if shutil.which("cmd"):
        commands.append(["cmd", "package", "list", "packages"])
    if shutil.which("pm"):
        commands.append(["pm", "list", "packages"])

    for command in commands:
        result = _run_command(command)
        if result.returncode != 0:
            continue

        packages: set[str] = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                package = line.split(":", 1)[1].strip()
                if package:
                    packages.add(package)
        if packages:
            return packages

    return set()


def list_playback_targets() -> list[PlaybackTarget]:
    """Return available playback targets in current environment."""

    targets = [PlaybackTarget(id=AUTO_TARGET, label="Auto (Recommended)", kind="virtual")]

    if is_termux_environment():
        packages = _list_installed_android_packages()
        if "is.xyz.mpv" in packages:
            targets.append(
                PlaybackTarget(
                    id=ANDROID_MPV_TARGET,
                    label="MPV Android app",
                    kind="android",
                    package="is.xyz.mpv",
                )
            )
        if "com.mxtech.videoplayer.pro" in packages:
            targets.append(
                PlaybackTarget(
                    id=ANDROID_MX_PRO_TARGET,
                    label="MX Player Pro",
                    kind="android",
                    package="com.mxtech.videoplayer.pro",
                )
            )
        if "com.mxtech.videoplayer.ad" in packages:
            targets.append(
                PlaybackTarget(
                    id=ANDROID_MX_FREE_TARGET,
                    label="MX Player",
                    kind="android",
                    package="com.mxtech.videoplayer.ad",
                )
            )
        if "org.videolan.vlc" in packages:
            targets.append(
                PlaybackTarget(
                    id=ANDROID_VLC_TARGET,
                    label="VLC Android",
                    kind="android",
                    package="org.videolan.vlc",
                )
            )

        if shutil.which("termux-open-url") or shutil.which("am"):
            targets.append(
                PlaybackTarget(
                    id=ANDROID_CHOOSER_TARGET,
                    label="Android chooser",
                    kind="android",
                )
            )

    if shutil.which("mpv"):
        targets.append(PlaybackTarget(id=CLI_MPV_TARGET, label="mpv (CLI)", kind="cli"))
    if shutil.which("vlc"):
        targets.append(PlaybackTarget(id=CLI_VLC_TARGET, label="VLC (CLI)", kind="cli"))

    if not is_termux_environment():
        targets.append(PlaybackTarget(id=BROWSER_TARGET, label="System browser", kind="browser"))

    return targets


def _available_target_ids() -> set[str]:
    return {target.id for target in list_playback_targets() if target.id != AUTO_TARGET}


def _normalize_target_alias(target_id: str | None) -> str:
    raw = (target_id or "").strip().lower()
    if not raw:
        return AUTO_TARGET

    if raw in {AUTO_TARGET, ANDROID_MPV_TARGET, ANDROID_MX_PRO_TARGET, ANDROID_MX_FREE_TARGET}:
        return raw
    if raw in {ANDROID_VLC_TARGET, ANDROID_CHOOSER_TARGET, CLI_MPV_TARGET, CLI_VLC_TARGET, BROWSER_TARGET}:
        return raw

    if raw in {"android", "chooser"}:
        return ANDROID_CHOOSER_TARGET
    if raw in {"android-mpv", "mpv-android", "android_mpv"}:
        return ANDROID_MPV_TARGET
    if raw in {"mx", "mx-player", "mx_player"}:
        return "mx_auto"
    if raw in {"vlc", "android-vlc", "vlc-android"}:
        return ANDROID_VLC_TARGET if is_termux_environment() else CLI_VLC_TARGET
    if raw == "mpv":
        return ANDROID_MPV_TARGET if is_termux_environment() else CLI_MPV_TARGET
    if raw in {"mpv-cli", "desktop", "cli-mpv"}:
        return CLI_MPV_TARGET

    return raw


def default_playback_target_id() -> str:
    """Resolve default target id from env and detected devices."""

    requested = _normalize_target_alias(os.getenv("MOVIEBOX_PLAYBACK_TARGET", AUTO_TARGET))
    order = resolve_playback_attempt_order(requested)
    if not order:
        return AUTO_TARGET
    if requested == AUTO_TARGET:
        return AUTO_TARGET
    return order[0]


def is_android_target(target_id: str) -> bool:
    return target_id in _ANDROID_TARGET_IDS


def should_use_android_chooser() -> bool:
    """Backward-compatible helper used by TUI flow logic."""

    requested = _normalize_target_alias(os.getenv("MOVIEBOX_PLAYBACK_TARGET", AUTO_TARGET))
    if requested in {"mx_auto", ANDROID_CHOOSER_TARGET, ANDROID_MX_PRO_TARGET, ANDROID_MX_FREE_TARGET}:
        return True

    if not is_termux_environment():
        return False

    return requested in {
        AUTO_TARGET,
        ANDROID_MPV_TARGET,
        ANDROID_VLC_TARGET,
        ANDROID_CHOOSER_TARGET,
        "mx_auto",
        ANDROID_MX_PRO_TARGET,
        ANDROID_MX_FREE_TARGET,
    }


def resolve_playback_attempt_order(target_id: str | None) -> list[str]:
    """Resolve player fallback order from selected target."""

    available = _available_target_ids()
    if not available:
        return []

    normalized = _normalize_target_alias(target_id)

    if normalized == "mx_auto":
        if ANDROID_MX_PRO_TARGET in available:
            normalized = ANDROID_MX_PRO_TARGET
        elif ANDROID_MX_FREE_TARGET in available:
            normalized = ANDROID_MX_FREE_TARGET
        else:
            normalized = AUTO_TARGET

    if normalized == AUTO_TARGET:
        preferred_order = [
            ANDROID_MPV_TARGET,
            ANDROID_MX_PRO_TARGET,
            ANDROID_MX_FREE_TARGET,
            ANDROID_VLC_TARGET,
            ANDROID_CHOOSER_TARGET,
            CLI_MPV_TARGET,
            CLI_VLC_TARGET,
            BROWSER_TARGET,
        ]
        return [target for target in preferred_order if target in available]

    if normalized not in available:
        return resolve_playback_attempt_order(AUTO_TARGET)

    fallback_order = [normalized]
    if is_termux_environment() and normalized in _ANDROID_TARGET_IDS and normalized != ANDROID_CHOOSER_TARGET:
        if ANDROID_CHOOSER_TARGET in available:
            fallback_order.append(ANDROID_CHOOSER_TARGET)

    return fallback_order


def _open_android_chooser(url: str) -> bool:
    if shutil.which("termux-open-url"):
        return subprocess.run(["termux-open-url", url], check=False).returncode == 0

    if shutil.which("am"):
        return _run_android_intent(["am", "start", "-a", "android.intent.action.VIEW", "-d", url])

    return False


def _android_header_array(headers: dict[str, str]) -> str | None:
    pairs: list[str] = []
    for key, value in headers.items():
        key_text = str(key).strip()
        value_text = str(value).strip()
        if key_text and value_text and "," not in key_text and "," not in value_text:
            pairs.extend([key_text, value_text])
    if not pairs:
        return None
    return ",".join(pairs)


def _with_subtitle_extras(command: list[str], subtitle_urls: list[str]) -> list[str]:
    if not subtitle_urls:
        return command

    primary = subtitle_urls[0]
    return [
        *command,
        "--eu",
        "subs",
        primary,
        "--eu",
        "subs.enable",
        primary,
        "--es",
        "subtitles_location",
        primary,
    ]


def _launch_android_target(
    target_id: str,
    stream_url: str,
    headers: dict[str, str],
    subtitle_urls: list[str],
    media_title: str | None,
) -> PlaybackResult:
    if not shutil.which("am") and target_id != ANDROID_CHOOSER_TARGET:
        return PlaybackResult(False, "Android activity manager (am) not available", target_id)

    if target_id == ANDROID_CHOOSER_TARGET:
        if _open_android_chooser(stream_url):
            return PlaybackResult(True, "Opened Android app chooser", target_id)
        return PlaybackResult(False, "Failed to open Android chooser", target_id)

    if target_id == ANDROID_MPV_TARGET:
        base = [
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-t",
            "video/any",
            "-p",
            "is.xyz.mpv",
            "-d",
            stream_url,
        ]
        if media_title:
            base.extend(["--es", "title", media_title])

        command = _with_subtitle_extras(base, subtitle_urls)
        if _run_android_intent(command):
            return PlaybackResult(True, "Opened MPV Android app", target_id)

        if subtitle_urls and _run_android_intent(base):
            return PlaybackResult(
                True,
                "Opened MPV Android app without external subtitle extras",
                target_id,
            )

        return PlaybackResult(False, "Failed to open MPV Android app", target_id)

    if target_id in {ANDROID_MX_PRO_TARGET, ANDROID_MX_FREE_TARGET}:
        if target_id == ANDROID_MX_PRO_TARGET:
            component = "com.mxtech.videoplayer.pro/com.mxtech.videoplayer.ActivityScreen"
            label = "MX Player Pro"
        else:
            component = "com.mxtech.videoplayer.ad/com.mxtech.videoplayer.ad.ActivityScreen"
            label = "MX Player"

        base = [
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-t",
            "video/any",
            "-n",
            component,
            "-d",
            stream_url,
        ]
        if media_title:
            base.extend(["--es", "title", media_title])

        header_array = _android_header_array(headers)
        if header_array:
            base.extend(["--esa", "headers", header_array])

        command = _with_subtitle_extras(base, subtitle_urls)
        if _run_android_intent(command):
            return PlaybackResult(True, f"Opened {label}", target_id)

        if subtitle_urls and _run_android_intent(base):
            return PlaybackResult(True, f"Opened {label} without external subtitle extras", target_id)

        return PlaybackResult(False, f"Failed to open {label}", target_id)

    if target_id == ANDROID_VLC_TARGET:
        base = [
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-t",
            "video/*",
            "-p",
            "org.videolan.vlc",
            "-d",
            stream_url,
        ]
        if media_title:
            base.extend(["--es", "title", media_title])
        if subtitle_urls:
            base.extend(["--es", "subtitles_location", subtitle_urls[0]])

        if _run_android_intent(base):
            return PlaybackResult(True, "Opened VLC Android", target_id)

        if subtitle_urls:
            base_without_subtitle = [token for token in base]
            while "subtitles_location" in base_without_subtitle:
                index = base_without_subtitle.index("subtitles_location")
                del base_without_subtitle[index - 1 : index + 2]
            if _run_android_intent(base_without_subtitle):
                return PlaybackResult(True, "Opened VLC Android without subtitle extras", target_id)

        return PlaybackResult(False, "Failed to open VLC Android", target_id)

    return PlaybackResult(False, f"Unsupported Android target: {target_id}", target_id)


def _open_url_fallback(url: str) -> bool:
    if webbrowser.open(url, new=2):
        return True
    if shutil.which("xdg-open"):
        return subprocess.run(["xdg-open", url], check=False).returncode == 0
    return False


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


def _run_vlc(stream_url: str, headers: dict[str, str], subtitle_paths: list[Path]) -> bool:
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
    return subprocess.run(command, check=False).returncode == 0


def play_stream(
    stream_url: str,
    headers: dict[str, str],
    subtitle_paths: list[Path] | None = None,
    *,
    subtitle_urls: list[str] | None = None,
    target_id: str | None = None,
    media_title: str | None = None,
    allow_browser_fallback: bool = True,
) -> PlaybackResult:
    """Play stream URL with selected target and fallback order."""

    subtitle_paths = subtitle_paths or []
    subtitle_urls = subtitle_urls or []

    attempt_order = resolve_playback_attempt_order(target_id or default_playback_target_id())
    if not attempt_order:
        return PlaybackResult(False, "No available playback targets detected", target_id or AUTO_TARGET)

    last_failure = ""

    for resolved_target in attempt_order:
        if resolved_target in _ANDROID_TARGET_IDS:
            result = _launch_android_target(
                target_id=resolved_target,
                stream_url=stream_url,
                headers=headers,
                subtitle_urls=subtitle_urls,
                media_title=media_title,
            )
        elif resolved_target == CLI_MPV_TARGET:
            success = _run_mpv(stream_url, headers, subtitle_paths)
            result = PlaybackResult(
                success=success,
                message="Launched mpv" if success else "mpv failed",
                target_id=resolved_target,
            )
        elif resolved_target == CLI_VLC_TARGET:
            success = _run_vlc(stream_url, headers, subtitle_paths)
            result = PlaybackResult(
                success=success,
                message="Launched VLC" if success else "VLC failed",
                target_id=resolved_target,
            )
        else:
            opened = _open_url_fallback(stream_url)
            result = PlaybackResult(
                success=opened,
                message="Opened URL via browser fallback" if opened else "Browser fallback failed",
                target_id=resolved_target,
            )

        if result.success:
            return result
        last_failure = result.message

    if is_termux_environment() and not allow_browser_fallback:
        return PlaybackResult(
            False,
            last_failure or "All Android player launch attempts failed",
            attempt_order[-1],
        )

    if BROWSER_TARGET not in attempt_order and allow_browser_fallback:
        opened = _open_url_fallback(stream_url)
        if opened:
            return PlaybackResult(True, "Opened URL via browser fallback", BROWSER_TARGET)

    return PlaybackResult(False, last_failure or "Playback failed", attempt_order[-1])
