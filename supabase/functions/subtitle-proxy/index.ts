import "jsr:@supabase/functions-js/edge-runtime.d.ts";

type SubtitleSource = "opensubtitles" | "subdl" | "subsource";

type ProxySubtitle = {
  url: string;
  language: string;
  label: string;
  source: SubtitleSource;
};

type SourceError = {
  source: SubtitleSource | "subtitle-proxy";
  message: string;
};

const OPEN_SUBTITLES_URL = "https://opensubtitles-v3.strem.io";
const SUBDL_BASE_URL = "https://subdl.strem.top";
const SUBSOURCE_BASE_URL = "https://subsource.strem.top";
const SUBDL_VALIDATION_URL = "https://api.subdl.com/api/v1/subtitles";
const HEARING_MODE = "hiInclude";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-forwarded-for",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Content-Type": "application/json",
};

const DEFAULT_HEADERS: HeadersInit = {
  "User-Agent":
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
  Accept: "application/json",
  "Accept-Language": "en-US,en;q=0.5",
};

const SUBDL_KEY_VALIDATION_CACHE = new Map<string, boolean | null>();
const SUBSOURCE_KEY_VALIDATION_CACHE = new Map<string, boolean | null>();

const REQUEST_BUCKET = new Map<string, number[]>();
const RATE_LIMIT_WINDOW_MS = Math.max(
  5000,
  Number.parseInt(Deno.env.get("SUBTITLE_PROXY_RATE_LIMIT_WINDOW_MS") ?? "60000", 10) || 60000,
);
const RATE_LIMIT_MAX_REQUESTS = Math.max(
  1,
  Number.parseInt(Deno.env.get("SUBTITLE_PROXY_RATE_LIMIT_MAX") ?? "60", 10) || 60,
);

const LANGUAGE_ALIASES: Record<string, string> = {
  english: "en",
  eng: "en",
  en: "en",
  indonesian: "id",
  ind: "id",
  id: "id",
  bahasa: "id",
  spanish: "es",
  spa: "es",
  es: "es",
  french: "fr",
  fre: "fr",
  fra: "fr",
  fr: "fr",
  german: "de",
  ger: "de",
  deu: "de",
  de: "de",
  italian: "it",
  ita: "it",
  it: "it",
  portuguese: "pt",
  por: "pt",
  pt: "pt",
  russian: "ru",
  rus: "ru",
  ru: "ru",
  arabic: "ar",
  ara: "ar",
  ar: "ar",
  turkish: "tr",
  tur: "tr",
  tr: "tr",
  japanese: "ja",
  jpn: "ja",
  ja: "ja",
  korean: "ko",
  kor: "ko",
  ko: "ko",
  chinese: "zh",
  zho: "zh",
  chi: "zh",
  zh: "zh",
  vietnamese: "vi",
  vie: "vi",
  vi: "vi",
  thai: "th",
  tha: "th",
  th: "th",
  dutch: "nl",
  dut: "nl",
  nld: "nl",
  nl: "nl",
  polish: "pl",
  pol: "pl",
  pl: "pl",
  romanian: "ro",
  rum: "ro",
  ron: "ro",
  ro: "ro",
  persian: "fa",
  farsi: "fa",
  per: "fa",
  fas: "fa",
  fa: "fa",
  hindi: "hi",
  hin: "hi",
  hi: "hi",
  malay: "ms",
  msa: "ms",
  may: "ms",
  ms: "ms",
  tagalog: "tl",
  filipino: "tl",
  tgl: "tl",
  tl: "tl",
  ukrainian: "uk",
  ukr: "uk",
  uk: "uk",
};

const ISO6391_TO_SUBSOURCE_LANGUAGE: Record<string, string> = {
  en: "english",
  id: "indonesian",
  es: "spanish",
  fr: "french",
  de: "german",
  it: "italian",
  pt: "portuguese",
  ru: "russian",
  ar: "arabic",
  tr: "turkish",
  ja: "japanese",
  ko: "korean",
  zh: "chinese",
  vi: "vietnamese",
  th: "thai",
  nl: "dutch",
  pl: "polish",
  ro: "romanian",
  fa: "persian",
  hi: "hindi",
  ms: "malay",
  tl: "tagalog",
  uk: "ukrainian",
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: CORS_HEADERS,
  });
}

function normalizeContentType(input: unknown): "movie" | "series" | null {
  const value = String(input ?? "").trim().toLowerCase();
  if (value === "movie") return "movie";
  if (value === "series") return "series";
  return null;
}

function normalizeLanguageCode(input: unknown): string {
  const raw = String(input ?? "").trim().toLowerCase();
  if (!raw) return "unknown";

  if (LANGUAGE_ALIASES[raw]) {
    return LANGUAGE_ALIASES[raw];
  }

  const compact = raw.replace(/[^a-z]/g, "");
  if (!compact) return "unknown";

  if (LANGUAGE_ALIASES[compact]) {
    return LANGUAGE_ALIASES[compact];
  }

  if (compact.length === 2) return compact;
  return compact.slice(0, 3);
}

function preferredLanguageCodes(input: unknown): string[] {
  const values: string[] = [];
  if (Array.isArray(input)) {
    for (const item of input) {
      const code = normalizeLanguageCode(item);
      if (code === "unknown") continue;
      if (!values.includes(code)) values.push(code);
    }
  }

  if (values.length === 0) {
    values.push("en", "id");
  }

  for (const fallback of ["en", "id"]) {
    if (!values.includes(fallback)) values.push(fallback);
  }

  return values.slice(0, 3);
}

function normalizeSubsourceLanguage(input: unknown): string | null {
  const code = normalizeLanguageCode(input);
  if (code === "unknown") {
    return null;
  }

  return ISO6391_TO_SUBSOURCE_LANGUAGE[code] ?? code;
}

function preferredSubsourceLanguages(input: unknown): string[] {
  const values: string[] = [];
  if (Array.isArray(input)) {
    for (const item of input) {
      const language = normalizeSubsourceLanguage(item);
      if (!language) continue;
      if (!values.includes(language)) values.push(language);
    }
  }

  if (values.length === 0) {
    values.push("english", "indonesian");
  }

  for (const fallback of ["english", "indonesian"]) {
    if (!values.includes(fallback)) values.push(fallback);
  }

  return values.slice(0, 3);
}

function normalizeSources(input: unknown): SubtitleSource[] {
  const allowed = new Set<SubtitleSource>(["opensubtitles", "subdl", "subsource"]);
  const normalized: SubtitleSource[] = [];

  if (!Array.isArray(input)) {
    return ["subdl", "subsource"];
  }

  for (const source of input) {
    const value = String(source ?? "").trim().toLowerCase() as SubtitleSource;
    if (!allowed.has(value)) continue;
    if (!normalized.includes(value)) normalized.push(value);
  }

  if (normalized.length === 0) {
    return ["subdl", "subsource"];
  }

  return normalized;
}

function base64Encode(value: string): string {
  return btoa(value);
}

function buildSubdlConfigPath(apiKey: string, languageCodes: string[]): string {
  const raw = `${apiKey}/${languageCodes.join(",")}/${HEARING_MODE}/`;
  return base64Encode(raw);
}

function buildSubsourceConfigPath(apiKey: string, languageCodes: string[]): string {
  const raw = `${apiKey}/${languageCodes.join(",")}/${HEARING_MODE}/type:0/`;
  return base64Encode(raw);
}

function mapSubtitleEntry(entry: Record<string, unknown>, source: SubtitleSource): ProxySubtitle | null {
  const url = String(entry.url ?? "").trim();
  if (!url.startsWith("http://") && !url.startsWith("https://")) {
    return null;
  }

  const language = normalizeLanguageCode(entry.lang);
  const subtitleId = String(entry.id ?? "").trim();
  const label = subtitleId || language;

  return {
    url,
    language,
    label,
    source,
  };
}

function looksLikeErrorEntry(entry: Record<string, unknown>): boolean {
  const subtitleId = String(entry.id ?? "").toLowerCase();
  const subtitleUrl = String(entry.url ?? "").toLowerCase();
  return subtitleId.startsWith("error_") || subtitleUrl.includes("/error-subtitle/");
}

async function fetchJson(url: string): Promise<Record<string, unknown>> {
  const response = await fetch(url, {
    method: "GET",
    headers: DEFAULT_HEADERS,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const payload = await response.json();
  if (!payload || typeof payload !== "object") {
    return {};
  }

  return payload as Record<string, unknown>;
}

async function validateSubdlKey(apiKey: string): Promise<boolean | null> {
  if (SUBDL_KEY_VALIDATION_CACHE.has(apiKey)) {
    return SUBDL_KEY_VALIDATION_CACHE.get(apiKey) ?? null;
  }

  try {
    const url = new URL(SUBDL_VALIDATION_URL);
    url.searchParams.set("api_key", apiKey);
    url.searchParams.set("film_name", "Inception");
    const response = await fetch(url.toString(), { headers: DEFAULT_HEADERS });
    if (!response.ok) {
      SUBDL_KEY_VALIDATION_CACHE.set(apiKey, null);
      return null;
    }

    const payload = await response.json();
    const valid = Boolean(payload && typeof payload === "object" && payload.status === true);
    SUBDL_KEY_VALIDATION_CACHE.set(apiKey, valid);
    return valid;
  } catch {
    SUBDL_KEY_VALIDATION_CACHE.set(apiKey, null);
    return null;
  }
}

async function validateSubsourceKey(apiKey: string): Promise<boolean | null> {
  if (SUBSOURCE_KEY_VALIDATION_CACHE.has(apiKey)) {
    return SUBSOURCE_KEY_VALIDATION_CACHE.get(apiKey) ?? null;
  }

  try {
    const response = await fetch(`${SUBSOURCE_BASE_URL}/api/validate-api-key`, {
      method: "POST",
      headers: {
        ...DEFAULT_HEADERS,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ apiKey }),
    });

    if (!response.ok) {
      SUBSOURCE_KEY_VALIDATION_CACHE.set(apiKey, null);
      return null;
    }

    const payload = await response.json();
    const valid = Boolean(payload && typeof payload === "object" && payload.valid === true);
    SUBSOURCE_KEY_VALIDATION_CACHE.set(apiKey, valid);
    return valid;
  } catch {
    SUBSOURCE_KEY_VALIDATION_CACHE.set(apiKey, null);
    return null;
  }
}

async function fetchOpenSubtitles(videoId: string, contentType: "movie" | "series"): Promise<ProxySubtitle[]> {
  const payload = await fetchJson(`${OPEN_SUBTITLES_URL}/subtitles/${contentType}/${videoId}.json`);
  const rawSubtitles = payload.subtitles;
  if (!Array.isArray(rawSubtitles)) return [];

  const results: ProxySubtitle[] = [];
  for (const item of rawSubtitles) {
    if (!item || typeof item !== "object") continue;
    const mapped = mapSubtitleEntry(item as Record<string, unknown>, "opensubtitles");
    if (mapped) results.push(mapped);
  }
  return results;
}

async function fetchSubdl(
  videoId: string,
  contentType: "movie" | "series",
  languageCodes: string[],
): Promise<{ subtitles: ProxySubtitle[]; error?: string }> {
  const apiKey = (Deno.env.get("SUBDL_API_KEY") ?? "").trim();
  if (!apiKey) {
    return { subtitles: [], error: "SubDL key is not configured" };
  }

  const keyValidation = await validateSubdlKey(apiKey);
  if (keyValidation === false) {
    return { subtitles: [], error: "SubDL API key is invalid or expired" };
  }

  try {
    const configPath = buildSubdlConfigPath(apiKey, languageCodes);
    const url = `${SUBDL_BASE_URL}/${configPath}/subtitles/${contentType}/${videoId}.json`;
    const payload = await fetchJson(url);
    const rawSubtitles = payload.subtitles;
    if (!Array.isArray(rawSubtitles)) {
      return { subtitles: [] };
    }

    const subtitles: ProxySubtitle[] = [];
    for (const item of rawSubtitles) {
      if (!item || typeof item !== "object") continue;
      if (looksLikeErrorEntry(item as Record<string, unknown>)) continue;
      const mapped = mapSubtitleEntry(item as Record<string, unknown>, "subdl");
      if (mapped) subtitles.push(mapped);
    }

    if (subtitles.length === 0 && keyValidation === null) {
      return {
        subtitles: [],
        error:
          "SubDL returned no subtitles and key validation could not be verified. Check network access to api.subdl.com.",
      };
    }

    return { subtitles };
  } catch (error) {
    return { subtitles: [], error: `SubDL request failed: ${String(error)}` };
  }
}

async function fetchSubsource(
  videoId: string,
  contentType: "movie" | "series",
  languageCodes: string[],
): Promise<{ subtitles: ProxySubtitle[]; error?: string }> {
  const apiKey = (Deno.env.get("SUBSOURCE_API_KEY") ?? "").trim();
  if (!apiKey) {
    return { subtitles: [], error: "SubSource key is not configured" };
  }

  const keyValidation = await validateSubsourceKey(apiKey);
  if (keyValidation === false) {
    return { subtitles: [], error: "SubSource API key is invalid or expired" };
  }

  try {
    const configPath = buildSubsourceConfigPath(apiKey, languageCodes);
    const url = `${SUBSOURCE_BASE_URL}/${configPath}/subtitles/${contentType}/${videoId}.json`;
    const payload = await fetchJson(url);
    const rawSubtitles = payload.subtitles;
    if (!Array.isArray(rawSubtitles)) {
      return { subtitles: [] };
    }

    const subtitles: ProxySubtitle[] = [];
    for (const item of rawSubtitles) {
      if (!item || typeof item !== "object") continue;
      if (looksLikeErrorEntry(item as Record<string, unknown>)) continue;
      const mapped = mapSubtitleEntry(item as Record<string, unknown>, "subsource");
      if (mapped) subtitles.push(mapped);
    }

    if (subtitles.length === 0 && keyValidation === null) {
      return {
        subtitles: [],
        error:
          "SubSource returned no subtitles and key validation could not be verified. Check network access to subsource.strem.top.",
      };
    }

    return { subtitles };
  } catch (error) {
    return { subtitles: [], error: `SubSource request failed: ${String(error)}` };
  }
}

function getClientIp(req: Request): string {
  const forwardedFor = req.headers.get("x-forwarded-for") ?? "";
  if (forwardedFor) {
    return forwardedFor.split(",")[0].trim() || "unknown";
  }
  return "unknown";
}

function isRateLimited(clientIp: string): boolean {
  const now = Date.now();
  const entries = REQUEST_BUCKET.get(clientIp) ?? [];
  const freshEntries = entries.filter((timestamp) => timestamp >= now - RATE_LIMIT_WINDOW_MS);

  if (freshEntries.length >= RATE_LIMIT_MAX_REQUESTS) {
    REQUEST_BUCKET.set(clientIp, freshEntries);
    return true;
  }

  freshEntries.push(now);
  REQUEST_BUCKET.set(clientIp, freshEntries);
  return false;
}

function isAuthorized(req: Request): boolean {
  const configuredToken = (Deno.env.get("SUBTITLE_PROXY_AUTH_TOKEN") ?? "").trim();
  if (!configuredToken) {
    return true;
  }

  const bearer = (req.headers.get("authorization") ?? "").trim();
  if (bearer.toLowerCase().startsWith("bearer ")) {
    if (bearer.slice(7).trim() === configuredToken) return true;
  }

  const apiKey = (req.headers.get("apikey") ?? "").trim();
  return apiKey === configuredToken;
}

function dedupeSubtitles(subtitles: ProxySubtitle[]): ProxySubtitle[] {
  const map = new Map<string, ProxySubtitle>();
  for (const subtitle of subtitles) {
    map.set(subtitle.url, subtitle);
  }
  return [...map.values()];
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers: CORS_HEADERS });
  }

  if (req.method !== "POST") {
    return jsonResponse({ error: "Method not allowed" }, 405);
  }

  if (!isAuthorized(req)) {
    return jsonResponse({ error: "Unauthorized" }, 401);
  }

  const clientIp = getClientIp(req);
  if (isRateLimited(clientIp)) {
    return jsonResponse({ error: "Too many requests" }, 429);
  }

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return jsonResponse({ error: "Invalid JSON body" }, 400);
  }

  const videoId = String(body.video_id ?? "").trim();
  if (!videoId) {
    return jsonResponse({ error: "video_id is required" }, 400);
  }

  const contentType = normalizeContentType(body.content_type);
  if (!contentType) {
    return jsonResponse({ error: "content_type must be 'movie' or 'series'" }, 400);
  }

  const sources = normalizeSources(body.sources);
  const languageCodes = preferredLanguageCodes(body.preferred_languages);
  const subsourceLanguages = preferredSubsourceLanguages(body.preferred_languages);

  const subtitles: ProxySubtitle[] = [];
  const errors: SourceError[] = [];

  for (const source of sources) {
    if (source === "opensubtitles") {
      try {
        const fetched = await fetchOpenSubtitles(videoId, contentType);
        subtitles.push(...fetched);
      } catch (error) {
        errors.push({ source, message: String(error) });
      }
      continue;
    }

    if (source === "subdl") {
      const fetched = await fetchSubdl(videoId, contentType, languageCodes);
      subtitles.push(...fetched.subtitles);
      if (fetched.error) {
        errors.push({ source, message: fetched.error });
      }
      continue;
    }

    const fetched = await fetchSubsource(videoId, contentType, subsourceLanguages);
    subtitles.push(...fetched.subtitles);
    if (fetched.error) {
      errors.push({ source, message: fetched.error });
    }
  }

  const deduped = dedupeSubtitles(subtitles);
  return jsonResponse({
    subtitles: deduped,
    errors,
    meta: {
      video_id: videoId,
      content_type: contentType,
      sources,
      preferred_languages: languageCodes,
      subsource_languages: subsourceLanguages,
      subtitle_count: deduped.length,
    },
  });
});
