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
