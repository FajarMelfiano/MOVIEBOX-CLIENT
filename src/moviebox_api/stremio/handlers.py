"""Core handlers for Stremio addon requests.

Handles stream, catalog, and subtitle requests by bridging
Stremio's IMDB-based system to moviebox-api's title-based search.
Moviebox streams and subtitles are served through the local proxy
for compatibility with CDN auth headers. Other providers are
returned as direct URLs.
"""

import logging
import os

from moviebox_api.constants import SubjectType
from moviebox_api.core import Search, Trending
from moviebox_api.models import SearchResultsItem, SearchResultsModel
from moviebox_api.providers import get_provider
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


def _format_provider_subtitles(subtitles: list, *, proxy: bool, provider_name: str) -> list[dict]:
    mapped = []
    seen_urls = set()

    for index, subtitle in enumerate(subtitles):
        if subtitle.url in seen_urls:
            continue
        seen_urls.add(subtitle.url)

        mapped.append(
            {
                "id": f"{provider_name}-{subtitle.language}-{index}",
                "url": _proxy_subtitle_url(subtitle.url) if proxy else subtitle.url,
                "lang": subtitle.language,
            }
        )

    return mapped


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

    subject_type = SubjectType.TV_SERIES if content_type == "series" else SubjectType.MOVIES

    provider_name = os.getenv("MOVIEBOX_PROVIDER", "moviebox")

    try:
        provider = get_provider(provider_name)
    except Exception as exc:
        logger.error(f"Invalid provider '{provider_name}': {exc}")
        return {"streams": []}

    try:
        item = await provider.search_best_match(info.title, subject_type, year=info.year)
        if not item:
            logger.warning(f"No {provider.name} results for '{info.title}'")
            return {"streams": []}

        target_season = season if content_type == "series" else 0
        target_episode = episode if content_type == "series" else 0
        resolved_streams = await provider.resolve_streams(
            item,
            season=target_season,
            episode=target_episode,
        )
    except Exception as exc:
        logger.error(f"Provider stream resolution failed ({provider.name}): {exc}")
        return {"streams": []}

    if not resolved_streams:
        logger.warning(f"No streams resolved by provider '{provider.name}' for {info.title}")
        return {"streams": []}

    should_proxy = provider.name == "moviebox"

    streams = []
    for stream in resolved_streams:
        quality = stream.quality or "AUTO"

        description = quality
        if stream.size:
            description = f"{quality} • {_format_size(stream.size)}"

        stream_obj = {
            "name": f"{provider.name.title()} {quality}",
            "description": description,
            "url": _proxy_media_url(stream.url) if should_proxy else stream.url,
            "behaviorHints": {
                "bingeGroup": f"{provider.name}-{quality.lower()}",
            },
        }

        subtitles = _format_provider_subtitles(
            stream.subtitles,
            proxy=should_proxy,
            provider_name=provider.name,
        )
        if subtitles:
            stream_obj["subtitles"] = subtitles

        streams.append(stream_obj)

    logger.info(
        f"Returning {len(streams)} streams for {info.title}{f' S{season}E{episode}' if season > 0 else ''}"
    )
    return {"streams": streams}


async def handle_subtitles(content_type: str, video_id: str) -> dict:
    """Handle a Stremio subtitles request with proxied URLs."""
    imdb_id, season, episode = parse_video_id(video_id)

    info = await resolve_imdb(imdb_id, content_type)
    if not info:
        return {"subtitles": []}

    subject_type = SubjectType.TV_SERIES if content_type == "series" else SubjectType.MOVIES

    provider_name = os.getenv("MOVIEBOX_PROVIDER", "moviebox")

    try:
        provider = get_provider(provider_name)
    except Exception as exc:
        logger.error(f"Invalid provider '{provider_name}': {exc}")
        return {"subtitles": []}

    try:
        item = await provider.search_best_match(info.title, subject_type, year=info.year)
        if not item:
            return {"subtitles": []}

        target_season = season if content_type == "series" else 0
        target_episode = episode if content_type == "series" else 0

        subtitles = await provider.resolve_subtitles(item, season=target_season, episode=target_episode)

        if not subtitles:
            streams = await provider.resolve_streams(item, season=target_season, episode=target_episode)
            for stream in streams:
                subtitles.extend(stream.subtitles)
    except Exception as exc:
        logger.error(f"Provider subtitles resolution failed ({provider.name}): {exc}")
        return {"subtitles": []}

    if not subtitles:
        return {"subtitles": []}

    mapped_subtitles = _format_provider_subtitles(
        subtitles,
        proxy=provider.name == "moviebox",
        provider_name=provider.name,
    )

    logger.info(f"Returning {len(mapped_subtitles)} subtitles for {info.title}")
    return {"subtitles": mapped_subtitles}


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
            subject_type = SubjectType.TV_SERIES if content_type == "series" else SubjectType.MOVIES
            search = Search(session, query, subject_type)
            results = await search.get_content_model()

            for item in results.items[:20]:
                meta = _item_to_meta_preview(item, content_type)
                if meta:
                    metas.append(meta)

        elif "trending" in (catalog_id or ""):
            subject_type = SubjectType.TV_SERIES if content_type == "series" else SubjectType.MOVIES
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
