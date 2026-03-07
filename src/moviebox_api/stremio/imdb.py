"""IMDB ID resolution via Stremio's Cinemeta API.

Stremio sends IMDB IDs (e.g. tt1234567) but moviebox-api searches by title.
This module bridges the gap by resolving IMDB IDs to movie/series titles
using Stremio's built-in Cinemeta addon, with IMDB page scraping as fallback.
"""

import logging
import re
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)

CINEMETA_BASE_URL = "https://v3-cinemeta.strem.io"


class CinemetaInfo:
    """Resolved info from Cinemeta for an IMDB ID."""

    def __init__(self, data: dict | None = None, title: str = "", year: int = 0, content_type: str = "movie"):
        if data:
            meta = data.get("meta", {})
            self.imdb_id: str = meta.get("id", "")
            self.title: str = meta.get("name", "")
            self.year: int = 0
            self.content_type: str = meta.get("type", "movie")
            self.poster: str = meta.get("poster", "")
            self.description: str = meta.get("description", "")

            release_info = meta.get("releaseInfo", "")
            if release_info:
                try:
                    self.year = int(release_info.split("-")[0])
                except (ValueError, IndexError):
                    pass
        else:
            self.imdb_id = ""
            self.title = title
            self.year = year
            self.content_type = content_type
            self.poster = ""
            self.description = ""

    def __repr__(self) -> str:
        return f"CinemetaInfo(imdb_id={self.imdb_id!r}, title={self.title!r}, year={self.year})"


# In-memory cache for IMDB lookups (up to 512 entries)
_cache: dict[str, CinemetaInfo | None] = {}
_CACHE_MAX_SIZE = 512


async def _resolve_via_cinemeta(imdb_id: str, content_type: str) -> CinemetaInfo | None:
    """Try resolving via Cinemeta API."""
    url = f"{CINEMETA_BASE_URL}/meta/{content_type}/{imdb_id}.json"
    logger.info(f"Resolving IMDB {imdb_id} via Cinemeta: {url}")

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        if not data or not data.get("meta"):
            return None

        info = CinemetaInfo(data)
        if not info.title:
            return None

        logger.info(f"Cinemeta resolved {imdb_id} -> {info.title} ({info.year})")
        return info

    except Exception as e:
        logger.debug(f"Cinemeta failed for {imdb_id}: {e}")
        return None


async def _resolve_via_imdb_scrape(imdb_id: str, content_type: str) -> CinemetaInfo | None:
    """Fallback: scrape IMDB page for title and year."""
    url = f"https://www.imdb.com/title/{imdb_id}/"
    logger.info(f"Fallback: scraping IMDB page for {imdb_id}")

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            html = response.text

        # Extract from <title>The Movie Name (2025) - IMDb</title>
        match = re.search(r"<title>(.*?)\s*(?:\((\d{4})\))?\s*[-–]?\s*IMDb</title>", html)
        if not match:
            logger.warning(f"Could not parse IMDB page title for {imdb_id}")
            return None

        title = match.group(1).strip()
        year = int(match.group(2)) if match.group(2) else 0

        # Clean title: remove " (TV Series)" etc.
        title = re.sub(r"\s*\(TV (?:Series|Mini Series|Movie|Special)\)\s*$", "", title)

        if not title:
            return None

        logger.info(f"IMDB scrape resolved {imdb_id} -> {title} ({year})")
        return CinemetaInfo(title=title, year=year, content_type=content_type)

    except Exception as e:
        logger.error(f"IMDB scrape failed for {imdb_id}: {e}")
        return None


async def resolve_imdb(imdb_id: str, content_type: str = "movie") -> CinemetaInfo | None:
    """Resolve an IMDB ID to title/year info.

    Tries Cinemeta first, falls back to IMDB page scraping.

    Args:
        imdb_id: IMDB ID, e.g. "tt1234567"
        content_type: "movie" or "series"

    Returns:
        CinemetaInfo with title and year, or None if not found.
    """
    cache_key = f"{content_type}:{imdb_id}"

    if cache_key in _cache:
        logger.debug(f"Cache hit for {cache_key}")
        return _cache[cache_key]

    # Strategy 1: Cinemeta
    info = await _resolve_via_cinemeta(imdb_id, content_type)

    # Strategy 2: IMDB page scraping fallback
    if not info:
        info = await _resolve_via_imdb_scrape(imdb_id, content_type)

    if not info:
        logger.warning(f"Could not resolve IMDB {imdb_id} from any source")
        _cache[cache_key] = None
        return None

    # Evict oldest if cache is full
    if len(_cache) >= _CACHE_MAX_SIZE:
        oldest_key = next(iter(_cache))
        del _cache[oldest_key]

    _cache[cache_key] = info
    return info


def parse_video_id(video_id: str) -> tuple[str, int, int]:
    """Parse a Stremio video ID into IMDB ID, season, and episode.

    For movies: video_id = "tt1234567" → ("tt1234567", 0, 0)
    For series: video_id = "tt1234567:2:5" → ("tt1234567", 2, 5)

    Args:
        video_id: The video ID from Stremio.

    Returns:
        Tuple of (imdb_id, season, episode).
    """
    parts = video_id.split(":")
    imdb_id = parts[0]
    season = int(parts[1]) if len(parts) > 1 else 0
    episode = int(parts[2]) if len(parts) > 2 else 0
    return imdb_id, season, episode
