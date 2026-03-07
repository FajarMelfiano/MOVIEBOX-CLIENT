# Moviebox Client

Unofficial Python client for searching, streaming, and downloading movies or TV episodes with subtitle support.

## What is included

- Interactive full-screen TUI (`moviebox interactive-tui`) with page flow:
  - `Home -> Search -> Source -> Subtitle -> Run`
- Legacy menu mode (`moviebox interactive`) for users who prefer prompt-based navigation.
- Provider-based stream resolution (`moviebox`, `yflix`, `vega`).
- Subtitle source selection (`provider`, `opensubtitles`, `subdl`, `subsource`, `all`).
- Secret management for subtitle API keys (`secret-set`, `secret-status`, `secret-unset`).
- CLI audio fallback preference for downloads (`--audio`).
- Termux-aware playback defaults (Android app chooser via `termux-open-url`).

## Quick install

### Linux / macOS

```bash
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
chmod +x install.sh
./install.sh
```

### Windows (PowerShell)

```powershell
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
.\install.ps1
```

### Windows (CMD)

```cmd
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
install.bat
```

### Termux (Android)

```bash
pkg install git -y
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
chmod +x install-termux.sh
./install-termux.sh
```

Detailed platform notes are in `INSTALL.md`.

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

## Interactive TUI flow

`moviebox interactive-tui` currently supports:

- Home trending list from Cinemeta/Stremio catalog.
- Search by subject type (Movies or TV Series).
- TV season/episode dropdown selectors.
- Source provider and stream selection.
- Subtitle source and language-id filtering.
- Run page for stream/download actions.
- TV auto-next episode behavior in stream mode (desktop players).
- Movie run returns to Home after completion.

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

- Supported providers: `moviebox`, `yflix`, `vega`.
- `nepu` and `tmdb_embed` are removed from active provider flow.
- `yflix` token generation requires `node` in `PATH`.
- Dynamic Vega modules execute remote provider logic; use trusted manifests only.

## Termux notes

- Install Termux from F-Droid for best compatibility.
- Playback defaults to Android chooser (`termux-open-url`) in Termux mode.
- External subtitle file auto-attach depends on Android player support.

## Development

```bash
# Run tests
.venv/bin/pytest

# Lint
.venv/bin/ruff check src tests
```

## License

Unlicense. See `LICENSE`.
