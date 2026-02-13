"""FastAPI HTTP server for the Stremio addon.

Serves the addon protocol endpoints with CORS support and a
streaming proxy for moviebox CDN URLs that require auth headers.

Endpoints:
- GET /manifest.json
- GET /catalog/{type}/{id}.json
- GET /catalog/{type}/{id}/{extra}.json
- GET /stream/{type}/{id}.json
- GET /subtitles/{type}/{id}.json
- GET /proxy/media/{encoded_url}     — streaming video proxy
- GET /proxy/subtitle/{encoded_url}  — subtitle proxy

Usage:
    moviebox-stremio              # CLI entry point
    python -m moviebox_api.stremio  # Module entry point
"""

import base64
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, unquote

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from moviebox_api.constants import DOWNLOAD_REQUEST_HEADERS
from moviebox_api.stremio.handlers import (
    handle_catalog,
    handle_stream,
    handle_subtitles,
)
from moviebox_api.stremio.manifest import MANIFEST

logger = logging.getLogger(__name__)

# Server host/port — set during startup, used by handlers to build proxy URLs
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 7000

# Global HTTP client for proxy requests
http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle (startup/shutdown)."""
    global http_client
    logger.info("Initializing HTTP client for proxy...")
    # Optimize client for streaming:
    # - limits: increase connection pool
    # - timeout: generous for slow streams
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=40)
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, read=300.0),
        limits=limits,
        follow_redirects=True,
    )
    yield
    logger.info("Closing HTTP client...")
    await http_client.aclose()


app = FastAPI(
    title="MovieBox Stremio Addon",
    description="Stremio addon for streaming movies & series from MovieBox",
    version=MANIFEST["version"],
    lifespan=lifespan,
)

# CORS is mandatory for Stremio addons
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Type"],
)


def get_server_base_url() -> str:
    """Return the base URL of this addon server."""
    return f"http://{SERVER_HOST}:{SERVER_PORT}"


def encode_url(url: str) -> str:
    """Base64-encode a URL for use in proxy path."""
    return base64.urlsafe_b64encode(url.encode()).decode()


def decode_url(encoded: str) -> str:
    """Decode a base64-encoded URL from proxy path."""
    # Add padding if needed
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    return base64.urlsafe_b64decode(encoded.encode()).decode()


# ---- Stremio addon protocol endpoints ----

@app.get("/manifest.json")
async def get_manifest():
    """Return the addon manifest."""
    return JSONResponse(content=MANIFEST)


@app.get("/catalog/{content_type}/{catalog_id}.json")
async def get_catalog(content_type: str, catalog_id: str):
    """Return catalog items (trending or search results)."""
    result = await handle_catalog(content_type, catalog_id)
    return JSONResponse(content=result)


@app.get("/catalog/{content_type}/{catalog_id}/{extra}.json")
async def get_catalog_with_extra(content_type: str, catalog_id: str, extra: str):
    """Return catalog items with extra args (e.g. search query)."""
    extra_args = {}
    if extra:
        decoded = unquote(extra)
        parsed = parse_qs(decoded)
        extra_args = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

    result = await handle_catalog(content_type, catalog_id, extra_args)
    return JSONResponse(content=result)


@app.get("/stream/{content_type}/{video_id}.json")
async def get_stream(content_type: str, video_id: str):
    """Return available streams for a video."""
    result = await handle_stream(content_type, video_id)
    return JSONResponse(content=result)


@app.get("/subtitles/{content_type}/{video_id}.json")
async def get_subtitles(content_type: str, video_id: str):
    """Return available subtitles for a video."""
    result = await handle_subtitles(content_type, video_id)
    return JSONResponse(content=result)


# ---- Streaming proxy endpoints ----
# Moviebox CDN requires Referer/User-Agent headers.
# This proxy fetches content with correct headers and streams it to Stremio.

CDN_HEADERS = {
    "User-Agent": DOWNLOAD_REQUEST_HEADERS["User-Agent"],
    "Referer": DOWNLOAD_REQUEST_HEADERS["Referer"],
    "Accept": "*/*",
    "Connection": "keep-alive",
}


@app.api_route("/proxy/media/{encoded_url:path}", methods=["GET", "HEAD"])
async def proxy_media(encoded_url: str, request: Request):
    """Stream video content from moviebox CDN with correct auth headers.

    Supports HTTP Range requests for video seeking.
    Optimized for high throughput with larger chunk sizes.
    """
    try:
        target_url = decode_url(encoded_url)
    except Exception:
        return Response(status_code=400, content="Invalid encoded URL")

    # Forward Range header from client for seeking support
    headers = dict(CDN_HEADERS)
    range_header = request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header

    try:
        # Use global client
        if not http_client:
            return Response(status_code=500, content="Server starting up or shutting down")

        # Stream the request
        req = http_client.build_request("GET", target_url, headers=headers)
        response = await http_client.send(req, stream=True)

        # Build response headers
        resp_headers = {
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
            "X-Proxy-Status": "Optimized-MovieBox",
        }
        if response.headers.get("Content-Type"):
            resp_headers["Content-Type"] = response.headers["Content-Type"]
        if response.headers.get("Content-Length"):
            resp_headers["Content-Length"] = response.headers["Content-Length"]
        if response.headers.get("Content-Range"):
            resp_headers["Content-Range"] = response.headers["Content-Range"]

        status_code = response.status_code  # 200 or 206 for partial content

        if request.method == "HEAD":
            await response.aclose()
            return Response(status_code=status_code, headers=resp_headers)

        async def stream_content():
            try:
                # Optimized chunk size: 1MB (was 64KB)
                # Reduces context switching overhead for high-bitrate video
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                    yield chunk
            finally:
                await response.aclose()
                # DO NOT close global client here

        return StreamingResponse(
            stream_content(),
            status_code=status_code,
            headers=resp_headers,
        )

    except Exception as e:
        logger.error(f"Proxy media error: {e}")
        return Response(status_code=502, content=f"Proxy error: {e}")


@app.api_route("/proxy/subtitle/{encoded_url:path}", methods=["GET", "HEAD"])
async def proxy_subtitle(encoded_url: str, request: Request):
    """Proxy subtitle file from moviebox CDN with correct auth headers."""
    try:
        target_url = decode_url(encoded_url)
    except Exception:
        return Response(status_code=400, content="Invalid encoded URL")

    logger.info(f"Proxy subtitle request: {target_url[:80]}...")

    try:
        if not http_client:
            return Response(status_code=500, content="Server starting up or shutting down")

        response = await http_client.get(target_url, headers=CDN_HEADERS)
        
        if request.method == "HEAD":
            return Response(
                status_code=response.status_code,
                headers={"Access-Control-Allow-Origin": "*"},
            )
            
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "application/x-subrip")
        return Response(
            content=response.content,
            media_type=content_type,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception as e:
        logger.error(f"Proxy subtitle error: {e}")
        return Response(status_code=502, content=f"Proxy error: {e}")


# ---- Server startup ----

def run_server(host: str = "0.0.0.0", port: int = 7000):
    """Start the Stremio addon server."""
    global SERVER_HOST, SERVER_PORT
    import uvicorn

    logging.basicConfig(
        format="[%(asctime)s] %(levelname)s - %(name)s - %(message)s",
        datefmt="%H:%M:%S",
        level=logging.INFO,
    )

    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = port

    logger.info(f"Starting MovieBox Stremio addon on http://{host}:{port}")
    logger.info(f"Install in Stremio: http://127.0.0.1:{port}/manifest.json")

    # Ensure clean shutdown on Ctrl+C
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    """CLI entry point for moviebox-stremio."""
    global SERVER_HOST, SERVER_PORT
    host = os.getenv("MOVIEBOX_STREMIO_HOST", "0.0.0.0")
    port = int(os.getenv("MOVIEBOX_STREMIO_PORT", "7000"))
    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = port
    run_server(host=host, port=port)


if __name__ == "__main__":
    main()
