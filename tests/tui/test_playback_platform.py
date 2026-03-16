import httpx
import pytest

from moviebox_api.tui import playback


def test_is_termux_environment_detected_by_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.119")
    monkeypatch.setattr(playback.shutil, "which", lambda _name: None)

    assert playback.is_termux_environment() is True


def test_is_termux_environment_detected_by_prefix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setattr(playback.shutil, "which", lambda _name: None)

    assert playback.is_termux_environment() is True


def test_list_playback_targets_termux_contains_fixed_android_player_choices(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TERMUX_VERSION", "0.119")
    monkeypatch.setattr(
        playback,
        "_list_installed_android_packages",
        lambda: {
            "is.xyz.mpv",
            "app.marlboroadvance.mpvex",
            "com.mxtech.videoplayer.pro",
            "com.mxtech.videoplayer.ad",
            "org.videolan.vlc",
        },
    )

    targets = playback.list_playback_targets()
    target_ids = [target.id for target in targets]

    assert target_ids == [
        playback.ANDROID_MPV_TARGET,
        playback.ANDROID_MPVEX_TARGET,
        playback.ANDROID_VLC_TARGET,
        playback.ANDROID_MX_PRO_TARGET,
        playback.ANDROID_MX_FREE_TARGET,
        playback.WEB_PLAYER_TARGET,
    ]


def test_default_target_prefers_first_detected_android_player(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.119")
    monkeypatch.delenv("MOVIEBOX_PLAYBACK_TARGET", raising=False)
    monkeypatch.setattr(
        playback,
        "_list_installed_android_packages",
        lambda: {"app.marlboroadvance.mpvex", "org.videolan.vlc"},
    )

    assert playback.default_playback_target_id() == playback.ANDROID_MPVEX_TARGET


def test_resolve_attempt_order_uses_explicit_termux_player(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.119")
    monkeypatch.setattr(playback, "_list_installed_android_packages", lambda: set())

    order = playback.resolve_playback_attempt_order(playback.ANDROID_MX_PRO_TARGET)
    assert order == [playback.ANDROID_MX_PRO_TARGET]


def test_play_stream_termux_blocks_browser_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.119")
    monkeypatch.setattr(
        playback,
        "resolve_playback_attempt_order",
        lambda _target: [playback.ANDROID_MPV_TARGET],
    )
    monkeypatch.setattr(
        playback,
        "_launch_android_target",
        lambda *args, **kwargs: playback.PlaybackResult(
            success=False,
            message="mpv launch failed",
            target_id=playback.ANDROID_MPV_TARGET,
        ),
    )

    opened_browser = {"called": False}

    def _fake_open_url(_url: str) -> bool:
        opened_browser["called"] = True
        return True

    monkeypatch.setattr(playback, "_open_url_fallback", _fake_open_url)

    result = playback.play_stream(
        "https://example.com/master.m3u8",
        {},
        [],
        target_id=playback.ANDROID_MPV_TARGET,
        allow_browser_fallback=False,
    )

    assert result.success is False
    assert opened_browser["called"] is False


def test_play_stream_android_prefers_local_proxy_launch(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.119")
    monkeypatch.setattr(
        playback,
        "resolve_playback_attempt_order",
        lambda _target: [playback.ANDROID_MPV_TARGET],
    )
    monkeypatch.setattr(
        playback,
        "_prepare_android_proxy_urls",
        lambda *_args, **_kwargs: ("http://127.0.0.1:9999/route/abc", ["http://127.0.0.1:9999/route/sub"]),
    )

    launched = {"url": ""}

    def _fake_launch(target_id, stream_url, headers, subtitle_urls, media_title):
        launched["url"] = stream_url
        return playback.PlaybackResult(True, "Opened MPV Android", target_id)

    monkeypatch.setattr(playback, "_launch_android_target", _fake_launch)

    result = playback.play_stream(
        "https://example.com/video.m3u8",
        {"Referer": "https://example.com"},
        [],
        subtitle_urls=["https://example.com/sub.srt"],
        target_id=playback.ANDROID_MPV_TARGET,
        allow_browser_fallback=False,
    )

    assert result.success is True
    assert "local proxy" in result.message
    assert launched["url"].startswith("http://127.0.0.1")


def test_build_web_player_html_uses_media_title_and_divider_state_hook():
    html = playback._build_web_player_html(
        media_title='Jujutsu Kaisen Season 3',
        subtitle_urls=['https://example.com/sub.vtt'],
    )

    assert '<title>Jujutsu Kaisen Season 3</title>' in html
    assert 'id="divider"' in html
    assert 'id="now-playing">Jujutsu Kaisen Season 3<' in html
    assert 'src="https://example.com/sub.vtt"' in html


def test_play_stream_web_player_includes_media_title_in_query(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv('TERMUX_VERSION', raising=False)
    monkeypatch.setattr(
        playback,
        'resolve_playback_attempt_order',
        lambda _target: [playback.WEB_PLAYER_TARGET],
    )
    monkeypatch.setattr(
        playback,
        '_prepare_android_proxy_urls',
        lambda *_args, **_kwargs: ('http://127.0.0.1:9999/route/abc.m3u8', []),
    )
    monkeypatch.setattr(playback, '_ensure_proxy_server', lambda: 9999)
    monkeypatch.setattr(playback, '_probe_web_player_hls_proxy', lambda _url: (True, 'ok'))

    opened = {'url': ''}

    def _fake_open_url(url: str) -> bool:
        opened['url'] = url
        return True

    monkeypatch.setattr(playback, '_open_url_fallback', _fake_open_url)

    result = playback.play_stream(
        'https://example.com/master.m3u8',
        {'Referer': 'https://example.com'},
        [],
        target_id=playback.WEB_PLAYER_TARGET,
        media_title='Jujutsu Kaisen Season 3',
    )

    assert result.success is True
    assert 'title=Jujutsu+Kaisen+Season+3' in opened['url']


def test_normalized_passthrough_content_type_uses_media_extension():
    assert playback._normalized_passthrough_content_type(
        'https://cdn.example/video.mp4?token=123',
        'application/octet-stream',
    ) == 'video/mp4'


def test_normalized_passthrough_content_type_keeps_specific_header():
    assert playback._normalized_passthrough_content_type(
        'https://cdn.example/video.mp4?token=123',
        'video/mp4',
    ) == 'video/mp4'


def test_local_proxy_rewrites_hls_playlist(monkeypatch: pytest.MonkeyPatch):
    playback._shutdown_proxy_server()
    playback._close_proxy_http_client()

    playlist = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-KEY:METHOD=AES-128,URI="keys/key.bin"
#EXTINF:4.0,
segment0.ts
"""

    def _mock_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == 'https://origin.example/master.m3u8'
        return httpx.Response(
            200,
            text=playlist,
            headers={'Content-Type': 'application/vnd.apple.mpegurl'},
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(_mock_handler), follow_redirects=True)
    monkeypatch.setattr(playback, '_PROXY_HTTP_CLIENT', mock_client)

    route_url = playback._register_proxy_route(
        'https://origin.example/master.m3u8',
        {'Referer': 'https://origin.example'},
        filename_hint='master.m3u8',
    )

    with httpx.Client(timeout=5.0) as client:
        response = client.get(route_url)

    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'application/vnd.apple.mpegurl'
    assert 'http://127.0.0.1:' in response.text
    assert '\nsegment0.ts' not in response.text
    assert 'URI="keys/key.bin"' not in response.text

    playback._shutdown_proxy_server()
    playback._close_proxy_http_client()


def test_local_proxy_serves_empty_favicon():
    playback._shutdown_proxy_server()
    port = playback._ensure_proxy_server()

    with httpx.Client(timeout=5.0) as client:
        response = client.get(f'http://127.0.0.1:{port}/favicon.ico')

    assert response.status_code == 204
    assert response.content == b''

    playback._shutdown_proxy_server()


def test_probe_web_player_hls_proxy_detects_child_playlist_failure(monkeypatch: pytest.MonkeyPatch):
    responses = {
        'http://127.0.0.1:9999/route/master/master.m3u8': httpx.Response(
            200,
            text='#EXTM3U\nhttp://127.0.0.1:9999/route/child/720p.m3u8\n',
            headers={'Content-Type': 'application/vnd.apple.mpegurl'},
        ),
        'http://127.0.0.1:9999/route/child/720p.m3u8': httpx.Response(
            502,
            text='Proxy request failed: Server disconnected without sending a response.',
            headers={'Content-Type': 'text/plain; charset=utf-8'},
        ),
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        return responses[str(request.url)]

    mock_client = httpx.Client(transport=httpx.MockTransport(_handler), follow_redirects=True)
    monkeypatch.setattr(playback.httpx, 'Client', lambda *args, **kwargs: mock_client)

    ok, detail = playback._probe_web_player_hls_proxy('http://127.0.0.1:9999/route/master/master.m3u8')

    assert ok is False
    assert 'HTTP 502' in detail


def test_play_stream_web_player_rejects_unproxyable_hls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv('TERMUX_VERSION', raising=False)
    monkeypatch.setattr(
        playback,
        'resolve_playback_attempt_order',
        lambda _target: [playback.WEB_PLAYER_TARGET],
    )
    monkeypatch.setattr(
        playback,
        '_prepare_android_proxy_urls',
        lambda *_args, **_kwargs: ('http://127.0.0.1:9999/route/master/master.m3u8', []),
    )
    monkeypatch.setattr(
        playback,
        '_probe_web_player_hls_proxy',
        lambda _url: (False, 'child playlist returned HTTP 502'),
    )

    opened = {'called': False}

    def _fake_open_url(_url: str) -> bool:
        opened['called'] = True
        return True

    monkeypatch.setattr(playback, '_open_url_fallback', _fake_open_url)

    result = playback.play_stream(
        'https://example.com/master.m3u8',
        {'Referer': 'https://example.com'},
        [],
        target_id=playback.WEB_PLAYER_TARGET,
        media_title='Stranger Things',
        allow_browser_fallback=False,
    )

    assert result.success is False
    assert 'Web Player cannot proxy this HLS stream' in result.message
    assert opened['called'] is False
