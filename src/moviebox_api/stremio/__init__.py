"""Stremio addon integration for moviebox-api.

Serves moviebox content via the Stremio addon protocol,
allowing Stremio to discover and stream movies/series from MovieBox.
"""

from moviebox_api.stremio.manifest import MANIFEST
from moviebox_api.stremio.server import run_server

__all__ = ["MANIFEST", "run_server"]
