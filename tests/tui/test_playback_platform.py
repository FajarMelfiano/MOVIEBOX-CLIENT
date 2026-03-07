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
