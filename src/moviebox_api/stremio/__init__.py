"""Stremio addon integration for moviebox-api.

Serves moviebox content via the Stremio addon protocol,
allowing Stremio to discover and stream movies/series from MovieBox.
"""

from moviebox_api.stremio.manifest import MANIFEST


def run_server(*args, **kwargs):
    from moviebox_api.stremio.server import run_server as _run_server

    return _run_server(*args, **kwargs)


__all__ = ["MANIFEST", "run_server"]
