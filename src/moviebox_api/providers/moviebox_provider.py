"""Native Moviebox provider adapter."""

from moviebox_api.constants import SubjectType
from moviebox_api.core import Search
from moviebox_api.download import DownloadableMovieFilesDetail, DownloadableTVSeriesFilesDetail
from moviebox_api.models import SearchResultsItem
from moviebox_api.providers.base import BaseStreamProvider
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle
from moviebox_api.requests import Session


class MovieboxProvider(BaseStreamProvider):
    """Adapter over the existing moviebox-api integration."""

    name = "moviebox"

    def __init__(self, session: Session | None = None):
        self._session = session or Session()

    async def search(
        self,
        query: str,
        subject_type: SubjectType,
        *,
        year: int | None = None,
        limit: int = 20,
    ) -> list[ProviderSearchResult]:
        search = Search(self._session, query, subject_type)
        results = await search.get_content_model()

        mapped: list[ProviderSearchResult] = []
        for item in results.items[:limit]:
            mapped.append(
                ProviderSearchResult(
                    id=item.subjectId,
                    title=item.title,
                    page_url=item.page_url,
                    subject_type=item.subjectType,
                    year=item.releaseDate.year,
                    payload={"raw_item": item},
                )
            )

        if year:
            return [item for item in mapped if item.year == year] or mapped

        return mapped

    async def resolve_streams(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderStream]:
        raw_item: SearchResultsItem | None = item.payload.get("raw_item")
        if raw_item is None:
            raise ValueError("Moviebox provider expects raw_item payload")

        if item.subject_type == SubjectType.TV_SERIES and (season <= 0 or episode <= 0):
            season = 1
            episode = 1

        if item.subject_type == SubjectType.TV_SERIES:
            details = DownloadableTVSeriesFilesDetail(self._session, raw_item)
            metadata = await details.get_content_model(season=season, episode=episode)
        else:
            details = DownloadableMovieFilesDetail(self._session, raw_item)
            metadata = await details.get_content_model()

        subtitles = [
            ProviderSubtitle(
                url=str(caption.url),
                language=caption.lan,
                label=caption.lanName,
            )
            for caption in metadata.captions
        ]

        streams = [
            ProviderStream(
                url=str(media.url),
                source="moviebox",
                quality=f"{media.resolution}P",
                size=media.size,
                audio=media.audio,
                subtitles=subtitles,
            )
            for media in sorted(metadata.downloads, key=lambda entry: entry.resolution, reverse=True)
        ]
        return streams

    async def resolve_subtitles(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderSubtitle]:
        streams = await self.resolve_streams(item, season=season, episode=episode)
        if not streams:
            return []

        dedup: dict[str, ProviderSubtitle] = {}
        for subtitle in streams[0].subtitles:
            dedup[subtitle.url] = subtitle
        return list(dedup.values())
