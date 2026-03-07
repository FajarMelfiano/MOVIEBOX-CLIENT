"""Contains functionalities for fetching and modelling downloadable files metadata
and later performing the actual download as well
"""

import hashlib
import os
import re
import typing as t
from pathlib import Path

import httpx
from throttlebuster import DownloadedFile, ThrottleBuster
from throttlebuster.helpers import get_filesize_string, sanitize_filename

from moviebox_api._bases import (
    BaseContentProviderAndHelper,
    BaseFileDownloaderAndHelper,
)
from moviebox_api.constants import (
    CURRENT_WORKING_DIR,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_READ_TIMEOUT_ATTEMPTS,
    DEFAULT_TASKS,
    DOWNLOAD_PART_EXTENSION,
    DOWNLOAD_QUALITIES,
    DOWNLOAD_REQUEST_HEADERS,
    DownloadMode,
    DownloadQualitiesType,
    SubjectType,
)
from moviebox_api.extractor.models.json import (
    ItemJsonDetailsModel,
    PostListItemSubjectModel,
)
from moviebox_api.helpers import assert_instance, get_absolute_url
from moviebox_api.models import (
    CaptionFileMetadata,
    DownloadableFilesMetadata,
    MediaFileMetadata,
    SearchResultsItem,
)
from moviebox_api.requests import Session

__all__ = [
    "MediaFileDownloader",
    "CaptionFileDownloader",
    "DownloadableMovieFilesDetail",
    "DownloadableTVSeriesFilesDetail",
    "resolve_media_file_to_be_downloaded",
]

_RESOLUTION_PATTERN = re.compile(r"(\d{3,4})")
_DEFAULT_FALLBACK_PROVIDERS = ("yflix", "vega:autoEmbed")
_LANGUAGE_CODE_MAP = {
    "english": "en",
    "indonesian": "id",
    "filipino": "fil",
    "french": "fr",
    "portuguese": "pt",
    "portugues": "pt",
    "russian": "ru",
    "arabic": "ar",
    "urdu": "ur",
    "bengali": "bn",
    "punjabi": "pa",
    "chinese": "zh",
    "spanish": "es",
    "unknown": "en",
}


def _normalise_language_code(language: str | None) -> str:
    if not language:
        return "en"

    value = language.strip()
    if len(value) == 2 and value.isascii():
        return value.lower()

    lowered = value.lower()
    if lowered in _LANGUAGE_CODE_MAP:
        return _LANGUAGE_CODE_MAP[lowered]

    if "english" in lowered:
        return "en"

    return lowered[:2] if len(lowered) >= 2 else "en"


def _normalise_resolution(value: str | int | None, default: int = 720) -> int:
    if isinstance(value, int) and value > 0:
        return value

    if isinstance(value, str):
        matched = _RESOLUTION_PATTERN.search(value)
        if matched:
            return int(matched.group(1))

    return default


def resolve_media_file_to_be_downloaded(
    quality: DownloadQualitiesType,
    downloadable_metadata: DownloadableFilesMetadata,
) -> MediaFileMetadata:
    """Gets media-file-metadata that matches the target quality

    Args:
        quality (DownloadQualitiesType): Target media quality such
        downloadable_metadata (DownloadableFilesMetadata): Downloadable files metadata

    Raises:
        RuntimeError: Incase no media file matched the target quality
        ValueError: Unexpected target media quality

    Returns:
        MediaFileMetadata: Media file details matching the target media quality
    """
    match quality:
        case "BEST":
            target_metadata = downloadable_metadata.best_media_file
        case "WORST":
            target_metadata = downloadable_metadata.worst_media_file
        case _:
            if quality in DOWNLOAD_QUALITIES:
                quality_downloads_map = downloadable_metadata.get_quality_downloads_map()
                target_metadata = quality_downloads_map.get(quality)

                if target_metadata is None:
                    raise RuntimeError(
                        f"Media file for quality {quality} does not exists. "
                        f"Try other qualities from {quality_downloads_map.keys()}"
                    )
            else:
                raise ValueError(
                    f"Unknown media file quality passed '{quality}'. Choose from {DOWNLOAD_QUALITIES}"
                )
    return target_metadata


class BaseDownloadableFilesDetail(BaseContentProviderAndHelper):
    """Base class for fetching and modelling downloadable files detail"""

    _url = get_absolute_url(r"/wefeed-h5-bff/web/subject/download")

    def __init__(self, session: Session, item: SearchResultsItem | ItemJsonDetailsModel):
        """Constructor for `BaseDownloadableFilesDetail`

        Args:
            session (Session): MovieboxAPI request session.
            item (SearchResultsItem | ItemJsonDetailsModel): Movie/TVSeries item to handle.
        """
        assert_instance(session, Session, "session")
        assert_instance(item, (SearchResultsItem, ItemJsonDetailsModel), "item")

        self.session = session
        self._raw_item = item
        self._item_details_model: ItemJsonDetailsModel | None = (
            item if isinstance(item, ItemJsonDetailsModel) else None
        )
        self._item: t.Any

        if isinstance(item, ItemJsonDetailsModel):
            self._item = item.resData.subject
            release_date = item.resData.subject.releaseDate
        else:
            self._item = item
            release_date = item.releaseDate

        self._subject_type: SubjectType = self._item.subjectType
        self._item_title: str = self._item.title
        self._item_year: int | None = release_date.year if release_date else None

    def _create_request_params(self, season: int, episode: int) -> dict:
        """Creates request parameters

        Args:
            season (int): Season number of the series.
            episde (int): Episode number of the series.
        Returns:
            t.Dict: Request params
        """
        return {
            "subjectId": self._item.subjectId,
            "se": season,
            "ep": episode,
        }

    async def _request_download_content(self, season: int, episode: int) -> dict:
        """Perform download metadata request against moviebox API."""

        # Referer
        request_header = {"Referer": get_absolute_url(f"/movies/{self._item.detailPath}")}
        # Without the referer, empty response will be served.

        return await self.session.get_with_cookies_from_api(
            url=self._url,
            params=self._create_request_params(season, episode),
            headers=request_header,
        )

    async def _resolve_series_details_model(self) -> ItemJsonDetailsModel | None:
        """Resolve and cache TV-series details model when needed."""

        if self._item_details_model is not None:
            return self._item_details_model

        if not isinstance(self._raw_item, SearchResultsItem):
            return None

        if self._subject_type != SubjectType.TV_SERIES:
            return None

        try:
            from moviebox_api.core import TVSeriesDetails

            details = TVSeriesDetails(self._raw_item, self.session)
            self._item_details_model = await details.get_content_model()
            return self._item_details_model
        except Exception:
            return None

    async def _resolve_best_tv_position(self, season: int, episode: int) -> tuple[int, int] | None:
        """Resolve a valid (season, episode) pair when requested one has no resource."""

        details_model = await self._resolve_series_details_model()
        if details_model is None:
            return None

        seasons = sorted(details_model.resData.resource.seasons, key=lambda current: current.se)
        if not seasons:
            return None

        target_season = next((current for current in seasons if current.se == season), seasons[0])
        target_episode = episode if 1 <= episode <= target_season.maxEp else 1
        return (target_season.se, target_episode)

    @staticmethod
    def _to_non_negative_int(value: t.Any) -> int:
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _supported_http_url(url: str) -> bool:
        lowered = url.lower().strip()
        return lowered.startswith("https://") or lowered.startswith("http://")

    @staticmethod
    def _extract_audio_label_from_stream_source(source: str | None) -> str | None:
        if not source:
            return None

        matched = re.search(r"\[([^\]]+)\]\s*$", source)
        if not matched:
            return None

        label = matched.group(1).strip()
        return label or None

    async def _expand_subtitle_endpoint(self, subtitle_url: str) -> list[tuple[str, str]]:
        """Expand provider subtitle listing endpoints into direct subtitle files."""

        lowered = subtitle_url.lower()
        if not ("/ajax/episode/" in lowered and lowered.endswith("/subtitles")):
            return []

        try:
            response = await self.session.get(subtitle_url)
            payload = response.json()
        except Exception:
            return []

        if not isinstance(payload, list):
            return []

        expanded: list[tuple[str, str]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue

            file_url = str(entry.get("file", "")).strip()
            label = str(entry.get("label", "")).strip()
            if not self._supported_http_url(file_url):
                continue

            expanded.append((file_url, label))

        return expanded

    def _get_fallback_provider_names(self) -> list[str]:
        configured = os.getenv("MOVIEBOX_DOWNLOAD_FALLBACK_PROVIDERS", "").strip()
        providers = (
            [item.strip() for item in configured.split(",") if item.strip()]
            if configured
            else list(_DEFAULT_FALLBACK_PROVIDERS)
        )
        return [provider for provider in providers if provider.lower() != "moviebox"]

    async def _build_fallback_content(self, season: int, episode: int) -> dict[str, t.Any] | None:
        """Build fallback download/caption content via source providers."""

        providers = self._get_fallback_provider_names()
        if not providers:
            return None

        try:
            from moviebox_api.source import SourceResolver
        except Exception:
            return None

        fallback_title = re.sub(r"\[[^\]]+\]", "", self._item_title).strip()
        if not fallback_title:
            fallback_title = self._item_title

        for provider_name in providers:
            streams: list = []
            subtitles: list = []

            resolver = SourceResolver(provider_name=provider_name)
            candidate_years = [self._item_year] if self._item_year is not None else []
            candidate_years.append(None)

            for candidate_year in candidate_years:
                try:
                    _, streams, subtitles = await resolver.resolve(
                        title=fallback_title,
                        subject_type=self._subject_type,
                        year=candidate_year,
                        season=season,
                        episode=episode,
                    )
                except Exception:
                    continue

                if streams or subtitles:
                    break

            if not streams and not subtitles:
                continue

            downloads: list[dict] = []
            for index, stream in enumerate(streams):
                stream_url = str(stream.url).strip()
                if not self._supported_http_url(stream_url):
                    continue

                audio_label = self._extract_audio_label_from_stream_source(
                    str(getattr(stream, "source", "")).strip()
                )

                stream_hash = hashlib.sha1(
                    f"{provider_name}|stream|{index}|{stream_url}".encode(), usedforsecurity=False
                ).hexdigest()
                downloads.append(
                    {
                        "id": stream_hash,
                        "url": stream_url,
                        "resolution": _normalise_resolution(stream.quality),
                        "size": self._to_non_negative_int(stream.size),
                        "audio": audio_label,
                    }
                )

            subtitle_candidates = []
            subtitle_candidates.extend(subtitles)
            for stream in streams:
                subtitle_candidates.extend(stream.subtitles)

            captions: list[dict] = []
            seen_subtitle_urls: set[str] = set()
            for index, subtitle in enumerate(subtitle_candidates):
                subtitle_url = str(subtitle.url).strip()
                if not subtitle_url or subtitle_url in seen_subtitle_urls:
                    continue
                if not self._supported_http_url(subtitle_url):
                    continue

                expanded_urls = await self._expand_subtitle_endpoint(subtitle_url)
                subtitle_entries = expanded_urls or [
                    (subtitle_url, (subtitle.label or subtitle.language or ""))
                ]

                for expanded_index, (resolved_subtitle_url, resolved_label) in enumerate(subtitle_entries):
                    if resolved_subtitle_url in seen_subtitle_urls:
                        continue

                    seen_subtitle_urls.add(resolved_subtitle_url)
                    language_code = _normalise_language_code(resolved_label or subtitle.language)
                    raw_label = (resolved_label or subtitle.label or subtitle.language or "").strip()
                    if raw_label.lower() in {"", "unknown", "sub.list", "subtitle"}:
                        language_label = "English" if language_code == "en" else language_code.upper()
                    else:
                        language_label = raw_label

                    subtitle_hash = hashlib.sha1(
                        (
                            f"{provider_name}|subtitle|{index}|{expanded_index}|{resolved_subtitle_url}"
                        ).encode(),
                        usedforsecurity=False,
                    ).hexdigest()

                    captions.append(
                        {
                            "id": subtitle_hash,
                            "lan": language_code,
                            "lanName": language_label,
                            "url": resolved_subtitle_url,
                            "size": 0,
                            "delay": 0,
                        }
                    )

            if downloads or captions:
                return {
                    "downloads": downloads,
                    "captions": captions,
                    "limited": False,
                    "limitedCode": "",
                    "hasResource": bool(downloads or captions),
                }

        return None

    async def get_content(self, season: int = 0, episode: int = 0) -> dict:
        """Performs the actual fetching of files detail."""

        request_season = season
        request_episode = episode

        content = dict(await self._request_download_content(request_season, request_episode))
        content.setdefault("downloads", [])
        content.setdefault("captions", [])
        content.setdefault("limited", False)
        content.setdefault("limitedCode", "")
        content.setdefault("hasResource", bool(content["downloads"] or content["captions"]))

        if self._subject_type == SubjectType.TV_SERIES and not content["downloads"]:
            resolved_position = await self._resolve_best_tv_position(request_season, request_episode)
            if resolved_position is not None and resolved_position != (request_season, request_episode):
                request_season, request_episode = resolved_position
                content = dict(await self._request_download_content(request_season, request_episode))
                content.setdefault("downloads", [])
                content.setdefault("captions", [])
                content.setdefault("limited", False)
                content.setdefault("limitedCode", "")
                content.setdefault("hasResource", bool(content["downloads"] or content["captions"]))

        if not content["downloads"] or not content["captions"]:
            fallback_content = await self._build_fallback_content(request_season, request_episode)
            if fallback_content is not None:
                if not content["downloads"]:
                    content["downloads"] = fallback_content["downloads"]
                if not content["captions"]:
                    content["captions"] = fallback_content["captions"]
                content["hasResource"] = bool(content["downloads"] or content["captions"])

        return content

    async def get_content_model(self, season: int = 0, episode: int = 0) -> DownloadableFilesMetadata:
        """Get modelled version of the downloadable files detail.

        Args:
            season (int): Season number of the series.
            episde (int): Episode number of the series.

        Returns:
            DownloadableFilesMetadata: Modelled file details
        """
        contents = await self.get_content(season, episode)
        return DownloadableFilesMetadata(**contents)


class DownloadableMovieFilesDetail(BaseDownloadableFilesDetail):
    """Fetches and model movie files detail"""

    async def get_content(self, season: int = 0, episode: int = 0) -> dict:
        """Actual fetch of files detail"""
        return await super().get_content(season=0, episode=0)

    async def get_content_model(self, season: int = 0, episode: int = 0) -> DownloadableFilesMetadata:
        """Modelled version of the files detail"""
        contents = await self.get_content()
        return DownloadableFilesMetadata(**contents)


class DownloadableTVSeriesFilesDetail(BaseDownloadableFilesDetail):
    """Fetches and model series files detail"""

    # NOTE: Already implemented by parent class - BaseDownloadableFilesDetail


class MediaFileDownloader(BaseFileDownloaderAndHelper):
    """Download movie and tv-series files"""

    request_headers = DOWNLOAD_REQUEST_HEADERS
    request_cookies = {}

    movie_filename_template = "{title} ({release_year}).{ext}"
    series_filename_template = "{title} S{season}E{episode}.{ext}"

    # Should have been named episode_filename_template but for consistency
    # with the subject-types {movie, tv-series, music} it's better as it is
    possible_filename_placeholders = (
        "{title}",
        "{release_year}",
        "{release_date}",
        "{resolution}",
        "{ext}",
        "{size_string}",
        "{season}",
        "{episode}",
    )

    def __init__(
        self,
        dir: Path | str = CURRENT_WORKING_DIR,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        tasks: int = DEFAULT_TASKS,
        part_dir: Path | str = CURRENT_WORKING_DIR,
        part_extension: str = DOWNLOAD_PART_EXTENSION,
        merge_buffer_size: int | None = None,
        group_series: bool = False,
        request_headers: dict[str, str] | None = None,
        **httpx_kwargs,
    ):
        """Constructor for `MediaFileDownloader`

        Args:
            dir (Path | str, optional): Directory for saving downloaded files to. Defaults to CURRENT_WORKING_DIR.
            chunk_size (int, optional): Streaming download chunk size in kilobytes. Defaults to DEFAULT_CHUNK_SIZE.
            tasks (int, optional): Number of tasks to carry out the download. Defaults to DEFAULT_TASKS.
            part_dir (Path | str, optional): Directory for temporarily saving downloaded file-parts to. Defaults to CURRENT_WORKING_DIR.
            part_extension (str, optional): Filename extension for download parts. Defaults to DOWNLOAD_PART_EXTENSION.
            merge_buffer_size (int|None, optional). Buffer size for merging the separated files in kilobytes. Defaults to chunk_size.
            group_series(bool, optional): Create directory for a series & group episodes based on season number. Defaults to False.

        httpx_kwargs : Keyword arguments for `httpx.AsyncClient`
        """  # noqa: E501

        httpx_kwargs.setdefault("cookies", self.request_cookies)
        self.group_series = group_series
        self.request_headers = dict(request_headers or self.__class__.request_headers)

        self.throttle_buster = ThrottleBuster(
            dir=dir,
            chunk_size=chunk_size,
            tasks=tasks,
            part_dir=part_dir,
            part_extension=part_extension,
            merge_buffer_size=merge_buffer_size,
            request_headers=self.request_headers,
            **httpx_kwargs,
        )

    def generate_filename(
        self,
        search_results_item: SearchResultsItem,
        media_file: MediaFileMetadata,
        season: int = 0,
        episode: int = 0,
        test: bool = False,
    ) -> tuple[str, Path]:
        """Generates filename in the format as in `self.*filename_template` and updates
        final directory for saving contents

        Args:
            search_results_item (SearchResultsItem)
            media_file (MediaFileMetadata): Movie/tv-series/music to be downloaded.
            season (int): Season number of the series.
            episde (int): Episode number of the series.

        """
        assert_instance(
            search_results_item,
            SearchResultsItem,
            "search_results_item",
        )

        assert_instance(media_file, MediaFileMetadata, "media_file")

        placeholders = dict(
            title=search_results_item.title,
            release_date=str(search_results_item.releaseDate),
            release_year=search_results_item.releaseDate.year,
            ext=media_file.ext,
            resolution=media_file.resolution,
            size_string=get_filesize_string(media_file.size),
            season=season,
            episode=episode,
        )

        filename_template: str = (
            self.series_filename_template
            if search_results_item.subjectType == SubjectType.TV_SERIES
            else self.movie_filename_template
        )

        final_dir = self.create_final_dir(
            working_dir=self.throttle_buster.dir,
            search_results_item=search_results_item,
            season=season,
            episode=episode,
            test=test,
            group=self.group_series,
        )

        return filename_template.format(**placeholders), final_dir

    async def run(
        self,
        media_file: MediaFileMetadata,
        filename: str | SearchResultsItem,
        progress_hook: callable = None,
        mode: DownloadMode = DownloadMode.AUTO,
        disable_progress_bar: bool = None,
        file_size: int = None,
        keep_parts: bool = False,
        timeout_retry_attempts: int = DEFAULT_READ_TIMEOUT_ATTEMPTS,
        colour: str = "cyan",
        simple: bool = False,
        test: bool = False,
        leave: bool = True,
        ascii: bool = False,
        **filename_kwargs,
    ) -> DownloadedFile | httpx.Response:
        """Performs the actual download.

        Args:
            media_file (MediaFileMetadata): Movie/tv-series/music to be downloaded.
            filename (str, optional): Filename for the downloaded content. Defaults to None.
            progress_hook (callable, optional): Function to call with the download progress information. Defaults to None.
            mode (DownloadMode, optional): Whether to start or resume incomplete download. Defaults DownloadMode.AUTO.
            disable_progress_bar (bool, optional): Do not show progress_bar. Defaults to None (decide based on progress_hook).
            file_size (int, optional): Size of the file to be downloaded. Defaults to None.
            keep_parts (bool, optional): Whether to retain the separate download parts. Defaults to False.
            timeout_retry_attempts (int, optional): Number of times to retry download upon read request timing out. Defaults to DEFAULT_READ_TIMEOUT_ATTEMPTS.
            leave (bool, optional): Keep all leaves of the progressbar. Defaults to True.
            colour (str, optional): Progress bar display color. Defaults to "cyan".
            simple (bool, optional): Show percentage and bar only in progressbar. Deafults to False.
            test (bool, optional): Just test if download is possible but do not actually download. Defaults to False.
            ascii (bool, optional): Use unicode (smooth blocks) to fill the progress-bar meter. Defaults to False.

        filename_kwargs: Keyworded arguments for generating filename incase instance of filename is SearchResultsItem.

        Returns:
            DownloadedFile | httpx.Response: Downloaded file details or httpx stream response (test).
        """  # noqa: E501

        assert_instance(media_file, MediaFileMetadata, "media_file")

        dir = None

        if isinstance(filename, SearchResultsItem):
            filename, dir = self.generate_filename(
                search_results_item=filename, media_file=media_file, test=test, **filename_kwargs
            )

        elif self.group_series:
            raise ValueError(
                f"Value for filename should be an instance of {SearchResultsItem} "
                "when group_series is activated"
            )

        return await self.throttle_buster.run(
            url=str(media_file.url),
            filename=filename,
            progress_hook=progress_hook,
            mode=mode,
            disable_progress_bar=disable_progress_bar,
            file_size=file_size,
            keep_parts=keep_parts,
            timeout_retry_attempts=timeout_retry_attempts,
            colour=colour,
            simple=simple,
            test=test,
            leave=leave,
            ascii=ascii,
            dir=dir,
        )


class CaptionFileDownloader(BaseFileDownloaderAndHelper):
    """Creates a local copy of a remote subtitle/caption file"""

    request_headers = DOWNLOAD_REQUEST_HEADERS
    request_cookies = {}
    movie_filename_template = "{title} ({release_year}).{lan}.{ext}"
    series_filename_template = "{title} S{season}E{episode}.{lan}.{ext}"
    possible_filename_placeholders = (
        "{title}",
        "{release_year}",
        "{release_date}",
        "{ext}",
        "{size_string}",
        "{id}",
        "{lan}",
        "{lanName}",
        "{delay}",
        "{season}",
        "{episode}",
    )

    def __init__(
        self,
        dir: Path | str = CURRENT_WORKING_DIR,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        tasks: int = DEFAULT_TASKS,
        part_dir: Path | str = CURRENT_WORKING_DIR,
        part_extension: str = DOWNLOAD_PART_EXTENSION,
        merge_buffer_size: int | None = None,
        group_series: bool = False,
        request_headers: dict[str, str] | None = None,
        **httpx_kwargs,
    ):
        """Constructor for `CaptionFileDownloader`
        Args:
            dir (Path | str, optional): Directory for downloaded files to. Defaults to CURRENT_WORKING_DIR.
            chunk_size (int, optional): Streaming download chunk size in kilobytes. Defaults to DEFAULT_CHUNK_SIZE.
            tasks (int, optional): Number of tasks to carry out the download. Defaults to DEFAULT_TASKS.
            part_dir (Path | str, optional): Directory for temporarily saving downloaded file-parts to. Defaults to CURRENT_WORKING_DIR.
            part_extension (str, optional): Filename extension for download parts. Defaults to DOWNLOAD_PART_EXTENSION.
            merge_buffer_size (int|None, optional). Buffer size for merging the separated files in kilobytes. Defaults to chunk_size.
            group_series(bool, optional): Create directory for a series & group episodes based on season number. Defaults to False.

        httpx_kwargs : Keyword arguments for `httpx.AsyncClient`
        """  # noqa: E501

        httpx_kwargs.setdefault("cookies", self.request_cookies)
        self.group_series = group_series
        self.request_headers = dict(request_headers or self.__class__.request_headers)

        self.throttle_buster = ThrottleBuster(
            dir=dir,
            chunk_size=chunk_size,
            tasks=tasks,
            part_dir=part_dir,
            part_extension=part_extension,
            merge_buffer_size=merge_buffer_size,
            request_headers=self.request_headers,
            **httpx_kwargs,
        )

    def generate_filename(
        self,
        search_results_item: SearchResultsItem,
        caption_file: CaptionFileMetadata,
        season: int = 0,
        episode: int = 0,
        test: bool = False,
        **kwargs,
    ) -> tuple[str, Path]:
        """Generates filename in the format as in `self.*filename_template`

        Args:
            search_results_item (SearchResultsItem)
            caption_file (CaptionFileMetadata): Movie/tv-series/music caption file details.
            season (int): Season number of the series.
            episde (int): Episode number of the series.
            test (bool, optional): whether to create final directory

        Kwargs: Nothing much folk.
                It's just here so that `MediaFileDownloader.run` and `CaptionFileDownloader.run`
                will accept similar parameters in `moviebox_api.extra.movies.Auto.run` method.
        """
        assert_instance(
            search_results_item,
            SearchResultsItem,
            "search_results_item",
        )

        placeholders = dict(
            title=search_results_item.title,
            release_date=str(search_results_item.releaseDate),
            release_year=search_results_item.releaseDate.year,
            ext=caption_file.ext,
            lan=caption_file.lan,
            lanName=caption_file.lanName,
            delay=caption_file.delay,
            size_string=get_filesize_string(caption_file.size),
            season=season,
            episode=episode,
        )

        filename_template: str = (
            self.series_filename_template
            if search_results_item.subjectType == SubjectType.TV_SERIES
            else self.movie_filename_template
        )

        final_dir = self.create_final_dir(
            working_dir=self.throttle_buster.dir,
            search_results_item=search_results_item,
            season=season,
            episode=episode,
            test=test,
            group=self.group_series,
        )

        return sanitize_filename(filename_template.format(**placeholders)), final_dir

    async def run(
        self,
        caption_file: CaptionFileMetadata,
        filename: str | SearchResultsItem,
        season: int = 0,
        episode: int = 0,
        **run_kwargs,
    ) -> DownloadedFile | httpx.Response:
        """Performs the actual download, incase already downloaded then return its Path.

        Args:
            caption_file (CaptionFileMetadata): Movie/tv-series/music caption file details.
            filename (str|SearchResultsItem): Movie filename
            season (int): Season number of the series. Defaults to 0.
            episde (int): Episode number of the series. Defaults to 0.

        run_kwargs: Keyword arguments for `ThrottleBuster.run`

        Returns:
            Path | httpx.Response: Path where the caption file has been saved to or httpx Response (test).
        """

        assert_instance(caption_file, CaptionFileMetadata, "caption_file")

        if run_kwargs.get("test") and "suppress_incompatible_error" not in run_kwargs:
            run_kwargs["suppress_incompatible_error"] = True
        if run_kwargs.get("test") and run_kwargs.get("file_size") is None:
            run_kwargs["file_size"] = 1

        dir = None

        if isinstance(filename, SearchResultsItem):
            # Lets generate filename
            filename, dir = self.generate_filename(
                search_results_item=filename,
                caption_file=caption_file,
                season=season,
                episode=episode,
                test=run_kwargs.get("test", False),
            )
        return await self.throttle_buster.run(
            url=str(caption_file.url), filename=filename, dir=dir, **run_kwargs
        )
