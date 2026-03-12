"""Playback adapters for Textual TUI sessions."""

from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

AUTO_TARGET = "auto"

ANDROID_MPV_TARGET = "android_mpv"
ANDROID_MPVEX_TARGET = "android_mpvex"
ANDROID_VLC_TARGET = "android_vlc"
ANDROID_MX_PRO_TARGET = "android_mx_pro"
ANDROID_MX_FREE_TARGET = "android_mx_free"

CLI_MPV_TARGET = "mpv_cli"
CLI_VLC_TARGET = "vlc_cli"
BROWSER_TARGET = "browser"
WEB_PLAYER_TARGET = "web_player"

_ANDROID_TARGET_IDS = {
    ANDROID_MPV_TARGET,
    ANDROID_MPVEX_TARGET,
    ANDROID_VLC_TARGET,
    ANDROID_MX_PRO_TARGET,
    ANDROID_MX_FREE_TARGET,
}

_ANDROID_TARGET_ORDER = [
    ANDROID_MPV_TARGET,
    ANDROID_MPVEX_TARGET,
    ANDROID_VLC_TARGET,
    ANDROID_MX_PRO_TARGET,
    ANDROID_MX_FREE_TARGET,
]

_ANDROID_TARGET_LABELS = {
    ANDROID_MPV_TARGET: "MPV Android",
    ANDROID_MPVEX_TARGET: "MPVEX Android",
    ANDROID_VLC_TARGET: "VLC Android",
    ANDROID_MX_PRO_TARGET: "MX Player Pro",
    ANDROID_MX_FREE_TARGET: "MX Player Free",
}

_ANDROID_TARGET_PACKAGES = {
    ANDROID_MPV_TARGET: ["is.xyz.mpv"],
    ANDROID_MPVEX_TARGET: ["app.marlboroadvance.mpvex"],
    ANDROID_VLC_TARGET: ["org.videolan.vlc"],
    ANDROID_MX_PRO_TARGET: ["com.mxtech.videoplayer.pro"],
    ANDROID_MX_FREE_TARGET: ["com.mxtech.videoplayer.ad"],
}

_PROXY_ROUTE_TTL_SECONDS = 20 * 60
_PROXY_LOCK = threading.Lock()
_PROXY_SERVER: ThreadingHTTPServer | None = None
_PROXY_THREAD: threading.Thread | None = None
_PROXY_HTTP_CLIENT: httpx.Client | None = None
_PROXY_ROUTES: dict[str, _ProxyRoute] = {}

_M3U8_URI_PATTERN = re.compile(r'URI="([^"]+)"')


def _safe_filename_hint(filename: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    if not cleaned:
        cleaned = fallback
    if len(cleaned) > 80:
        cleaned = cleaned[:80]
    return cleaned


def _guess_filename_hint(url: str, fallback: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name.strip()
    if name:
        return _safe_filename_hint(name, fallback)
    return _safe_filename_hint(fallback, fallback)


@dataclass(frozen=True, slots=True)
class PlaybackTarget:
    id: str
    label: str
    kind: str
    package: str | None = None
    detected: bool = True


@dataclass(frozen=True, slots=True)
class PlaybackResult:
    success: bool
    message: str
    target_id: str


@dataclass(slots=True)
class _ProxyRoute:
    url: str
    headers: dict[str, str]
    created_at: float


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


def _target_package_candidates(target_id: str) -> list[str]:
    return _ANDROID_TARGET_PACKAGES.get(target_id, [])


def _target_detected(target_id: str, packages: set[str]) -> bool:
    if not packages:
        return False
    candidates = _target_package_candidates(target_id)
    return any(candidate in packages for candidate in candidates)


def list_playback_targets() -> list[PlaybackTarget]:
    """Return available playback targets in current environment."""

    if is_termux_environment():
        installed_packages = _list_installed_android_packages()
        targets: list[PlaybackTarget] = []
        for target_id in _ANDROID_TARGET_ORDER:
            candidates = _target_package_candidates(target_id)
            detected = _target_detected(target_id, installed_packages)
            label = _ANDROID_TARGET_LABELS[target_id]
            if installed_packages and not detected:
                label = f"{label} (not detected)"

            targets.append(
                PlaybackTarget(
                    id=target_id,
                    label=label,
                    kind="android",
                    package=candidates[0] if candidates else None,
                    detected=detected,
                )
            )
        targets.append(PlaybackTarget(id=WEB_PLAYER_TARGET, label="Web Player", kind="browser"))
        return targets

    targets = [PlaybackTarget(id=AUTO_TARGET, label="Auto (Recommended)", kind="virtual")]
    if shutil.which("mpv"):
        targets.append(PlaybackTarget(id=CLI_MPV_TARGET, label="mpv (CLI)", kind="cli"))
    if shutil.which("vlc"):
        targets.append(PlaybackTarget(id=CLI_VLC_TARGET, label="VLC (CLI)", kind="cli"))
    targets.append(PlaybackTarget(id=BROWSER_TARGET, label="System browser", kind="browser"))
    targets.append(PlaybackTarget(id=WEB_PLAYER_TARGET, label="Web Player", kind="browser"))
    return targets


def _normalize_target_alias(target_id: str | None) -> str:
    raw = (target_id or "").strip().lower()
    if not raw:
        return AUTO_TARGET

    known_targets = {
        AUTO_TARGET,
        ANDROID_MPV_TARGET,
        ANDROID_MPVEX_TARGET,
        ANDROID_VLC_TARGET,
        ANDROID_MX_PRO_TARGET,
        ANDROID_MX_FREE_TARGET,
        CLI_MPV_TARGET,
        CLI_VLC_TARGET,
        BROWSER_TARGET,
        WEB_PLAYER_TARGET,
    }
    if raw in known_targets:
        return raw

    alias_map = {
        "android": ANDROID_MPV_TARGET,
        "chooser": ANDROID_MPV_TARGET,
        "android-mpv": ANDROID_MPV_TARGET,
        "mpv-android": ANDROID_MPV_TARGET,
        "mpv": ANDROID_MPV_TARGET if is_termux_environment() else CLI_MPV_TARGET,
        "mpvex": ANDROID_MPVEX_TARGET,
        "mpv-ex": ANDROID_MPVEX_TARGET,
        "vlc": ANDROID_VLC_TARGET if is_termux_environment() else CLI_VLC_TARGET,
        "android-vlc": ANDROID_VLC_TARGET,
        "vlc-android": ANDROID_VLC_TARGET,
        "mx": ANDROID_MX_PRO_TARGET,
        "mx-pro": ANDROID_MX_PRO_TARGET,
        "mx-free": ANDROID_MX_FREE_TARGET,
        "mx-player-pro": ANDROID_MX_PRO_TARGET,
        "mx-player-free": ANDROID_MX_FREE_TARGET,
        "mpv-cli": CLI_MPV_TARGET,
        "desktop": CLI_MPV_TARGET,
        "cli-mpv": CLI_MPV_TARGET,
        "web": WEB_PLAYER_TARGET,
        "web-player": WEB_PLAYER_TARGET,
        "web_player": WEB_PLAYER_TARGET,
    }
    return alias_map.get(raw, raw)


def default_playback_target_id() -> str:
    """Resolve default target id from env and detected devices."""

    requested = _normalize_target_alias(os.getenv("MOVIEBOX_PLAYBACK_TARGET", AUTO_TARGET))

    if is_termux_environment():
        if requested in _ANDROID_TARGET_IDS | {CLI_MPV_TARGET, CLI_VLC_TARGET}:
            return requested

        termux_targets = list_playback_targets()
        for target in termux_targets:
            if target.detected:
                return target.id
        return ANDROID_MPV_TARGET

    if requested in {CLI_MPV_TARGET, CLI_VLC_TARGET, BROWSER_TARGET}:
        return requested
    return AUTO_TARGET


def is_android_target(target_id: str) -> bool:
    return target_id in _ANDROID_TARGET_IDS


def should_use_android_chooser() -> bool:
    """Backward-compatible helper retained for legacy callers."""

    if not is_termux_environment():
        return False

    requested = _normalize_target_alias(os.getenv("MOVIEBOX_PLAYBACK_TARGET", AUTO_TARGET))
    return requested in {AUTO_TARGET, *list(_ANDROID_TARGET_IDS)}


def resolve_playback_attempt_order(target_id: str | None) -> list[str]:
    """Resolve player fallback order from selected target."""

    normalized = _normalize_target_alias(target_id)

    if is_termux_environment():
        if normalized in _ANDROID_TARGET_IDS | {CLI_MPV_TARGET, CLI_VLC_TARGET}:
            return [normalized]

        if normalized == AUTO_TARGET:
            detected_targets = [target.id for target in list_playback_targets() if target.detected]
            return detected_targets or list(_ANDROID_TARGET_ORDER)

        return [default_playback_target_id()]

    available = {target.id for target in list_playback_targets() if target.id != AUTO_TARGET}
    if normalized in available:
        return [normalized]

    preferred_order = [CLI_MPV_TARGET, CLI_VLC_TARGET, WEB_PLAYER_TARGET, BROWSER_TARGET]
    return [target_id for target_id in preferred_order if target_id in available]


def _ensure_proxy_http_client() -> httpx.Client:
    global _PROXY_HTTP_CLIENT
    if _PROXY_HTTP_CLIENT is None:
        _PROXY_HTTP_CLIENT = httpx.Client(
            timeout=httpx.Timeout(20.0, read=300.0),
            follow_redirects=True,
        )
    return _PROXY_HTTP_CLIENT


def _close_proxy_http_client() -> None:
    global _PROXY_HTTP_CLIENT
    if _PROXY_HTTP_CLIENT is not None:
        _PROXY_HTTP_CLIENT.close()
        _PROXY_HTTP_CLIENT = None


def _cleanup_proxy_routes(now: float | None = None) -> None:
    current = now if now is not None else time.time()
    expiry = current - _PROXY_ROUTE_TTL_SECONDS
    stale_tokens = [token for token, route in _PROXY_ROUTES.items() if route.created_at < expiry]
    for token in stale_tokens:
        _PROXY_ROUTES.pop(token, None)


def _register_proxy_route(url: str, headers: dict[str, str], *, filename_hint: str | None = None) -> str:
    server_port = _ensure_proxy_server()
    token = os.urandom(12).hex()
    cleaned_headers = {
        str(key).strip(): str(value).strip()
        for key, value in headers.items()
        if str(key).strip() and str(value).strip()
    }

    with _PROXY_LOCK:
        _cleanup_proxy_routes()
        _PROXY_ROUTES[token] = _ProxyRoute(url=url, headers=cleaned_headers, created_at=time.time())

    hint = _safe_filename_hint(filename_hint or "media.bin", "media.bin")
    return f"http://127.0.0.1:{server_port}/route/{token}/{hint}"


def _resolve_proxy_route(token: str) -> _ProxyRoute | None:
    with _PROXY_LOCK:
        route = _PROXY_ROUTES.get(token)
        if route is None:
            return None
        return route


def _is_m3u8_response(url: str, content_type: str | None) -> bool:
    if ".m3u8" in url.lower():
        return True
    lowered = (content_type or "").lower()
    return "mpegurl" in lowered or "vnd.apple.mpegurl" in lowered


def _rewrite_m3u8_playlist(text: str, *, base_url: str, headers: dict[str, str]) -> str:
    rewritten_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            rewritten_lines.append(line)
            continue

        if stripped.startswith("#"):
            if 'URI="' in line:

                def _replace_uri(match: re.Match[str]) -> str:
                    nested_url = urljoin(base_url, match.group(1))
                    proxied = _register_proxy_route(
                        nested_url,
                        headers,
                        filename_hint=_guess_filename_hint(nested_url, "segment.ts"),
                    )
                    return f'URI="{proxied}"'

                rewritten_lines.append(_M3U8_URI_PATTERN.sub(_replace_uri, line))
                continue

            rewritten_lines.append(line)
            continue

        nested_url = urljoin(base_url, stripped)
        proxied_url = _register_proxy_route(
            nested_url,
            headers,
            filename_hint=_guess_filename_hint(nested_url, "segment.ts"),
        )
        rewritten_lines.append(proxied_url)

    return "\n".join(rewritten_lines)


class _PlaybackProxyRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        return

    def do_HEAD(self) -> None:
        self._handle_proxy_request(send_body=False)

    def do_GET(self) -> None:
        self._handle_proxy_request(send_body=True)

    def _handle_proxy_request(self, *, send_body: bool) -> None:
        path = self.path.split("?", 1)[0]
        parts = path.split("/")
        
        if len(parts) >= 2 and parts[1] == "player":
            from urllib.parse import parse_qs
            query_string = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = parse_qs(query_string)
            video_url = params.get("video", [""])[0]
            subs_urls = params.get("sub", [])
            
            html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MOVIEBOX</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary: #6366f1;
            --bg: #030712;
            --text: #f9fafb;
        }}
        body, html {{ 
            margin: 0; padding: 0; width: 100%; height: 100%;
            background-color: var(--bg); color: var(--text);
            font-family: 'Inter', system-ui, sans-serif;
            overflow: hidden;
        }}
        .player-wrapper {{
            position: relative;
            width: 100%; height: 100%;
            display: flex; justify-content: center; align-items: center;
        }}
        video {{
            width: 100%; height: 100%;
            outline: none; background: #000;
        }}
        video::-webkit-media-controls-buffering-overlay {{
            display: none !important;
        }}
        .header {{
            position: absolute; top: 0; left: 0; right: 0;
            padding: 2rem;
            background: linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0) 100%);
            display: flex; justify-content: space-between; align-items: center;
            z-index: 10;
            transition: opacity 0.4s ease;
            opacity: 1;
        }}
        .header.idle {{ opacity: 0; pointer-events: none; }}
        .title-container {{ display: flex; align-items: center; gap: 14px; }}
        .logo {{ 
            font-weight: 800; font-size: 20px; letter-spacing: 1px;
            background: linear-gradient(to right, #818cf8, #c084fc);
            -webkit-background-clip: text; color: transparent;
        }}
        .divider {{ width: 5px; height: 5px; border-radius: 50%; background: #4b5563; }}
        .now-playing {{ font-weight: 500; font-size: 15px; color: #d1d5db; letter-spacing: 0.5px; }}
        
        .loading {{
            position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
            width: 48px; height: 48px;
            border: 3px solid rgba(255,255,255,0.1);
            border-radius: 50%;
            border-top-color: var(--primary);
            animation: spin 1s ease-in-out infinite;
            z-index: 5;
            display: none;
            pointer-events: none;
        }}
        @keyframes spin {{ to {{ transform: translate(-50%, -50%) rotate(360deg); }} }}
        video.waiting ~ .loading {{ display: block; }}
    </style>
</head>
<body>
    <div class="player-wrapper" id="wrapper">
        <div class="header" id="header">
            <div class="title-container">
                <div class="logo">MOVIEBOX</div>
                <div class="divider"></div>
                <div class="now-playing">Playing External Stream</div>
            </div>
        </div>
        <video id="video-player" controls autoplay playsinline crossorigin="anonymous">
"""
            for i, sub in enumerate(subs_urls):
                default = "default" if i == 0 else ""
                html += f'            <track label="Subtitle {i+1}" kind="subtitles" srclang="en" src="{sub}" {default}>\n'
            
            html += f"""        </video>
        <div class="loading"></div>
    </div>
    <script>
        const video = document.getElementById('video-player');
        const header = document.getElementById('header');
        const wrapper = document.getElementById('wrapper');
        const videoSrc = "{video_url}";
        
        if (Hls.isSupported() && videoSrc.includes('.m3u8')) {{
            const hls = new Hls({{ maxBufferLength: 30, maxMaxBufferLength: 600 }});
            hls.loadSource(videoSrc); 
            hls.attachMedia(video);
            hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {{}}));
            hls.on(Hls.Events.ERROR, (evt, data) => {{
                if(data.fatal) {{
                    switch(data.type) {{
                        case Hls.ErrorTypes.NETWORK_ERROR: hls.startLoad(); break;
                        case Hls.ErrorTypes.MEDIA_ERROR: hls.recoverMediaError(); break;
                        default: hls.destroy(); break;
                    }}
                }}
            }});
        }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
            video.src = videoSrc; 
            video.addEventListener('loadedmetadata', () => video.play().catch(() => {{}}));
        }} else {{ 
            video.src = videoSrc; 
        }}

        let idleTimeout;
        const resetIdle = () => {{
            header.classList.remove('idle');
            clearTimeout(idleTimeout);
            idleTimeout = setTimeout(() => {{
                if(!video.paused) header.classList.add('idle');
            }}, 2800);
        }};
        
        document.addEventListener('mousemove', resetIdle);
        document.addEventListener('keydown', resetIdle);
        video.addEventListener('play', resetIdle);
        video.addEventListener('pause', () => header.classList.remove('idle'));

        document.addEventListener('keydown', (e) => {{
            const focused = document.activeElement;
            if (focused && focused.tagName === 'VIDEO') return;
            
            if (e.code === 'Space' || e.code === 'KeyK') {{ e.preventDefault(); video.paused ? video.play() : video.pause(); }}
            if (e.code === 'KeyF') {{ 
                if (!document.fullscreenElement) wrapper.requestFullscreen().catch(() => {{}});
                else document.exitFullscreen();
            }}
            if (e.code === 'KeyM') {{ video.muted = !video.muted; }}
            if (e.code === 'ArrowRight') {{ video.currentTime += 10; }}
            if (e.code === 'ArrowLeft') {{ video.currentTime -= 10; }}
        }});

        video.addEventListener('dblclick', (e) => {{
            e.preventDefault();
            if (!document.fullscreenElement) wrapper.requestFullscreen().catch(() => {{}});
            else document.exitFullscreen();
        }});

        video.addEventListener('waiting', () => video.classList.add('waiting'));
        video.addEventListener('playing', () => video.classList.remove('waiting'));
        video.addEventListener('canplay', () => video.classList.remove('waiting'));
        
        resetIdle();
    </script>
</body>
</html>"""
            payload = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if send_body:
                self.wfile.write(payload)
            return

        if len(parts) < 3 or parts[1] != "route":
            self.send_response(404)
            self.end_headers()
            return

        token = parts[2].strip()
        if not token:
            self.send_response(404)
            self.end_headers()
            return

        route = _resolve_proxy_route(token)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return

        request_headers = dict(route.headers)
        range_header = self.headers.get("Range")
        if range_header:
            request_headers["Range"] = range_header

        client = _ensure_proxy_http_client()
        try:
            method = "GET" if send_body else "HEAD"
            with client.stream(method, route.url, headers=request_headers) as response:
                is_playlist = _is_m3u8_response(route.url, response.headers.get("Content-Type"))
                if send_body and is_playlist:
                    playlist_text = response.text
                    rewritten = _rewrite_m3u8_playlist(
                        playlist_text,
                        base_url=str(response.url),
                        headers=route.headers,
                    )
                    payload = rewritten.encode("utf-8")

                    self.send_response(response.status_code)
                    self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                self.send_response(response.status_code)
                passthrough = [
                    "Content-Type",
                    "Content-Length",
                    "Content-Range",
                    "Accept-Ranges",
                    "Last-Modified",
                    "ETag",
                ]
                for header_name in passthrough:
                    header_value = response.headers.get(header_name)
                    if header_value:
                        self.send_header(header_name, header_value)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                if not send_body:
                    return

                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    self.wfile.write(chunk)
        except Exception:
            self.send_response(502)
            self.end_headers()


def _shutdown_proxy_server() -> None:
    global _PROXY_SERVER, _PROXY_THREAD
    server = _PROXY_SERVER
    if server is not None:
        server.shutdown()
        server.server_close()
    _PROXY_SERVER = None
    _PROXY_THREAD = None


def _ensure_proxy_server() -> int:
    global _PROXY_SERVER, _PROXY_THREAD
    with _PROXY_LOCK:
        if _PROXY_SERVER is not None:
            return _PROXY_SERVER.server_port

        server = ThreadingHTTPServer(("127.0.0.1", 0), _PlaybackProxyRequestHandler)
        server.daemon_threads = True

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        _PROXY_SERVER = server
        _PROXY_THREAD = thread
        return server.server_port


atexit.register(_shutdown_proxy_server)
atexit.register(_close_proxy_http_client)


def _prepare_android_proxy_urls(
    stream_url: str,
    headers: dict[str, str],
    subtitle_urls: list[str],
) -> tuple[str, list[str]]:
    try:
        stream_hint = _guess_filename_hint(stream_url, "stream.m3u8")
        proxied_stream = _register_proxy_route(stream_url, headers, filename_hint=stream_hint)

        proxied_subtitles = [
            _register_proxy_route(
                url,
                headers,
                filename_hint=_guess_filename_hint(url, "subtitle.srt"),
            )
            for url in subtitle_urls
            if url
        ]
        return proxied_stream, proxied_subtitles
    except Exception:
        return stream_url, [url for url in subtitle_urls if url]


def probe_stream_access(stream_url: str, headers: dict[str, str]) -> tuple[bool, str]:
    """Probe a stream URL quickly to determine whether it is reachable."""

    probe_headers = {
        str(key).strip(): str(value).strip()
        for key, value in headers.items()
        if str(key).strip() and str(value).strip()
    }
    probe_headers["Range"] = "bytes=0-1"

    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, read=10.0), follow_redirects=True) as client:
            response = client.get(stream_url, headers=probe_headers)
        if response.status_code in {200, 206}:
            return True, "ok"
        return False, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, str(exc)


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


def _android_header_fields_string(headers: dict[str, str]) -> str | None:
    parts: list[str] = []
    for key, value in headers.items():
        key_text = str(key).strip()
        value_text = str(value).strip()
        if key_text and value_text:
            parts.append(f"{key_text}: {value_text}")
    if not parts:
        return None
    return ",".join(parts)


def _with_title_extra(command: list[str], media_title: str | None) -> list[str]:
    if not media_title:
        return command
    return [*command, "--es", "title", media_title]


def _with_subtitle_extras(command: list[str], subtitle_urls: list[str], target_id: str) -> list[str]:
    if not subtitle_urls:
        return command

    primary = subtitle_urls[0]
    subtitle_name = Path(urlparse(primary).path).name or "subtitle.srt"

    extras: list[str] = []
    if target_id in {ANDROID_MPV_TARGET, ANDROID_MPVEX_TARGET}:
        extras.extend(["--eu", "subs", primary, "--eu", "subs.enable", primary])
        extras.extend(["--es", "subtitles_location", primary])
    elif target_id in {ANDROID_MX_PRO_TARGET, ANDROID_MX_FREE_TARGET}:
        extras.extend(["--eu", "subs", primary, "--eu", "subs.enable", primary])
        extras.extend(["--es", "subs.name", subtitle_name, "--es", "subs.filename", subtitle_name])
        extras.extend(["--es", "subtitles_location", primary])
    elif target_id == ANDROID_VLC_TARGET:
        extras.extend(["--es", "subtitles_location", primary, "--eu", "subs", primary])

    return [*command, *extras]


def _build_android_intent_commands(
    target_id: str,
    stream_url: str,
    headers: dict[str, str],
    subtitle_urls: list[str],
    media_title: str | None,
) -> list[list[str]]:
    base = ["am", "start", "-a", "android.intent.action.VIEW"]

    commands: list[list[str]] = []
    if target_id in {ANDROID_MPV_TARGET, ANDROID_MPVEX_TARGET}:
        package = _target_package_candidates(target_id)[0]
        variants = [
            [*base, "-t", "video/any", "-n", f"{package}/.MPVActivity", "-d", stream_url],
            [*base, "-t", "video/any", "-n", f"{package}/.MainActivity", "-d", stream_url],
            [*base, "-t", "video/any", "-p", package, "-d", stream_url],
            [*base, "-t", "video/*", "-p", package, "-d", stream_url],
        ]
        commands = [_with_title_extra(variant, media_title) for variant in variants]

        header_fields = _android_header_fields_string(headers)
        if header_fields:
            commands = [[*command, "--es", "http-header-fields", header_fields] for command in commands]

    elif target_id == ANDROID_VLC_TARGET:
        package = _target_package_candidates(target_id)[0]
        variants = [
            [*base, "-t", "video/*", "-p", package, "-d", stream_url],
            [
                *base,
                "-n",
                "org.videolan.vlc/org.videolan.vlc.gui.video.VideoPlayerActivity",
                "-d",
                stream_url,
            ],
        ]
        commands = [_with_title_extra(variant, media_title) for variant in variants]

    elif target_id == ANDROID_MX_PRO_TARGET:
        package = _target_package_candidates(target_id)[0]
        variants = [
            [
                *base,
                "-t",
                "video/any",
                "-n",
                "com.mxtech.videoplayer.pro/com.mxtech.videoplayer.ActivityScreen",
                "-d",
                stream_url,
            ],
            [*base, "-t", "video/*", "-p", package, "-d", stream_url],
        ]
        commands = [_with_title_extra(variant, media_title) for variant in variants]

    elif target_id == ANDROID_MX_FREE_TARGET:
        package = _target_package_candidates(target_id)[0]
        variants = [
            [
                *base,
                "-t",
                "video/any",
                "-n",
                "com.mxtech.videoplayer.ad/com.mxtech.videoplayer.ad.ActivityScreen",
                "-d",
                stream_url,
            ],
            [*base, "-t", "video/*", "-p", package, "-d", stream_url],
        ]
        commands = [_with_title_extra(variant, media_title) for variant in variants]

    if target_id in {ANDROID_MX_PRO_TARGET, ANDROID_MX_FREE_TARGET}:
        header_array = _android_header_array(headers)
        if header_array:
            commands = [[*command, "--esa", "headers", header_array] for command in commands]

    if subtitle_urls:
        with_subtitles = [_with_subtitle_extras(command, subtitle_urls, target_id) for command in commands]
        return [*with_subtitles, *commands]

    return commands


def _launch_android_target(
    target_id: str,
    stream_url: str,
    headers: dict[str, str],
    subtitle_urls: list[str],
    media_title: str | None,
) -> PlaybackResult:
    if not shutil.which("am"):
        return PlaybackResult(False, "Android activity manager (am) not available", target_id)

    if target_id not in _ANDROID_TARGET_IDS:
        return PlaybackResult(False, f"Unsupported Android target: {target_id}", target_id)

    installed_packages = _list_installed_android_packages()
    detected = _target_detected(target_id, installed_packages)

    commands = _build_android_intent_commands(
        target_id=target_id,
        stream_url=stream_url,
        headers=headers,
        subtitle_urls=subtitle_urls,
        media_title=media_title,
    )

    for command in commands:
        if _run_android_intent(command):
            return PlaybackResult(True, f"Opened {_ANDROID_TARGET_LABELS[target_id]}", target_id)

    if installed_packages and not detected:
        return PlaybackResult(
            False,
            f"Failed to open {_ANDROID_TARGET_LABELS[target_id]} (package not detected)",
            target_id,
        )

    return PlaybackResult(False, f"Failed to open {_ANDROID_TARGET_LABELS[target_id]}", target_id)


def _open_url_fallback(url: str) -> bool:
    with open("proxy_debug.log", "a") as f:
        f.write(f"OPENING URL: {url}\n")
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
            proxied_stream, proxied_subtitles = _prepare_android_proxy_urls(
                stream_url, headers, subtitle_urls
            )
            android_attempts: list[tuple[str, list[str], bool]] = [(proxied_stream, proxied_subtitles, True)]

            if proxied_stream != stream_url or proxied_subtitles != subtitle_urls:
                android_attempts.append((stream_url, subtitle_urls, False))

            for media_url, subtitles, proxied in android_attempts:
                result = _launch_android_target(
                    target_id=resolved_target,
                    stream_url=media_url,
                    headers=headers,
                    subtitle_urls=subtitles,
                    media_title=media_title,
                )
                if result.success:
                    suffix = " via local proxy" if proxied else ""
                    return PlaybackResult(True, f"{result.message}{suffix}", resolved_target)
                last_failure = result.message

            continue

        if resolved_target == CLI_MPV_TARGET:
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
        elif resolved_target == WEB_PLAYER_TARGET:
            from urllib.parse import urlencode
            proxied_stream, proxied_subtitles = _prepare_android_proxy_urls(
                stream_url, headers, subtitle_urls
            )
            query = {"video": proxied_stream}
            if proxied_subtitles:
                query["sub"] = proxied_subtitles
            port = _ensure_proxy_server()
            player_url = f"http://127.0.0.1:{port}/player?{urlencode(query, doseq=True)}"
            opened = _open_url_fallback(player_url)
            result = PlaybackResult(
                success=opened,
                message="Opened Web Player" if opened else "Failed to open Web Player",
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
            False, last_failure or "All Android player launch attempts failed", attempt_order[-1]
        )

    if allow_browser_fallback and BROWSER_TARGET not in attempt_order:
        opened = _open_url_fallback(stream_url)
        if opened:
            return PlaybackResult(True, "Opened URL via browser fallback", BROWSER_TARGET)

    return PlaybackResult(False, last_failure or "Playback failed", attempt_order[-1])
