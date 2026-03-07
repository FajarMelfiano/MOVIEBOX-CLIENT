import pytest

from moviebox_api.stremio import subtitle_sources
from moviebox_api.stremio.subtitle_sources import (
    ExternalSubtitle,
    _normalise_language_code,
    _preferred_language_codes,
    fetch_external_subtitles,
    subtitle_source_is_configured,
)


def test_normalise_language_code_prefers_iso639_1_codes():
    assert _normalise_language_code("ind") == "id"
    assert _normalise_language_code("id") == "id"
    assert _normalise_language_code("english") == "en"


def test_preferred_language_codes_default_to_en_and_id():
    assert _preferred_language_codes(None) == ["en", "id"]


def test_preferred_language_codes_respects_language_aliases():
    assert _preferred_language_codes(["Indonesian", "English"]) == ["id", "en"]


def test_preferred_language_codes_appends_fallback_languages():
    assert _preferred_language_codes(["indonesian"]) == ["id", "en"]


@pytest.mark.asyncio
async def test_fetch_external_subtitles_raises_when_only_source_errors(monkeypatch: pytest.MonkeyPatch):
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("invalid key")

    monkeypatch.setattr(subtitle_sources, "_fetch_subsource", _boom)

    with pytest.raises(RuntimeError, match="subsource: invalid key"):
        await fetch_external_subtitles(
            video_id="tt0816692",
            content_type="movie",
            sources=["subsource"],
            preferred_languages=["english"],
        )


@pytest.mark.asyncio
async def test_fetch_external_subtitles_ignores_one_source_error_if_others_succeed(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("invalid key")

    async def _ok(*_args, **_kwargs):
        return [
            ExternalSubtitle(
                url="https://example.com/sub.srt",
                language="en",
                label="English",
                source="opensubtitles",
            )
        ]

    monkeypatch.setattr(subtitle_sources, "_fetch_subsource", _boom)
    monkeypatch.setattr(subtitle_sources, "_fetch_opensubtitles", _ok)

    result = await fetch_external_subtitles(
        video_id="tt0816692",
        content_type="movie",
        sources=["subsource", "opensubtitles"],
        preferred_languages=["english"],
    )
    assert len(result) == 1
    assert result[0].source == "opensubtitles"


def test_subtitle_source_is_configured_uses_proxy_without_local_keys(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MOVIEBOX_SUBTITLE_PROXY_URL", "https://example.com/subtitle-proxy")
    monkeypatch.setattr(subtitle_sources, "get_secret", lambda *_args, **_kwargs: "")

    assert subtitle_source_is_configured("subdl") is True
    assert subtitle_source_is_configured("subsource") is True


@pytest.mark.asyncio
async def test_fetch_external_subtitles_prefers_proxy_for_subdl_and_subsource(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MOVIEBOX_SUBTITLE_PROXY_URL", "https://example.com/subtitle-proxy")

    async def _proxy_fetch(*_args, **_kwargs):
        return (
            [
                ExternalSubtitle(
                    url="https://proxy.example/subdl.srt",
                    language="en",
                    label="Proxy SubDL",
                    source="subdl",
                ),
                ExternalSubtitle(
                    url="https://proxy.example/subsource.srt",
                    language="en",
                    label="Proxy SubSource",
                    source="subsource",
                ),
            ],
            [],
        )

    async def _should_not_call_local(*_args, **_kwargs):
        raise AssertionError("Local subtitle source should not be called when proxy is configured")

    monkeypatch.setattr(subtitle_sources, "_fetch_subtitle_proxy", _proxy_fetch)
    monkeypatch.setattr(subtitle_sources, "_fetch_subdl", _should_not_call_local)
    monkeypatch.setattr(subtitle_sources, "_fetch_subsource", _should_not_call_local)

    result = await fetch_external_subtitles(
        video_id="tt0816692",
        content_type="movie",
        sources=["subdl", "subsource"],
        preferred_languages=["english"],
    )
    assert len(result) == 2
    assert {item.source for item in result} == {"subdl", "subsource"}
