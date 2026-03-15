# Installation Guide

This guide covers installation for Linux, macOS, Windows, and Termux.

## Requirements

- Python 3.10 or newer
- Git
- Optional for streaming: `mpv` or `vlc`

## 1) Quick install scripts

### Linux / macOS

```bash
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
chmod +x install.sh
./install.sh
```

Run:

```bash
moviebox interactive-tui
```

### Windows PowerShell (recommended)

```powershell
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
.\install.ps1
```

Run:

```powershell
moviebox interactive-tui
```

### Windows CMD

```cmd
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
install.bat
```

Run:

```cmd
.venv\Scripts\activate.bat
moviebox interactive-tui
```

### Termux (Android)

```bash
pkg install git -y
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
chmod +x install-termux.sh
./install-termux.sh
```

Run:

```bash
moviebox interactive-tui
```

Note:

- Installer also installs `termux-api` so TUI can open native text dialog (`Type (Termux)`) when keyboard focus is limited.
- Termux install intentionally skips `pydantic` and uses the compatibility layer in `src/moviebox_api/pydantic_compat.py`.

## 2) What installers configure

All installers:

- Create or reuse `.venv`
- Upgrade `pip`
- Install project dependencies for the target platform (desktop CLI extras or Termux compatibility requirements)
- Verify `moviebox` entrypoint in `.venv`

Shell integration (automatic by default):

- `install.sh`: bash/zsh auto-venv + completion
- `install-termux.sh`: bash/zsh auto-venv + completion
- `install.ps1`: PowerShell profile auto-venv + completion
- `install.bat`: no shell profile changes (use PowerShell installer for that)

To skip shell integration:

Linux/macOS/Termux:

```bash
MOVIEBOX_SKIP_SHELL_SETUP=1 ./install.sh
```

PowerShell:

```powershell
$env:MOVIEBOX_SKIP_SHELL_SETUP='1'; .\install.ps1
```

## 3) Manual install (all platforms)

```bash
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
python -m venv .venv
```

Activate:

Linux/macOS/Termux:

```bash
source .venv/bin/activate
```

Windows CMD:

```cmd
.venv\Scripts\activate.bat
```

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install:

Linux/macOS/Windows:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

Termux:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-termux.txt
python -m pip install --no-deps -e .
```

## 4) Autocompletion setup (manual)

### Bash

```bash
echo 'eval "$(_MOVIEBOX_COMPLETE=bash_source moviebox)"' >> ~/.bashrc
source ~/.bashrc
```

### Zsh

```zsh
echo 'eval "$(_MOVIEBOX_COMPLETE=zsh_source moviebox)"' >> ~/.zshrc
source ~/.zshrc
```

### Fish

```fish
mkdir -p ~/.config/fish/completions
_MOVIEBOX_COMPLETE=fish_source moviebox > ~/.config/fish/completions/moviebox.fish
```

### PowerShell

```powershell
if (-not (Test-Path $PROFILE)) {
  New-Item -Type File -Path $PROFILE -Force | Out-Null
}
Add-Content $PROFILE @'
if (Get-Command moviebox -ErrorAction SilentlyContinue) {
  (& { $env:_MOVIEBOX_COMPLETE = "powershell_source"; moviebox }) | Out-String | Invoke-Expression
  Remove-Item Env:_MOVIEBOX_COMPLETE -ErrorAction SilentlyContinue
}
'@
```

## 5) Auto-activate `.venv` on entering repo (manual)

The installers can do this automatically. If you skipped that step, add one of the snippets below.

### Bash

Add to `~/.bashrc` (replace path):

```bash
export MOVIEBOX_PROJECT_ROOT="/absolute/path/to/moviebox-api"
_moviebox_repo_auto_venv() {
  local root="${MOVIEBOX_PROJECT_ROOT:-}"
  if [[ "$PWD" == "$root" || "$PWD" == "$root/"* ]]; then
    if [ -z "${VIRTUAL_ENV:-}" ] && [ -f "$root/.venv/bin/activate" ]; then
      . "$root/.venv/bin/activate"
      export MOVIEBOX_AUTO_VENV_ACTIVE=1
    fi
  else
    if [ "${MOVIEBOX_AUTO_VENV_ACTIVE:-0}" = "1" ] && [ -n "${VIRTUAL_ENV:-}" ]; then
      deactivate >/dev/null 2>&1 || true
      unset MOVIEBOX_AUTO_VENV_ACTIVE
    fi
  fi
}
case ";${PROMPT_COMMAND:-};" in
  *";_moviebox_repo_auto_venv;"*) ;;
  *) PROMPT_COMMAND="_moviebox_repo_auto_venv;${PROMPT_COMMAND:-}" ;;
esac
```

### Zsh

Add to `~/.zshrc` (replace path):

```zsh
export MOVIEBOX_PROJECT_ROOT="/absolute/path/to/moviebox-api"
_moviebox_repo_auto_venv() {
  local root="${MOVIEBOX_PROJECT_ROOT:-}"
  if [[ "$PWD" == "$root" || "$PWD" == "$root/"* ]]; then
    if [[ -z "${VIRTUAL_ENV:-}" && -f "$root/.venv/bin/activate" ]]; then
      source "$root/.venv/bin/activate"
      export MOVIEBOX_AUTO_VENV_ACTIVE=1
    fi
  else
    if [[ "${MOVIEBOX_AUTO_VENV_ACTIVE:-0}" == "1" && -n "${VIRTUAL_ENV:-}" ]]; then
      deactivate
      unset MOVIEBOX_AUTO_VENV_ACTIVE
    fi
  fi
}
autoload -Uz add-zsh-hook
add-zsh-hook precmd _moviebox_repo_auto_venv
```

### PowerShell

`install.ps1` writes this automatically to your profile. Re-run it if needed.

## 6) Troubleshooting

### Python not found

Install Python 3.10+ and ensure it is in `PATH`.

### PowerShell execution policy blocks script

Run in PowerShell:

```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Termux package issues

```bash
pkg update -y
pkg upgrade -y
```

### Stream playback issues

- Install `mpv` or `vlc`.
- On Termux, Run page detects installed Android players (`MPV`, `MX`, `VLC`) and lets you pick one.
- Termux external-player mode does not fall back to browser (prevents accidental auto-download behavior).
- Set `MOVIEBOX_PLAYBACK_TARGET` to override startup default:
  - `auto` (recommended)
  - `android-mpv`
  - `mpvex`
  - `mx`
  - `vlc`
  - `mpv-cli` (terminal mpv)

### TV next episode behavior

- Stream mode now asks confirmation before moving to the next episode.
- Subtitle language preference is persisted across episode continuation.
- Subtitle language table uses full language names for readability.

### Subtitle API key setup

```bash
moviebox secret-set MOVIEBOX_SUBDL_API_KEY
moviebox secret-set MOVIEBOX_SUBSOURCE_API_KEY
moviebox secret-status
```

### Subtitle proxy mode (Supabase)

- `subdl` and `subsource` default to a hosted Supabase proxy endpoint in this project.
- Override proxy endpoint (or point to your own project):

```bash
export MOVIEBOX_SUBTITLE_PROXY_URL="https://<your-project>.supabase.co/functions/v1/subtitle-proxy"
export MOVIEBOX_SUBTITLE_PROXY_AUTH_TOKEN="<optional-token>"
```

- Disable proxy mode and use local API keys only:

```bash
export MOVIEBOX_SUBTITLE_PROXY_DISABLE=1
```
