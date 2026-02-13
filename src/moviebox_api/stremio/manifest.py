"""Stremio addon manifest definition.

The manifest describes the addon's capabilities to Stremio:
- Provides streams for movies and series (matched by IMDB ID prefix "tt")
- Provides subtitles for movies and series
- Provides catalogs: trending movies, search, trending series
"""

MANIFEST = {
    "id": "community.moviebox",
    "version": "0.1.0",
    "name": "MovieBox",
    "description": "Search and stream movies & TV series from MovieBox with subtitles",
    "resources": [
        {
            "name": "stream",
            "types": ["movie", "series"],
            "idPrefixes": ["tt"],
        },
        {
            "name": "subtitles",
            "types": ["movie", "series"],
            "idPrefixes": ["tt"],
        },
        "catalog",
    ],
    "types": ["movie", "series"],
    "catalogs": [
        {
            "type": "movie",
            "id": "moviebox_trending_movies",
            "name": "MovieBox Trending",
        },
        {
            "type": "series",
            "id": "moviebox_trending_series",
            "name": "MovieBox Trending Series",
        },
        {
            "type": "movie",
            "id": "moviebox_search_movies",
            "name": "MovieBox Search",
            "extra": [{"name": "search", "isRequired": True}],
        },
        {
            "type": "series",
            "id": "moviebox_search_series",
            "name": "MovieBox Search Series",
            "extra": [{"name": "search", "isRequired": True}],
        },
    ],
    "idPrefixes": ["tt"],
    "behaviorHints": {"configurable": False},
}
