# Moviebox Client

Unofficial Python client for searching, streaming, and downloading movies, TV episodes, or anime with subtitle support.

## What is included

- Interactive full-screen TUI (`moviebox interactive-tui`) with page flow:
  - `Home -> Search -> Source -> Subtitle -> Run`
- Legacy menu mode (`moviebox interactive`) for users who prefer prompt-based navigation.
- Provider-based stream resolution for movies/TV (`moviebox`, `yflix`, `vega`) and anime (`samehadaku`, `oplovers`, `otakudesu`).
- Subtitle source selection (`provider`, `opensubtitles`, `subdl`, `subsource`, `all`).
- Secret management for subtitle API keys (`secret-set`, `secret-status`, `secret-unset`).
- CLI audio fallback preference for downloads (`--audio`).
- Termux-aware playback with explicit player selector (MPV, MPVEX, VLC, MX Pro, MX Free).

## Quick install

### Linux / macOS

```bash
git clone https://github.com/FajarMelfiano/MOVIEBOX-CLIENT
cd MOVIEBOX-CLIENT
chmod +x install.sh
./install.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/FajarMelfiano/MOVIEBOX-CLIENT
cd MOVIEBOX-CLIENT
.\install.ps1
```

### Windows (CMD)

```cmd
git clone https://github.com/FajarMelfiano/MOVIEBOX-CLIENT
cd MOVIEBOX-CLIENT
install.bat
```

### Termux (Android)

```bash
pkg install git -y
git clone https://github.com/FajarMelfiano/MOVIEBOX-CLIENT
cd MOVIEBOX-CLIENT
chmod +x install-termux.sh
./install-termux.sh
```

Detailed platform notes are in `INSTALL.md`.

Manual dependency files are also available:

- `requirements.txt` for standard desktop/server installs
- `requirements-termux.txt` for Termux installs without `pydantic`

## Quick start

After install:

```bash
moviebox interactive-tui
```

If `moviebox` is not available in your current shell yet, activate `.venv` once:

```bash
source .venv/bin/activate
```

Legacy prompt menu:

```bash
moviebox interactive
```

## Common commands

### Download / stream

```bash
# Download a movie
moviebox download-movie "Interstellar" --quality 1080p

# Download a TV episode
moviebox download-series "Arcane" -s 1 -e 1

# Prefer a specific audio label in fallback streams
moviebox download-movie "Interstellar" --audio English

# Stream directly with a local player
moviebox download-movie "Interstellar" --stream-via mpv

# Resolve and stream anime episode metadata
moviebox source-anime "One Piece" -p samehadaku --json

# Download anime episode with Indonesian subtitle preference
moviebox download-anime "One Piece" -p samehadaku -e 1 -x Indonesian

# Stream anime directly to Android/desktop player targets
moviebox download-anime "Solo Leveling" -p oplovers -e 1 --stream-via vlc
```

### Provider resolution

```bash
# Resolve stream links with default provider
moviebox source-streams "Scream 7"

# Resolve with yflix
moviebox source-streams "Scream 7" -p yflix --json

# Inspect available Vega dynamic provider values
moviebox vega-providers

# Use dynamic Vega provider module
moviebox source-streams "Scream 7" -p "vega:autoEmbed" --json
```

### Subtitle API keys

```bash
# Save secret keys in local keyring
moviebox secret-set MOVIEBOX_SUBDL_API_KEY
moviebox secret-set MOVIEBOX_SUBSOURCE_API_KEY

# Check whether values come from env/keyring/none
moviebox secret-status

# Remove a stored secret
moviebox secret-unset MOVIEBOX_SUBDL_API_KEY
```

Environment variable mode is still supported:

```bash
export MOVIEBOX_SUBDL_API_KEY="<your-key>"
export MOVIEBOX_SUBSOURCE_API_KEY="<your-key>"
```

### Supabase subtitle proxy mode (public, no login)

This project now defaults to a hosted Supabase subtitle proxy endpoint for `subdl` and `subsource`.

You can override the endpoint with your own proxy URL:

```bash
export MOVIEBOX_SUBTITLE_PROXY_URL="https://<your-project>.supabase.co/functions/v1/subtitle-proxy"
# Optional if your function expects bearer/apikey token
export MOVIEBOX_SUBTITLE_PROXY_AUTH_TOKEN="<optional-token>"
```

If you need to disable proxy mode and use local keys instead:

```bash
export MOVIEBOX_SUBTITLE_PROXY_DISABLE=1
```

## Interactive TUI flow

`moviebox interactive-tui` currently supports:

- Home trending list from Cinemeta/Stremio catalog for Movies/TV and provider feeds for Anime.
- Search by subject type (Movies, TV Series, or Anime).
- TV season/episode dropdown selectors and anime episode selectors sourced from provider metadata.
- Source provider and stream selection.
- Subtitle source selection with full language names (not short code labels).
- Run page for stream/download actions and player target selection.
- Stream fallback for video/audio variants; subtitle-launch fallback if app extras are unsupported.
- TV and episodic-anime next episode flow with explicit confirmation (continue or stop).
- Movie/anime-movie run returns to Home after completion.

## Shell productivity

The install scripts can configure shell helpers automatically:

- Command completion for `moviebox`.
- Auto-activate `.venv` when entering this repository.
- Auto-deactivate the venv when leaving the repository.

To skip shell setup during install, use:

```bash
MOVIEBOX_SKIP_SHELL_SETUP=1 ./install.sh
```

PowerShell:

```powershell
$env:MOVIEBOX_SKIP_SHELL_SETUP='1'; .\install.ps1
```

Manual completion and auto-venv setup instructions are documented in `INSTALL.md`.

## Provider notes

- Supported movie/TV providers: `moviebox`, `yflix`, `vega`.
- Supported anime providers: `samehadaku`, `oplovers`, `otakudesu`.
- `nepu` and `tmdb_embed` are removed from active provider flow.
- `yflix` token generation requires `node` in `PATH`.
- Dynamic Vega modules execute remote provider logic; use trusted manifests only.
- Anime providers are Indonesian-first sources; provider subtitles default to Indonesian and automatically fall back to external subtitle APIs when provider subtitles are missing.
- Override anime source domains with environment variables when mirrors change: `MOVIEBOX_SAMEHADAKU_URLS`, `MOVIEBOX_OPLOVERS_URLS`, `MOVIEBOX_OPLOVERS_API_URLS`, `MOVIEBOX_OTAKUDESU_URLS`.

## Termux notes

- Install Termux from F-Droid for best compatibility.
- Playback defaults to MPV Android app in Termux mode, with detected fallback order.
- You can choose Android player from Run page (`MPV`, `MPVEX`, `VLC`, `MX Player Pro`, `MX Player Free`).
- Browser fallback is disabled in Termux external-player mode to avoid accidental auto-download.
- Set `MOVIEBOX_PLAYBACK_TARGET` to override defaults (`auto`, `android-mpv`, `mpvex`, `mx`, `vlc`, `mpv-cli`).
- External subtitle file auto-attach depends on per-player Android intent support.
- If terminal keyboard does not appear in Textual search input, use `Type (Termux)` button (uses `termux-dialog`).

## Development

```bash
# Run tests
.venv/bin/pytest

# Lint
.venv/bin/ruff check src tests
```

## License

Unlicense. See `LICENSE`.
