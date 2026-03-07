"""Dynamic provider adapter compatible with Vega provider bundles.

This adapter reads a remote provider manifest and executes selected provider
modules (posts/meta/stream/episodes) through a local Node.js runtime.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

from moviebox_api.constants import SubjectType
from moviebox_api.providers.base import BaseStreamProvider
from moviebox_api.providers.models import ProviderSearchResult, ProviderStream, ProviderSubtitle

ENV_VEGA_PROVIDER_KEY = "MOVIEBOX_VEGA_PROVIDER"
ENV_VEGA_MANIFEST_URL = "MOVIEBOX_VEGA_MANIFEST_URL"
ENV_VEGA_DIST_BASE_URL = "MOVIEBOX_VEGA_DIST_BASE_URL"
ENV_VEGA_MANIFEST_TTL_SECONDS = "MOVIEBOX_VEGA_MANIFEST_TTL_SECONDS"
ENV_VEGA_CACHE_DIR = "MOVIEBOX_VEGA_CACHE_DIR"
ENV_VEGA_ALLOW_DISABLED = "MOVIEBOX_VEGA_ALLOW_DISABLED"
ENV_VEGA_BOOTSTRAP_NODE_DEPS = "MOVIEBOX_VEGA_BOOTSTRAP_NODE_DEPS"
ENV_VEGA_NODE_MODULES_DIR = "MOVIEBOX_VEGA_NODE_MODULES_DIR"
ENV_VEGA_RUNTIME_TIMEOUT_SECONDS = "MOVIEBOX_VEGA_RUNTIME_TIMEOUT_SECONDS"

_DEFAULT_PROVIDER_VALUE = "autoEmbed"
_DEFAULT_MANIFEST_URL = "https://raw.githubusercontent.com/vega-org/vega-providers/main/manifest.json"
_DEFAULT_DIST_BASE_URL = "https://raw.githubusercontent.com/vega-org/vega-providers/main/dist"
_DEFAULT_MANIFEST_TTL_SECONDS = 3600
_DEFAULT_RUNTIME_TIMEOUT_SECONDS = 120
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "moviebox-api" / "vega"

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
}

_YEAR_PATTERN = re.compile(r"(19|20)\d{2}")
_TV_HINTS = (
    "season",
    "episode",
    "s01",
    "s02",
    "s03",
    "series",
    "tv",
)


def _to_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


class VegaProvider(BaseStreamProvider):
    """Dynamic stream provider powered by Vega provider bundles."""

    name = "vega"

    _manifest_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
    _module_cache: dict[tuple[str, str, str], str] = {}
    _runtime_setup_locks: dict[str, asyncio.Lock] = {}

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        provider_value: str | None = None,
    ):
        self._provider_value = (
            provider_value or os.getenv(ENV_VEGA_PROVIDER_KEY, _DEFAULT_PROVIDER_VALUE)
        ).strip()
        if not self._provider_value:
            self._provider_value = _DEFAULT_PROVIDER_VALUE

        self._manifest_url = os.getenv(ENV_VEGA_MANIFEST_URL, _DEFAULT_MANIFEST_URL).strip()
        self._dist_base_url = os.getenv(ENV_VEGA_DIST_BASE_URL, _DEFAULT_DIST_BASE_URL).strip().rstrip("/")
        self._manifest_ttl = self._safe_positive_int(
            os.getenv(ENV_VEGA_MANIFEST_TTL_SECONDS),
            default=_DEFAULT_MANIFEST_TTL_SECONDS,
        )
        self._runtime_timeout = self._safe_positive_int(
            os.getenv(ENV_VEGA_RUNTIME_TIMEOUT_SECONDS),
            default=_DEFAULT_RUNTIME_TIMEOUT_SECONDS,
        )
        self._allow_disabled = _to_bool(os.getenv(ENV_VEGA_ALLOW_DISABLED), default=False)
        self._bootstrap_node_deps = _to_bool(os.getenv(ENV_VEGA_BOOTSTRAP_NODE_DEPS), default=True)

        configured_cache_dir = os.getenv(ENV_VEGA_CACHE_DIR, "").strip()
        self._cache_dir = (
            Path(configured_cache_dir).expanduser() if configured_cache_dir else _DEFAULT_CACHE_DIR
        )
        self._runtime_script_path = self._cache_dir / "vega_runtime.js"

        configured_node_modules = os.getenv(ENV_VEGA_NODE_MODULES_DIR, "").strip()
        self._node_modules_dir = (
            Path(configured_node_modules).expanduser()
            if configured_node_modules
            else self._cache_dir / "node_modules"
        )

        self._client = client or httpx.AsyncClient(
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
        )

    @property
    def selected_provider_value(self) -> str:
        """Current Vega module value selected for this provider instance."""
        return self._provider_value

    async def list_available_providers(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        """List providers available from the remote Vega manifest."""
        manifest = await self._get_manifest()
        if include_disabled:
            return manifest
        return [item for item in manifest if not bool(item.get("disabled"))]

    async def search(
        self,
        query: str,
        subject_type: SubjectType,
        *,
        year: int | None = None,
        limit: int = 20,
    ) -> list[ProviderSearchResult]:
        provider_value = await self._resolve_manifest_provider_value(self._provider_value)
        modules = await self._get_provider_modules(provider_value)

        runtime_payload = {
            "operation": "search",
            "providerValue": provider_value,
            "query": query,
            "limit": limit,
            "modules": {
                "posts": modules["posts"],
            },
        }
        runtime_result = await self._run_runtime(runtime_payload)
        posts = runtime_result.get("posts") or []
        if not isinstance(posts, list):
            return []

        mapped: list[ProviderSearchResult] = []
        for index, post in enumerate(posts):
            if not isinstance(post, dict):
                continue

            title = self._to_str(post.get("title"))
            link = self._to_str(post.get("link"))
            if not title or not link:
                continue

            inferred_subject_type = self._infer_subject_type(subject_type, title)
            if subject_type is not SubjectType.ALL and inferred_subject_type is not subject_type:
                continue

            year_value = self._extract_year(title)
            if year and year_value and year_value != year:
                continue

            result_id = hashlib.sha1(
                f"{provider_value}|{link}|{index}".encode(), usedforsecurity=False
            ).hexdigest()
            mapped.append(
                ProviderSearchResult(
                    id=result_id,
                    title=title,
                    page_url=link,
                    subject_type=inferred_subject_type,
                    year=year_value,
                    payload={
                        "vega_provider": provider_value,
                        "source_link": link,
                        "post": post,
                    },
                )
            )

            if len(mapped) >= limit:
                break

        if year:
            exact_year = [entry for entry in mapped if entry.year == year]
            if exact_year:
                return exact_year

        return mapped

    async def resolve_streams(
        self,
        item: ProviderSearchResult,
        *,
        season: int = 0,
        episode: int = 0,
    ) -> list[ProviderStream]:
        provider_value = self._to_str(item.payload.get("vega_provider")) or self._provider_value
        provider_value = await self._resolve_manifest_provider_value(provider_value)
        modules = await self._get_provider_modules(provider_value)

        source_link = self._to_str(item.payload.get("source_link")) or item.page_url
        runtime_payload = {
            "operation": "resolve",
            "providerValue": provider_value,
            "season": season,
            "episode": episode,
            "item": {
                "title": item.title,
                "link": source_link,
                "subjectType": item.subject_type.name,
            },
            "modules": {
                "meta": modules["meta"],
                "stream": modules["stream"],
                "episodes": modules.get("episodes") or "",
            },
        }

        runtime_result = await self._run_runtime(runtime_payload)
        raw_streams = runtime_result.get("streams") or []
        if not isinstance(raw_streams, list):
            return []

        streams: list[ProviderStream] = []
        seen: set[str] = set()

        for raw_stream in raw_streams:
            if not isinstance(raw_stream, dict):
                continue

            stream_url = self._to_str(raw_stream.get("url"))
            if not stream_url:
                continue

            audio_label = self._to_str(raw_stream.get("audio"))
            audio_tracks = self._normalize_audio_tracks(raw_stream.get("audioTracks"))
            stream_identity = f"{stream_url}|{audio_label.lower()}|{'|'.join(audio_tracks).lower()}"
            if stream_identity in seen:
                continue
            seen.add(stream_identity)

            source = self._to_str(raw_stream.get("source")) or f"vega-{provider_value}"
            if audio_label:
                source = f"{source} [{audio_label}]"
            elif audio_tracks:
                source = f"{source} [{' / '.join(audio_tracks[:3])}]"
            quality = self._to_str(raw_stream.get("quality")) or None
            headers = self._normalize_headers(raw_stream.get("headers"))
            subtitles = self._normalize_subtitles(raw_stream.get("subtitles"))

            streams.append(
                ProviderStream(
                    url=stream_url,
                    source=source,
                    quality=quality,
                    subtitles=subtitles,
                    headers=headers,
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

    async def _resolve_manifest_provider_value(self, provider_value: str) -> str:
        manifest = await self._get_manifest()
        candidate = provider_value.strip().lower()

        for item in manifest:
            raw_value = self._to_str(item.get("value"))
            if raw_value.lower() != candidate:
                continue

            if bool(item.get("disabled")) and not self._allow_disabled:
                raise RuntimeError(
                    f"Vega provider '{raw_value}' is disabled in manifest. "
                    f"Set {ENV_VEGA_ALLOW_DISABLED}=1 to force it."
                )
            return raw_value

        available = ", ".join(self._to_str(entry.get("value")) for entry in manifest[:25])
        raise RuntimeError(
            f"Unknown Vega provider '{provider_value}'. "
            f"Use 'moviebox vega-providers' to inspect available values. Sample: {available}"
        )

    async def _get_manifest(self) -> list[dict[str, Any]]:
        cache_key = self._manifest_url
        now = time.time()
        cached = self._manifest_cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

        response = await self._client.get(self._manifest_url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Invalid Vega manifest payload from {self._manifest_url}")

        manifest_entries = [entry for entry in payload if isinstance(entry, dict) and entry.get("value")]
        self._manifest_cache[cache_key] = (now + self._manifest_ttl, manifest_entries)
        return manifest_entries

    async def _get_provider_modules(self, provider_value: str) -> dict[str, str]:
        modules: dict[str, str] = {}

        modules["posts"] = await self._fetch_provider_module(provider_value, "posts", required=True)
        modules["meta"] = await self._fetch_provider_module(provider_value, "meta", required=True)
        modules["stream"] = await self._fetch_provider_module(provider_value, "stream", required=True)
        modules["episodes"] = await self._fetch_provider_module(provider_value, "episodes", required=False)

        return modules

    async def _fetch_provider_module(self, provider_value: str, module_name: str, *, required: bool) -> str:
        cache_key = (self._dist_base_url, provider_value, module_name)
        if cache_key in self._module_cache:
            return self._module_cache[cache_key]

        module_url = f"{self._dist_base_url}/{provider_value}/{module_name}.js"
        response = await self._client.get(module_url)
        if response.status_code == 404 and not required:
            return ""

        response.raise_for_status()
        module_code = response.text
        self._module_cache[cache_key] = module_code
        return module_code

    async def _run_runtime(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_runtime_ready()

        if shutil.which("node") is None:
            raise RuntimeError("Node.js is required for vega dynamic provider runtime")

        env = dict(os.environ)
        existing_node_path = env.get("NODE_PATH", "")
        if existing_node_path:
            env["NODE_PATH"] = f"{self._node_modules_dir}:{existing_node_path}"
        else:
            env["NODE_PATH"] = str(self._node_modules_dir)

        process = await asyncio.create_subprocess_exec(
            "node",
            str(self._runtime_script_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdin_payload = json.dumps(payload).encode("utf-8")
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin_payload),
                timeout=self._runtime_timeout,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError(f"Vega runtime timed out after {self._runtime_timeout}s") from exc

        stdout_text = stdout.decode("utf-8", errors="ignore").strip()
        stderr_text = stderr.decode("utf-8", errors="ignore").strip()

        if process.returncode != 0:
            error_text = stderr_text or stdout_text or "unknown runtime error"
            raise RuntimeError(f"Vega runtime failed: {error_text}")

        try:
            result = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            error_text = stderr_text or stdout_text
            raise RuntimeError(f"Invalid Vega runtime JSON output: {error_text}") from exc

        if not isinstance(result, dict):
            raise RuntimeError("Vega runtime returned invalid payload")
        if not result.get("ok", False):
            raise RuntimeError(self._to_str(result.get("error")) or "Vega runtime reported failure")
        return result

    async def _ensure_runtime_ready(self) -> None:
        lock_key = str(self._cache_dir)
        lock = self._runtime_setup_locks.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            self._runtime_setup_locks[lock_key] = lock

        async with lock:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._runtime_script_path.write_text(_VEGA_RUNTIME_SCRIPT)

            has_axios = (self._node_modules_dir / "axios").exists()
            has_cheerio = (self._node_modules_dir / "cheerio").exists()
            if has_axios and has_cheerio:
                return

            if not self._bootstrap_node_deps:
                raise RuntimeError(
                    "Missing Node runtime dependencies (axios, cheerio). "
                    f"Enable auto bootstrap with {ENV_VEGA_BOOTSTRAP_NODE_DEPS}=1 "
                    "or install them manually in MOVIEBOX_VEGA_NODE_MODULES_DIR."
                )

            await self._bootstrap_node_dependencies()

    async def _bootstrap_node_dependencies(self) -> None:
        npm_path = shutil.which("npm")
        if not npm_path:
            raise RuntimeError("npm is required to bootstrap Vega runtime dependencies")

        self._cache_dir.mkdir(parents=True, exist_ok=True)

        process = await asyncio.create_subprocess_exec(
            npm_path,
            "install",
            "--no-audit",
            "--no-fund",
            "--silent",
            "--prefix",
            str(self._cache_dir),
            "axios@^1.7.9",
            "cheerio@^1.0.0",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            stdout_text = stdout.decode("utf-8", errors="ignore").strip()
            stderr_text = stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(
                "Failed to install Vega runtime dependencies via npm: "
                f"{stderr_text or stdout_text or 'unknown npm error'}"
            )

        has_axios = (self._node_modules_dir / "axios").exists()
        has_cheerio = (self._node_modules_dir / "cheerio").exists()
        if not (has_axios and has_cheerio):
            raise RuntimeError("npm install completed but axios/cheerio were not found in node_modules")

    @staticmethod
    def _infer_subject_type(requested: SubjectType, title: str) -> SubjectType:
        if requested is not SubjectType.ALL:
            return requested

        lowered = title.lower()
        if any(token in lowered for token in _TV_HINTS):
            return SubjectType.TV_SERIES
        return SubjectType.MOVIES

    @staticmethod
    def _extract_year(value: str) -> int | None:
        match = _YEAR_PATTERN.search(value)
        if not match:
            return None
        return int(match.group(0))

    @staticmethod
    def _normalize_headers(raw_headers: Any) -> dict[str, str]:
        if not isinstance(raw_headers, dict):
            return {}

        normalized: dict[str, str] = {}
        for key, value in raw_headers.items():
            string_key = VegaProvider._to_str(key)
            string_value = VegaProvider._to_str(value)
            if string_key and string_value:
                normalized[string_key] = string_value
        return normalized

    @staticmethod
    def _normalize_subtitles(raw_subtitles: Any) -> list[ProviderSubtitle]:
        if not isinstance(raw_subtitles, list):
            return []

        subtitles: list[ProviderSubtitle] = []
        seen: set[str] = set()

        for subtitle in raw_subtitles:
            if not isinstance(subtitle, dict):
                continue

            url = VegaProvider._to_str(subtitle.get("url")) or VegaProvider._to_str(subtitle.get("uri"))
            if not url or url in seen:
                continue
            seen.add(url)

            language = VegaProvider._to_str(subtitle.get("language")) or VegaProvider._to_str(
                subtitle.get("lang")
            )
            label = VegaProvider._to_str(subtitle.get("label")) or VegaProvider._to_str(subtitle.get("title"))

            subtitles.append(
                ProviderSubtitle(
                    url=url,
                    language=language or "unknown",
                    label=label or None,
                )
            )

        return subtitles

    @staticmethod
    def _normalize_audio_tracks(raw_tracks: Any) -> list[str]:
        if not isinstance(raw_tracks, list):
            return []

        tracks: list[str] = []
        for track in raw_tracks:
            if isinstance(track, dict):
                normalized = (
                    VegaProvider._to_str(track.get("label"))
                    or VegaProvider._to_str(track.get("name"))
                    or VegaProvider._to_str(track.get("language"))
                    or VegaProvider._to_str(track.get("lang"))
                    or VegaProvider._to_str(track.get("code"))
                )
            else:
                normalized = VegaProvider._to_str(track)

            if normalized and normalized not in tracks:
                tracks.append(normalized)
        return tracks

    @staticmethod
    def _to_str(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    @staticmethod
    def _safe_positive_int(value: str | None, *, default: int) -> int:
        if value is None:
            return default
        raw = value.strip()
        if not raw:
            return default
        try:
            parsed = int(raw)
        except ValueError:
            return default
        return parsed if parsed > 0 else default


_VEGA_RUNTIME_SCRIPT = r"""
'use strict';

const fs = require('node:fs');
const crypto = require('node:crypto');

const axios = require('axios');
const cheerio = require('cheerio');

function formatLogValue(value) {
  if (typeof value === 'string') {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch (_error) {
    return String(value);
  }
}

const runtimeConsole = {
  log: (...args) => {
    process.stderr.write(`[vega-runtime] ${args.map(formatLogValue).join(' ')}\n`);
  },
  error: (...args) => {
    process.stderr.write(`[vega-runtime:error] ${args.map(formatLogValue).join(' ')}\n`);
  },
  warn: (...args) => {
    process.stderr.write(`[vega-runtime:warn] ${args.map(formatLogValue).join(' ')}\n`);
  },
};

function base64Decode(value) {
  return Buffer.from(String(value), 'base64').toString('binary');
}

function base64Encode(value) {
  return Buffer.from(String(value), 'binary').toString('base64');
}

function createExecutionContext() {
  return {
    exports: {},
    module: { exports: {} },
    require: () => ({}),
    console: runtimeConsole,
    Promise,
    Object,
    process,
    fetch: globalThis.fetch,
    FormData: globalThis.FormData,
    atob: globalThis.atob || base64Decode,
    btoa: globalThis.btoa || base64Encode,
    __awaiter: (thisArg, _arguments, P, generator) => {
      function adopt(value) {
        return value instanceof P
          ? value
          : new P((resolve) => {
              resolve(value);
            });
      }

      return new (P || (P = Promise))((resolve, reject) => {
        function fulfilled(value) {
          try {
            step(generator.next(value));
          } catch (error) {
            reject(error);
          }
        }

        function rejected(value) {
          try {
            step(generator.throw(value));
          } catch (error) {
            reject(error);
          }
        }

        function step(result) {
          if (result.done) {
            resolve(result.value);
          } else {
            adopt(result.value).then(fulfilled, rejected);
          }
        }

        step((generator = generator.apply(thisArg, _arguments || [])).next());
      });
    },
  };
}

function executeModule(moduleCode) {
  const context = createExecutionContext();

  const executor = new Function(
    'context',
    `
      const exports = context.exports;
      const module = context.module;
      const require = context.require;
      const console = context.console;
      const Promise = context.Promise;
      const Object = context.Object;
      const process = context.process;
      const fetch = context.fetch;
      const FormData = context.FormData;
      const atob = context.atob;
      const btoa = context.btoa;
      const __awaiter = context.__awaiter;

      ${moduleCode}

      if (module && module.exports && Object.keys(module.exports).length > 0) {
        return module.exports;
      }
      return exports;
    `,
  );

  return executor(context);
}

let baseUrlConfigCache = null;

async function getBaseUrl(providerValue) {
  if (!baseUrlConfigCache) {
    const response = await fetch('https://himanshu8443.github.io/providers/modflix.json', {
      headers: {
        'User-Agent': 'Mozilla/5.0',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch base URL map: ${response.status}`);
    }

    baseUrlConfigCache = await response.json();
  }

  const entry = baseUrlConfigCache?.[providerValue];
  const value = typeof entry?.url === 'string' ? entry.url : '';
  if (!value) {
    throw new Error(`Missing base URL for provider '${providerValue}'`);
  }
  return value;
}

function createProviderContext() {
  return {
    axios,
    cheerio,
    getBaseUrl,
    commonHeaders: {
      'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Microsoft Edge";v="120"',
      'sec-ch-ua-mobile': '?0',
      'sec-ch-ua-platform': '"Windows"',
      'User-Agent':
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        + '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    },
    Crypto: {
      digestStringAsync: async (algorithm, value) => {
        const algo = String(algorithm || '').toLowerCase();
        const mapped = algo.includes('sha256') ? 'sha256' : 'sha1';
        return crypto.createHash(mapped).update(String(value)).digest('hex');
      },
    },
    extractors: {},
  };
}

function asString(value) {
  if (typeof value === 'string') {
    return value.trim();
  }
  if (value === null || value === undefined) {
    return '';
  }
  return String(value).trim();
}

function extractNumber(value) {
  const match = asString(value).match(/(\d{1,4})/);
  if (!match) {
    return null;
  }
  const parsed = Number.parseInt(match[1], 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeHeaders(rawHeaders) {
  if (!rawHeaders || typeof rawHeaders !== 'object' || Array.isArray(rawHeaders)) {
    return {};
  }

  const normalized = {};
  for (const [key, value] of Object.entries(rawHeaders)) {
    const normalizedKey = asString(key);
    const normalizedValue = asString(value);
    if (normalizedKey && normalizedValue) {
      normalized[normalizedKey] = normalizedValue;
    }
  }
  return normalized;
}

function normalizeSubtitles(rawSubtitles) {
  if (!Array.isArray(rawSubtitles)) {
    return [];
  }

  const subtitles = [];
  const seen = new Set();
  for (const subtitle of rawSubtitles) {
    if (!subtitle || typeof subtitle !== 'object') {
      continue;
    }

    const url = asString(subtitle.url || subtitle.uri || subtitle.link);
    if (!url || seen.has(url)) {
      continue;
    }
    seen.add(url);

    subtitles.push({
      url,
      language: asString(subtitle.language || subtitle.lang || subtitle.label || 'unknown') || 'unknown',
      label: asString(subtitle.label || subtitle.title || subtitle.lang) || null,
    });
  }

  return subtitles;
}

function normalizeAudioTracks(rawTracks) {
  if (!Array.isArray(rawTracks)) {
    return [];
  }

  const tracks = [];
  for (const track of rawTracks) {
    if (track && typeof track === 'object') {
      const normalized = asString(
        track.label || track.name || track.language || track.lang || track.code
      );
      if (normalized && !tracks.includes(normalized)) {
        tracks.push(normalized);
      }
      continue;
    }

    const normalized = asString(track);
    if (normalized && !tracks.includes(normalized)) {
      tracks.push(normalized);
    }
  }

  return tracks;
}

function normalizeStreams(rawStreams, providerValue) {
  if (!Array.isArray(rawStreams)) {
    return [];
  }

  const streams = [];
  const seen = new Set();

  for (const stream of rawStreams) {
    if (!stream || typeof stream !== 'object') {
      continue;
    }

    const url = asString(stream.link || stream.url);
    if (!url) {
      continue;
    }

    const audioTracks = normalizeAudioTracks(
      stream.audioTracks || stream.audio_tracks || stream.audios || stream.tracks?.audio
    );
    const audio = asString(
      stream.audio || stream.audioTrack || stream.language || stream.lang || stream.dub
    );
    const streamIdentity = `${url}|${audio.toLowerCase()}|${audioTracks.join('|').toLowerCase()}`;
    if (seen.has(streamIdentity)) {
      continue;
    }
    seen.add(streamIdentity);

    streams.push({
      url,
      source: asString(stream.server || stream.source) || `vega-${providerValue}`,
      quality: asString(stream.quality) || null,
      audio: audio || null,
      audioTracks,
      headers: normalizeHeaders(stream.headers),
      subtitles: normalizeSubtitles(stream.subtitles),
    });
  }

  return streams;
}

function chooseFromDirectLinks(directLinks, episode) {
  if (!Array.isArray(directLinks) || directLinks.length === 0) {
    return null;
  }

  if (episode > 0) {
    const byTitle = directLinks.find((entry) => extractNumber(entry?.title) === episode);
    if (byTitle) {
      return byTitle;
    }

    const index = episode - 1;
    if (index >= 0 && index < directLinks.length) {
      return directLinks[index];
    }
  }

  return directLinks[0];
}

async function pickSeriesLink({ linkList, season, episode, episodesModule, providerContext }) {
  if (!Array.isArray(linkList) || linkList.length === 0) {
    return null;
  }

  let seasonEntry = null;
  if (season > 0) {
    seasonEntry = linkList.find((entry) => extractNumber(entry?.title) === season) || null;
    if (!seasonEntry && season - 1 < linkList.length) {
      seasonEntry = linkList[season - 1];
    }
  }
  if (!seasonEntry) {
    seasonEntry = linkList[0];
  }

  const directPick = chooseFromDirectLinks(seasonEntry?.directLinks, episode);
  if (directPick?.link) {
    return {
      link: asString(directPick.link),
      type: asString(directPick.type) || 'series',
    };
  }

  const episodesUrl = asString(seasonEntry?.episodesLink);
  if (!episodesUrl || !episodesModule || typeof episodesModule.getEpisodes !== 'function') {
    return null;
  }

  const episodes = await episodesModule.getEpisodes({
    url: episodesUrl,
    providerContext,
  });

  if (!Array.isArray(episodes) || episodes.length === 0) {
    return null;
  }

  let selectedEpisode = null;
  if (episode > 0) {
    selectedEpisode = episodes.find((entry) => extractNumber(entry?.title) === episode) || null;
    if (!selectedEpisode && episode - 1 < episodes.length) {
      selectedEpisode = episodes[episode - 1];
    }
  }
  if (!selectedEpisode) {
    selectedEpisode = episodes[0];
  }

  const episodeLink = asString(selectedEpisode?.link);
  if (!episodeLink) {
    return null;
  }

  return {
    link: episodeLink,
    type: 'series',
  };
}

async function pickStreamInput({ item, meta, season, episode, episodesModule, providerContext }) {
  const fallbackLink = asString(item?.link);
  const requestedType = asString(item?.subjectType).toUpperCase() === 'TV_SERIES' ? 'series' : 'movie';
  const metaType = asString(meta?.type).toLowerCase() || requestedType;
  const linkList = Array.isArray(meta?.linkList) ? meta.linkList : [];

  if (metaType === 'series' || requestedType === 'series') {
    const pickedSeries = await pickSeriesLink({
      linkList,
      season,
      episode,
      episodesModule,
      providerContext,
    });
    if (pickedSeries?.link) {
      return pickedSeries;
    }
  } else {
    const firstLinkList = linkList[0];
    const directPick = chooseFromDirectLinks(firstLinkList?.directLinks, 0);
    if (directPick?.link) {
      return {
        link: asString(directPick.link),
        type: asString(directPick.type) || 'movie',
      };
    }
  }

  const firstLinkList = linkList[0];
  const listLink = asString(firstLinkList?.link || firstLinkList?.episodesLink);
  if (listLink) {
    return {
      link: listLink,
      type: metaType || requestedType,
    };
  }

  return {
    link: fallbackLink,
    type: metaType || requestedType,
  };
}

async function runSearch(input, providerContext) {
  const postsModuleCode = asString(input?.modules?.posts);
  if (!postsModuleCode) {
    throw new Error('Missing posts module code');
  }

  const postsModule = executeModule(postsModuleCode);
  if (typeof postsModule?.getSearchPosts !== 'function') {
    throw new Error('posts module does not export getSearchPosts');
  }

  const controller = new AbortController();
  const posts = await postsModule.getSearchPosts({
    searchQuery: asString(input.query),
    page: 1,
    providerValue: asString(input.providerValue),
    signal: controller.signal,
    providerContext,
  });

  if (!Array.isArray(posts)) {
    return [];
  }

  const limit = Number.isFinite(Number(input.limit)) ? Number(input.limit) : 20;
  return posts
    .slice(0, Math.max(1, limit))
    .map((post) => ({
      title: asString(post?.title),
      link: asString(post?.link),
      image: asString(post?.image),
    }))
    .filter((post) => post.title && post.link);
}

async function runResolve(input, providerContext) {
  const metaModuleCode = asString(input?.modules?.meta);
  const streamModuleCode = asString(input?.modules?.stream);
  const episodesModuleCode = asString(input?.modules?.episodes);
  if (!metaModuleCode) {
    throw new Error('Missing meta module code');
  }
  if (!streamModuleCode) {
    throw new Error('Missing stream module code');
  }

  const metaModule = executeModule(metaModuleCode);
  const streamModule = executeModule(streamModuleCode);
  const episodesModule = episodesModuleCode ? executeModule(episodesModuleCode) : null;

  if (typeof metaModule?.getMeta !== 'function') {
    throw new Error('meta module does not export getMeta');
  }
  if (typeof streamModule?.getStream !== 'function') {
    throw new Error('stream module does not export getStream');
  }

  const item = input?.item || {};
  const sourceLink = asString(item?.link);
  if (!sourceLink) {
    throw new Error('Missing source link for resolve');
  }

  const meta = await metaModule.getMeta({
    link: sourceLink,
    provider: asString(input.providerValue),
    providerContext,
  });

  const season = Number.parseInt(String(input.season || 0), 10) || 0;
  const episode = Number.parseInt(String(input.episode || 0), 10) || 0;
  const streamInput = await pickStreamInput({
    item,
    meta,
    season,
    episode,
    episodesModule,
    providerContext,
  });

  if (!asString(streamInput?.link)) {
    throw new Error('Unable to select a stream link from provider metadata');
  }

  const controller = new AbortController();
  const rawStreams = await streamModule.getStream({
    link: asString(streamInput.link),
    type: asString(streamInput.type) || 'movie',
    signal: controller.signal,
    providerValue: asString(input.providerValue),
    providerContext,
  });

  return {
    selectedLink: asString(streamInput.link),
    streamType: asString(streamInput.type) || 'movie',
    meta: {
      title: asString(meta?.title),
      type: asString(meta?.type),
      imdbId: asString(meta?.imdbId),
    },
    streams: normalizeStreams(rawStreams, asString(input.providerValue)),
  };
}

async function main() {
  const rawInput = fs.readFileSync(0, 'utf8').trim();
  const input = rawInput ? JSON.parse(rawInput) : {};
  const operation = asString(input.operation);
  const providerContext = createProviderContext();

  if (operation === 'search') {
    const posts = await runSearch(input, providerContext);
    process.stdout.write(JSON.stringify({ ok: true, posts }));
    return;
  }

  if (operation === 'resolve') {
    const result = await runResolve(input, providerContext);
    process.stdout.write(JSON.stringify({ ok: true, ...result }));
    return;
  }

  throw new Error(`Unsupported operation '${operation}'`);
}

main().catch((error) => {
  const message = error && error.message ? error.message : String(error);
  process.stdout.write(JSON.stringify({ ok: false, error: message }));
  process.exit(1);
});
"""
