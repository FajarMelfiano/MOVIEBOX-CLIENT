"""Core handlers for Stremio addon requests.

Handles stream, catalog, and subtitle requests by bridging
Stremio's IMDB-based system to moviebox-api's title-based search.
All streams and subtitles are served through the local proxy for
maximum compatibility (CDN requires auth headers).
"""

import logging
from difflib import SequenceMatcher

from moviebox_api.constants import SubjectType
from moviebox_api.core import Search, Trending
from moviebox_api.download import (
    DownloadableMovieFilesDetail,
    DownloadableTVSeriesFilesDetail,
)
from moviebox_api.models import (
    DownloadableFilesMetadata,
    SearchResultsItem,
    SearchResultsModel,
)
from moviebox_api.requests import Session
from moviebox_api.stremio.imdb import CinemetaInfo, parse_video_id, resolve_imdb

logger = logging.getLogger(__name__)


def _proxy_media_url(cdn_url: str) -> str:
    """Convert a CDN URL to a proxied URL through our addon server."""
    from moviebox_api.stremio.server import encode_url, get_server_base_url
    return f"{get_server_base_url()}/proxy/media/{encode_url(cdn_url)}"


def _proxy_subtitle_url(cdn_url: str) -> str:
    """Convert a subtitle CDN URL to a proxied URL through our addon server."""
    from moviebox_api.stremio.server import encode_url, get_server_base_url
    return f"{get_server_base_url()}/proxy/subtitle/{encode_url(cdn_url)}"


def _format_size(size_bytes: int) -> str:
    """Format file size to human readable string."""
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} GB"
    elif size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.0f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


def _title_similarity(a: str, b: str) -> float:
    """Calculate similarity between two titles (0.0 to 1.0)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


async def _search_moviebox(
    session: Session,
    title: str,
    subject_type: SubjectType,
    year: int = 0,
) -> SearchResultsItem | None:
    """Search moviebox for a title and return the best matching item.
    
    Uses title similarity matching to avoid false positives (e.g. searching 'Iron Lung' 
    but getting 'Avatar' due to year match).
    """
    try:
        search = Search(session, title, subject_type)
        results: SearchResultsModel = await search.get_content_model()

        if not results.items:
            logger.warning(f"No moviebox results for '{title}'")
            return None

        # Sort all results by title similarity to the requested title
        scored_items = []
        for item in results.items:
            # Clean title for comparison (remove year if present in title string)
            score = _title_similarity(title, item.title)
            scored_items.append((score, item))
        
        # Sort by score descending
        scored_items.sort(key=lambda x: x[0], reverse=True)
        
        # Log top 3 matches for debugging
        top_matches = [f"{item.title} ({score:.2f})" for score, item in scored_items[:3]]
        logger.info(f"Top matches for '{title}': {', '.join(top_matches)}")

        best_item = None
        best_score = 0.0

        # Strategy 1: Find high similarity + correct year
        if year > 0:
            for score, item in scored_items:
                # Accept year match only if title is reasonably similar (> 0.6)
                if item.releaseDate.year == year and score > 0.6:
                    logger.info(f"Year-matched & verified: {item.title} ({item.releaseDate.year}) score={score:.2f}")
                    return item
        
        # Strategy 2: Fallback to highest similarity score
        # But ensure it's actually similar (> 0.6)
        first_score, first_item = scored_items[0]
        if first_score > 0.6:
            logger.info(f"Best title match: {first_item.title} ({first_item.releaseDate.year}) score={first_score:.2f}")
            return first_item
            
        logger.warning(f"No good match found for '{title}'. Best was '{first_item.title}' with score {first_score:.2f}")
        return None

    except Exception as e:
        logger.error(f"Moviebox search failed for '{title}': {e}")
        return None


async def _get_downloadable_metadata(
    session: Session,
    item: SearchResultsItem,
    season: int,
    episode: int,
) -> DownloadableFilesMetadata | None:
    """Fetch downloadable file metadata."""
    try:
        if season == 0 and episode == 0:
            detail = DownloadableMovieFilesDetail(session, item)
            return await detail.get_content_model()
        else:
            detail = DownloadableTVSeriesFilesDetail(session, item)
            return await detail.get_content_model(season, episode)
    except Exception as e:
        logger.error(f"Failed to get metadata: {e}")
        return None


async def handle_stream(content_type: str, video_id: str) -> dict:
    """Handle a Stremio stream request.

    Returns proxied stream URLs — our server fetches CDN content
    with correct auth headers and streams to Stremio.
    """
    imdb_id, season, episode = parse_video_id(video_id)

    info: CinemetaInfo | None = await resolve_imdb(imdb_id, content_type)
    if not info:
        logger.warning(f"Could not resolve IMDB {imdb_id}")
        return {"streams": []}

    subject_type = (
        SubjectType.TV_SERIES if content_type == "series" else SubjectType.MOVIES
    )

    session = Session()
    item = await _search_moviebox(session, info.title, subject_type, info.year)
    if not item:
        return {"streams": []}

    metadata = await _get_downloadable_metadata(session, item, season, episode)
    if not metadata or not metadata.downloads:
        logger.warning(f"No downloadable files for {info.title}")
        return {"streams": []}

    # Build proxied subtitle list
    proxy_subtitles = []
    if metadata.captions:
        proxy_subtitles = [
            {
                "id": f"moviebox-{caption.lan}",
                "url": _proxy_subtitle_url(str(caption.url)),
                "lang": caption.lan,
            }
            for caption in metadata.captions
        ]

    # Build streams — proxied URLs, sorted highest resolution first
    streams = []
    for media_file in sorted(metadata.downloads, key=lambda f: f.resolution, reverse=True):
        resolution = f"{media_file.resolution}P"
        size_str = _format_size(media_file.size)

        stream_obj = {
            "name": f"MovieBox {resolution}",
            "description": f"{resolution} • {size_str}",
            "url": _proxy_media_url(str(media_file.url)),
            "behaviorHints": {
                "bingeGroup": f"moviebox-{media_file.resolution}",
            },
        }

        if proxy_subtitles:
            stream_obj["subtitles"] = proxy_subtitles

        streams.append(stream_obj)

    logger.info(
        f"Returning {len(streams)} streams for {info.title}"
        f"{f' S{season}E{episode}' if season > 0 else ''}"
    )
    return {"streams": streams}


async def handle_subtitles(content_type: str, video_id: str) -> dict:
    """Handle a Stremio subtitles request with proxied URLs."""
    imdb_id, season, episode = parse_video_id(video_id)

    info = await resolve_imdb(imdb_id, content_type)
    if not info:
        return {"subtitles": []}

    subject_type = (
        SubjectType.TV_SERIES if content_type == "series" else SubjectType.MOVIES
    )

    session = Session()
    item = await _search_moviebox(session, info.title, subject_type, info.year)
    if not item:
        return {"subtitles": []}

    metadata = await _get_downloadable_metadata(session, item, season, episode)
    if not metadata or not metadata.captions:
        return {"subtitles": []}

    subtitles = [
        {
            "id": f"moviebox-{caption.lan}-{caption.id}",
            "url": _proxy_subtitle_url(str(caption.url)),
            "lang": caption.lan,
        }
        for caption in metadata.captions
    ]

    logger.info(f"Returning {len(subtitles)} subtitles for {info.title}")
    return {"subtitles": subtitles}


async def handle_catalog(
    content_type: str,
    catalog_id: str,
    extra_args: dict | None = None,
) -> dict:
    """Handle a Stremio catalog request."""
    session = Session()
    metas = []

    try:
        if "search" in (catalog_id or "") and extra_args and extra_args.get("search"):
            query = extra_args["search"]
            subject_type = (
                SubjectType.TV_SERIES
                if content_type == "series"
                else SubjectType.MOVIES
            )
            search = Search(session, query, subject_type)
            results = await search.get_content_model()

            for item in results.items[:20]:
                meta = _item_to_meta_preview(item, content_type)
                if meta:
                    metas.append(meta)

        elif "trending" in (catalog_id or ""):
            subject_type = (
                SubjectType.TV_SERIES
                if content_type == "series"
                else SubjectType.MOVIES
            )
            trending = Trending(session, subject_type)
            results = await trending.get_content_model()

            for item in results.items[:20]:
                meta = _item_to_meta_preview(item, content_type)
                if meta:
                    metas.append(meta)

    except Exception as e:
        logger.error(f"Catalog handler error: {e}")

    logger.info(f"Returning {len(metas)} catalog items for {catalog_id}")
    return {"metas": metas}


def _item_to_meta_preview(item: SearchResultsItem, content_type: str) -> dict | None:
    """Convert a moviebox SearchResultsItem to a Stremio meta preview object."""
    try:
        poster_url = ""
        if item.cover:
            poster_url = str(item.cover.url)

        return {
            "id": f"moviebox:{item.subjectId}",
            "type": content_type,
            "name": item.title,
            "poster": poster_url,
            "description": item.description,
            "releaseInfo": str(item.releaseDate.year),
            "imdbRating": str(item.imdbRatingValue) if item.imdbRatingValue else None,
            "genres": item.genre if item.genre else [],
        }
    except Exception as e:
        logger.error(f"Failed to convert item to meta preview: {e}")
        return None
