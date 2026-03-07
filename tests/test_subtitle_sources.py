import pytest

from moviebox_api.stremio import subtitle_sources
from moviebox_api.stremio.subtitle_sources import (
    ExternalSubtitle,
    _normalise_language_code,
    _preferred_language_codes,
    fetch_external_subtitles,
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
