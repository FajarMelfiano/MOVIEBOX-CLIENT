# Supabase Edge Functions

## subtitle-proxy

Public subtitle proxy for `subdl` and `subsource` requests used by Moviebox clients.

### Required production secrets

Set these in Supabase Dashboard -> Project Settings -> Edge Functions -> Secrets:

- `SUBDL_API_KEY`
- `SUBSOURCE_API_KEY`

Optional:

- `SUBTITLE_PROXY_AUTH_TOKEN` (if set, callers must send bearer token/apikey)
- `SUBTITLE_PROXY_RATE_LIMIT_MAX` (default: `60` per window)
- `SUBTITLE_PROXY_RATE_LIMIT_WINDOW_MS` (default: `60000`)

### Request body

```json
{
  "video_id": "tt0816692",
  "content_type": "movie",
  "sources": ["subdl", "subsource"],
  "preferred_languages": ["en", "id"]
}
```

### Response body

```json
{
  "subtitles": [
    {
      "url": "https://...",
      "language": "en",
      "label": "English",
      "source": "subdl"
    }
  ],
  "errors": [
    {
      "source": "subsource",
      "message": "SubSource API key is invalid or expired"
    }
  ],
  "meta": {
    "video_id": "tt0816692",
    "content_type": "movie",
    "sources": ["subdl", "subsource"],
    "preferred_languages": ["en", "id"],
    "subtitle_count": 1
  }
}
```
