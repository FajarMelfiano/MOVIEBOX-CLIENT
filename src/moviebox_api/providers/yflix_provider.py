"""yflix.to provider adapter.

This provider uses yflix's public AJAX endpoints and reproduces the same
request token/signature transformation used by the website's frontend bundle.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from moviebox_api.constants import SubjectType
from moviebox_api.providers.base import BaseStreamProvider
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle

_YFLIX_BASE_URL = "https://yflix.to"
_WATCH_SCRIPT_PATTERN = re.compile(r"/assets/build/.+?/scripts-[\w-]+\.js(?:\?[^\"']*)?")
_DATA_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]{6,}$")

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.5",
}


class YflixProvider(BaseStreamProvider):
    """Stream provider for yflix.to."""

    name = "yflix"

    _codec_script_path: Path | None = None
    _codec_script_key: str | None = None

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
        )

    async def search(
        self,
        query: str,
        subject_type: SubjectType,
        *,
        year: int | None = None,
        limit: int = 20,
    ) -> list[ProviderSearchResult]:
        response = await self._client.get(
            f"{_YFLIX_BASE_URL}/ajax/film/search",
            params={"keyword": query},
            headers={
                "Referer": f"{_YFLIX_BASE_URL}/home",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )
        response.raise_for_status()

        payload = response.json()
        html = (payload.get("result") or {}).get("html") or ""
        soup = BeautifulSoup(html, "html.parser")

        items: list[ProviderSearchResult] = []
        for entry in soup.select("a.item[href]"):
            href = entry.get("href")
            if not href:
                continue

            title_node = entry.select_one(".title")
            title = title_node.get_text(strip=True) if title_node else ""
            if not title:
                continue

            metadata_spans = entry.select(".metadata span")
            type_text = metadata_spans[0].get_text(strip=True).lower() if metadata_spans else "movie"
            year_value: int | None = None
            if len(metadata_spans) > 1:
                raw_year = metadata_spans[1].get_text(strip=True)
                if raw_year.isdigit():
                    year_value = int(raw_year)

            inferred_subject_type = (
                SubjectType.TV_SERIES
                if any(token in type_text for token in ("series", "tv", "show"))
                else SubjectType.MOVIES
            )

            if subject_type is not SubjectType.ALL and inferred_subject_type is not subject_type:
                continue

            full_url = urljoin(_YFLIX_BASE_URL, href)
            items.append(
                ProviderSearchResult(
                    id=href,
                    title=title,
                    page_url=full_url,
                    subject_type=inferred_subject_type,
                    year=year_value,
                )
            )

        if year:
            filtered = [entry for entry in items if entry.year == year]
            if filtered:
                items = filtered

        return items[:limit]

    async def resolve_streams(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderStream]:
        page_response = await self._client.get(item.page_url)
        page_response.raise_for_status()

        await self._ensure_codec(page_response.text)
        page_soup = BeautifulSoup(page_response.text, "html.parser")
        item_id = self._extract_item_id(page_soup)
        if not item_id:
            return []

        item_signature = self._codec_encode(item_id)
        episodes_response = await self._ajax_get(
            item.page_url,
            "/ajax/episodes/list",
            params={"id": item_id, "_": item_signature},
        )
        episodes_html = episodes_response.get("result") or ""
        episode_id = self._extract_episode_id(episodes_html, season=season, episode=episode)
        if not episode_id:
            return []

        episode_signature = self._codec_encode(episode_id)
        links_response = await self._ajax_get(
            item.page_url,
            "/ajax/links/list",
            params={"eid": episode_id, "_": episode_signature},
        )
        links_html = links_response.get("result") or ""
        servers = self._extract_servers(links_html)
        if not servers:
            return []

        streams: list[ProviderStream] = []
        seen_urls: set[str] = set()

        for server in servers:
            server_signature = self._codec_encode(server["lid"])
            view_response = await self._ajax_get(
                item.page_url,
                "/ajax/links/view",
                params={"id": server["lid"], "_": server_signature},
            )
            encoded = view_response.get("result") or ""
            if not encoded:
                continue

            decoded = self._codec_decode(encoded)
            stream_url = self._extract_stream_url(decoded)
            if not stream_url or stream_url in seen_urls:
                continue

            seen_urls.add(stream_url)
            subtitles = self._extract_subtitles_from_url(stream_url)
            streams.append(
                ProviderStream(
                    url=stream_url,
                    source=f"yflix-server-{server['sid']}",
                    subtitles=subtitles,
                )
            )

        return streams

    async def resolve_subtitles(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderSubtitle]:
        streams = await self.resolve_streams(item, season=season, episode=episode)
        dedup: dict[str, ProviderSubtitle] = {}
        for stream in streams:
            for subtitle in stream.subtitles:
                dedup[subtitle.url] = subtitle
        return list(dedup.values())

    async def _ajax_get(self, referer_url: str, path: str, *, params: dict[str, str]) -> dict:
        response = await self._client.get(
            urljoin(_YFLIX_BASE_URL, path),
            params=params,
            headers={
                "Referer": referer_url,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "ok":
            raise RuntimeError(f"yflix ajax request failed for {path}: {payload}")
        return payload

    @classmethod
    async def _ensure_codec(cls, watch_page_html: str) -> None:
        script_url = cls._extract_watch_script_url(watch_page_html)
        if not script_url:
            raise RuntimeError("Unable to locate yflix frontend script URL")

        cache_key = script_url
        if cls._codec_script_path and cls._codec_script_key == cache_key and cls._codec_script_path.exists():
            return

        async with httpx.AsyncClient(headers=_DEFAULT_HEADERS, follow_redirects=True, timeout=30.0) as client:
            script_response = await client.get(script_url)
            script_response.raise_for_status()
            script_text = script_response.text

        codec_script = cls._build_codec_script(script_text)
        script_path = Path(tempfile.gettempdir()) / "moviebox_yflix_codec.js"
        script_path.write_text(codec_script)

        cls._codec_script_path = script_path
        cls._codec_script_key = cache_key

    @staticmethod
    def _extract_watch_script_url(html: str) -> str | None:
        match = _WATCH_SCRIPT_PATTERN.search(html)
        if not match:
            return None
        return urljoin(_YFLIX_BASE_URL, match.group(0))

    @classmethod
    def _build_codec_script(cls, script_text: str) -> str:
        vm_a_fn = cls._extract_function(script_text, "vmA")
        vm_g_fn = cls._extract_function(script_text, "vmG")

        rotate_start = script_text.find("(function(A0,A1){")
        rotate_end = script_text.find(",!function(A0)", rotate_start)
        if rotate_start < 0 or rotate_end < 0:
            raise RuntimeError("Failed to extract yflix vmA rotation bootstrap")
        rotation_snippet = script_text[rotate_start:rotate_end] + ");"

        s_closure_start = script_text.find("S=(function(){")
        t_object_marker = script_text.find(",T={'G':S[0x0]", s_closure_start)
        if s_closure_start < 0 or t_object_marker < 0:
            raise RuntimeError("Failed to extract yflix codec closure")

        s_expression = script_text[s_closure_start + 2 : t_object_marker]
        s_expression = cls._patch_at_function(s_expression)

        return (
            f"{vm_a_fn}\n"
            f"{vm_g_fn}\n"
            "var vmD4 = vmG;\n"
            f"{rotation_snippet}\n"
            f"var S = {s_expression};\n"
            "var T = {'G': S[0], 'W': S[1], 'Y': S[2], 'K': S[3]};\n"
            "const mode = process.argv[2];\n"
            "const value = process.argv[3] || '';\n"
            "if (mode === 'enc') { console.log(T.Y(value)); process.exit(0); }\n"
            "if (mode === 'dec') { console.log(T.K(value)); process.exit(0); }\n"
            "process.exit(2);\n"
        )

    @classmethod
    def _patch_at_function(cls, expression: str) -> str:
        at_index = expression.find("function AT()")
        if at_index < 0:
            raise RuntimeError("Failed to locate yflix AT() function in codec closure")

        body_start = expression.find("{", at_index)
        body_end = cls._find_matching_brace(expression, body_start)

        return expression[:at_index] + "function AT(){return true;}" + expression[body_end + 1 :]

    @classmethod
    def _extract_function(cls, source: str, name: str) -> str:
        start = source.find(f"function {name}")
        if start < 0:
            raise RuntimeError(f"Unable to locate function {name} in yflix script")

        body_start = source.find("{", start)
        body_end = cls._find_matching_brace(source, body_start)
        return source[start : body_end + 1]

    @staticmethod
    def _find_matching_brace(text: str, start: int) -> int:
        depth = 0
        in_string: str | None = None
        escaped = False

        for index in range(start, len(text)):
            char = text[index]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == in_string:
                    in_string = None
                continue

            if char in ('"', "'", "`"):
                in_string = char
                continue

            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index

        raise RuntimeError("Failed to match closing brace")

    @classmethod
    def _run_codec(cls, mode: str, value: str) -> str:
        if cls._codec_script_path is None:
            raise RuntimeError("yflix codec script is not initialized")

        try:
            output = subprocess.check_output(
                ["node", str(cls._codec_script_path), mode, value],
                text=True,
                timeout=20,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Node.js is required for yflix provider token generation") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Failed to run yflix codec script: {exc.output}") from exc

        return output.strip()

    @classmethod
    def _codec_encode(cls, value: str) -> str:
        return cls._run_codec("enc", value)

    @classmethod
    def _codec_decode(cls, value: str) -> str:
        return cls._run_codec("dec", value)

    @staticmethod
    def _extract_item_id(soup: BeautifulSoup) -> str | None:
        target = soup.select_one(".rating[data-id]") or soup.select_one(".user-bookmark[data-id]")
        if target and target.get("data-id"):
            return target.get("data-id")

        for element in soup.select("[data-id]"):
            candidate = (element.get("data-id") or "").strip()
            if candidate in {"search-md", "request"}:
                continue
            if _DATA_ID_PATTERN.match(candidate):
                return candidate

        return None

    @staticmethod
    def _extract_episode_id(episodes_html: str, *, season: int, episode: int) -> str | None:
        soup = BeautifulSoup(episodes_html, "html.parser")

        selected_anchor = None
        if season > 0 and episode > 0:
            target_season = soup.select_one(f'ul.episodes[data-season="{season}"]')
            if target_season:
                selected_anchor = target_season.select_one(f'a[num="{episode}"]')

        if selected_anchor is None and episode > 0:
            selected_anchor = soup.select_one(f'a[num="{episode}"]')

        if selected_anchor is None:
            selected_anchor = soup.select_one("ul.episodes a")

        if selected_anchor is None:
            return None

        return selected_anchor.get("eid")

    @staticmethod
    def _extract_servers(links_html: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(links_html, "html.parser")
        servers: list[dict[str, str]] = []

        for item in soup.select("li.server[data-lid]"):
            lid = item.get("data-lid")
            sid = item.get("data-sid") or "0"
            if not lid:
                continue
            servers.append({"lid": lid, "sid": sid})

        return servers

    @staticmethod
    def _extract_stream_url(decoded_result: str) -> str | None:
        if not decoded_result:
            return None

        try:
            payload = json.loads(decoded_result)
            if isinstance(payload, dict) and isinstance(payload.get("url"), str):
                return payload["url"]
        except json.JSONDecodeError:
            pass

        soup = BeautifulSoup(decoded_result, "html.parser")
        iframe = soup.select_one("iframe[src]")
        if iframe and iframe.get("src"):
            return iframe.get("src")

        source = soup.select_one("source[src]")
        if source and source.get("src"):
            return source.get("src")

        match = re.search(r"https?://[^\s\"'<>]+", decoded_result)
        return match.group(0) if match else None

    @staticmethod
    def _extract_subtitles_from_url(stream_url: str) -> list[ProviderSubtitle]:
        parsed = urlparse(stream_url)
        params = parse_qs(parsed.query)

        subtitles: list[ProviderSubtitle] = []
        sub_list = params.get("sub.list", [None])[0]
        if sub_list:
            subtitles.append(
                ProviderSubtitle(
                    url=unquote(sub_list),
                    language="unknown",
                    label="sub.list",
                )
            )

        return subtitles
