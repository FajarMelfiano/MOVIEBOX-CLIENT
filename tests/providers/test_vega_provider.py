import pytest

from moviebox_api.constants import SubjectType
from moviebox_api.providers.models import ProviderSearchResult
from moviebox_api.providers.vega_provider import VegaProvider


@pytest.mark.asyncio
async def test_resolve_streams_preserves_audio_track_variants(monkeypatch: pytest.MonkeyPatch):
    provider = VegaProvider()

    async def _fake_manifest(provider_value: str) -> str:
        return provider_value

    async def _fake_modules(_provider_value: str) -> dict[str, str]:
        return {"meta": "", "stream": "", "episodes": ""}

    async def _fake_runtime(_payload: dict) -> dict:
        return {
            "streams": [
                {
                    "url": "https://stream.example/video/master.m3u8",
                    "source": "vega-autoEmbed",
                    "quality": "1080p",
                    "audio": "English",
                    "audioTracks": ["English", "Indonesian"],
                    "headers": {},
                    "subtitles": [],
                },
                {
                    "url": "https://stream.example/video/master.m3u8",
                    "source": "vega-autoEmbed",
                    "quality": "1080p",
                    "audio": "Indonesian",
                    "audioTracks": ["English", "Indonesian"],
                    "headers": {},
                    "subtitles": [],
                },
            ]
        }

    monkeypatch.setattr(provider, "_resolve_manifest_provider_value", _fake_manifest)
    monkeypatch.setattr(provider, "_get_provider_modules", _fake_modules)
    monkeypatch.setattr(provider, "_run_runtime", _fake_runtime)

    item = ProviderSearchResult(
        id="id-1",
        title="Interstellar",
        page_url="https://example.com/interstellar",
        subject_type=SubjectType.MOVIES,
        payload={"vega_provider": "autoEmbed", "source_link": "https://example.com/interstellar"},
    )

    streams = await provider.resolve_streams(item)

    assert len(streams) == 2
    assert streams[0].source.endswith("[English]")
    assert streams[1].source.endswith("[Indonesian]")


def test_normalize_audio_tracks_accepts_strings_and_objects():
    tracks = VegaProvider._normalize_audio_tracks(
        [
            "English",
            {"label": "Indonesian"},
            {"language": "Japanese"},
            {"lang": "Korean"},
            {"code": "de"},
            "English",
        ]
    )

    assert tracks == ["English", "Indonesian", "Japanese", "Korean", "de"]
