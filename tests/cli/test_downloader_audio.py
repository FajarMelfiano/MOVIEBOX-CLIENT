import pytest

from moviebox_api.cli.downloader import Downloader
from moviebox_api.models import DownloadableFilesMetadata


def _build_details() -> DownloadableFilesMetadata:
    return DownloadableFilesMetadata(
        downloads=[
            {
                "id": "1",
                "url": "https://example.com/movie-eng-720.m3u8",
                "resolution": 720,
                "size": 1,
                "audio": "English",
            },
            {
                "id": "2",
                "url": "https://example.com/movie-ind-1080.m3u8",
                "resolution": 1080,
                "size": 1,
                "audio": "Indonesian",
            },
            {
                "id": "3",
                "url": "https://example.com/movie-ind-720.m3u8",
                "resolution": 720,
                "size": 1,
                "audio": "Indonesian",
            },
        ],
        captions=[],
        limited=False,
        limitedCode="",
        hasResource=True,
    )


def test_resolve_target_media_file_filters_by_audio_label():
    details = _build_details()

    selected = Downloader._resolve_target_media_file(details, "BEST", "indonesian")

    assert selected.audio == "Indonesian"
    assert selected.resolution == 1080


def test_resolve_target_media_file_raises_for_missing_audio():
    details = _build_details()

    with pytest.raises(ValueError, match="Requested audio"):
        Downloader._resolve_target_media_file(details, "BEST", "japanese")
