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
