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


def test_should_use_android_chooser_honors_explicit_targets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOVIEBOX_PLAYBACK_TARGET", "android")
    monkeypatch.setattr(playback.shutil, "which", lambda _name: None)
    assert playback.should_use_android_chooser() is True

    monkeypatch.setenv("MOVIEBOX_PLAYBACK_TARGET", "mpv")
    assert playback.should_use_android_chooser() is False


def test_should_use_android_chooser_termux_mpv_prefers_android_app(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TERMUX_VERSION", "0.119")
    monkeypatch.setenv("MOVIEBOX_PLAYBACK_TARGET", "mpv")
    monkeypatch.setattr(playback.shutil, "which", lambda _name: None)

    assert playback.should_use_android_chooser() is True


def test_should_use_android_chooser_auto_uses_termux(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOVIEBOX_PLAYBACK_TARGET", "auto")
    monkeypatch.setenv("TERMUX_VERSION", "0.119")
    monkeypatch.setattr(playback.shutil, "which", lambda _name: None)

    assert playback.should_use_android_chooser() is True


def test_list_playback_targets_detects_android_players(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.119")
    monkeypatch.setattr(
        playback,
        "_list_installed_android_packages",
        lambda: {
            "is.xyz.mpv",
            "com.mxtech.videoplayer.ad",
            "org.videolan.vlc",
        },
    )

    def _which(name: str) -> str | None:
        return "/usr/bin/tool" if name in {"am", "termux-open-url"} else None

    monkeypatch.setattr(playback.shutil, "which", _which)

    target_ids = {target.id for target in playback.list_playback_targets()}
    assert playback.AUTO_TARGET in target_ids
    assert playback.ANDROID_MPV_TARGET in target_ids
    assert playback.ANDROID_MX_FREE_TARGET in target_ids
    assert playback.ANDROID_VLC_TARGET in target_ids
    assert playback.ANDROID_CHOOSER_TARGET in target_ids


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
