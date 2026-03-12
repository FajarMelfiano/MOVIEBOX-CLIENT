#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

step() {
    printf "${BLUE}[step]${NC} %s\n" "$1"
}

ok() {
    printf "${GREEN}[ok]${NC} %s\n" "$1"
}

warn() {
    printf "${YELLOW}[warn]${NC} %s\n" "$1"
}

fail() {
    printf "${RED}[error]${NC} %s\n" "$1"
    exit 1
}

SHELL_RC_FILE_USED="${HOME}/.bashrc"

setup_shell_integration() {
    if [ "${MOVIEBOX_SKIP_SHELL_SETUP:-0}" = "1" ]; then
        warn "Skipping shell integration because MOVIEBOX_SKIP_SHELL_SETUP=1"
        return
    fi

    local shell_name
    local rc_file
    local marker
    shell_name="$(basename "${SHELL:-}")"
    case "$shell_name" in
    zsh)
        rc_file="${HOME}/.zshrc"
        ;;
    bash | "")
        rc_file="${HOME}/.bashrc"
        ;;
    *)
        warn "Shell '${shell_name:-unknown}' not explicitly supported, using bash config"
        shell_name="bash"
        rc_file="${HOME}/.bashrc"
        ;;
    esac

    SHELL_RC_FILE_USED="$rc_file"
    marker="# >>> moviebox shell setup >>>"

    if [ -f "$rc_file" ] && grep -qF "$marker" "$rc_file"; then
        ok "Shell integration already exists in $rc_file"
        return
    fi

    touch "$rc_file"

    local escaped_root
    escaped_root="${SCRIPT_DIR//\"/\\\"}"

    if [ "$shell_name" = "zsh" ]; then
        cat >>"$rc_file" <<EOF

# >>> moviebox shell setup >>>
export MOVIEBOX_PROJECT_ROOT="$escaped_root"
_moviebox_repo_auto_venv() {
  local root="\${MOVIEBOX_PROJECT_ROOT:-}"
  if [[ -z "\$root" ]]; then
    return
  fi
  if [[ "\$PWD" == "\$root" || "\$PWD" == "\$root/"* ]]; then
    if [[ -z "\${VIRTUAL_ENV:-}" && -f "\$root/.venv/bin/activate" ]]; then
      source "\$root/.venv/bin/activate" >/dev/null 2>&1
      export MOVIEBOX_AUTO_VENV_ACTIVE=1
    fi
  else
    if [[ "\${MOVIEBOX_AUTO_VENV_ACTIVE:-0}" == "1" && -n "\${VIRTUAL_ENV:-}" ]]; then
      if type deactivate >/dev/null 2>&1; then
        deactivate >/dev/null 2>&1
      fi
      unset MOVIEBOX_AUTO_VENV_ACTIVE
    fi
  fi
}
if [[ -z "\${MOVIEBOX_AUTO_VENV_HOOKED:-}" ]]; then
  autoload -Uz add-zsh-hook
  add-zsh-hook precmd _moviebox_repo_auto_venv
  export MOVIEBOX_AUTO_VENV_HOOKED=1
fi
if [ -x "\${MOVIEBOX_PROJECT_ROOT}/.venv/bin/moviebox" ]; then
  if ! type compdef >/dev/null 2>&1; then
    autoload -Uz compinit
    compinit
  fi
  eval "\$(_MOVIEBOX_COMPLETE=zsh_source "\${MOVIEBOX_PROJECT_ROOT}/.venv/bin/moviebox")"
fi
# <<< moviebox shell setup <<<
EOF
    else
        cat >>"$rc_file" <<EOF

# >>> moviebox shell setup >>>
export MOVIEBOX_PROJECT_ROOT="$escaped_root"
_moviebox_repo_auto_venv() {
  local root="\${MOVIEBOX_PROJECT_ROOT:-}"
  if [ -z "\$root" ]; then
    return
  fi
  if [[ "\$PWD" == "\$root" || "\$PWD" == "\$root/"* ]]; then
    if [ -z "\${VIRTUAL_ENV:-}" ] && [ -f "\$root/.venv/bin/activate" ]; then
      . "\$root/.venv/bin/activate" >/dev/null 2>&1
      export MOVIEBOX_AUTO_VENV_ACTIVE=1
    fi
  else
    if [ "\${MOVIEBOX_AUTO_VENV_ACTIVE:-0}" = "1" ] && [ -n "\${VIRTUAL_ENV:-}" ]; then
      deactivate >/dev/null 2>&1 || true
      unset MOVIEBOX_AUTO_VENV_ACTIVE
    fi
  fi
}
case ";\${PROMPT_COMMAND:-};" in
  *";_moviebox_repo_auto_venv;"*) ;;
  *) PROMPT_COMMAND="_moviebox_repo_auto_venv;\${PROMPT_COMMAND:-}" ;;
esac
if [ -x "\${MOVIEBOX_PROJECT_ROOT}/.venv/bin/moviebox" ]; then
  eval "\$(_MOVIEBOX_COMPLETE=bash_source "\${MOVIEBOX_PROJECT_ROOT}/.venv/bin/moviebox")"
fi
# <<< moviebox shell setup <<<
EOF
    fi

    ok "Added auto-venv and completion to $rc_file"
}

printf "${CYAN}Moviebox installer (Termux)${NC}\n\n"

if ! command -v pkg >/dev/null 2>&1; then
    fail "This script must run inside Termux"
fi

step "Updating Termux package index"
ok "Termux package index update skipped"

step "Installing required system packages"
pkg install -y python git termux-api
ok "System packages installed"

step "Checking Python version"
PYTHON_BIN="python"
if ! "$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info[:2] < (3, 10):
    raise SystemExit(1)
PY
then
    fail "Python 3.10+ is required"
fi
ok "Using $($PYTHON_BIN --version 2>&1)"

step "Creating virtual environment"
if [ -d ".venv" ] && [ ! -x ".venv/bin/python" ] && [ ! -x ".venv/bin/python3" ]; then
    warn "Detected broken .venv, recreating"
    rm -rf .venv
fi

if [ -x ".venv/bin/python" ] || [ -x ".venv/bin/python3" ]; then
    ok "Reusing existing .venv"
else
    "$PYTHON_BIN" -m venv .venv
    ok "Created .venv"
fi

if [ -x "${SCRIPT_DIR}/.venv/bin/python" ]; then
    VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python"
elif [ -x "${SCRIPT_DIR}/.venv/bin/python3" ]; then
    VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python3"
else
    fail "Virtualenv creation failed: missing .venv/bin/python and .venv/bin/python3"
fi

MOVIEBOX_BIN="${SCRIPT_DIR}/.venv/bin/moviebox"

step "Upgrading pip"
if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
    warn "pip not available in .venv, bootstrapping with ensurepip"
    "$VENV_PYTHON" -m ensurepip --upgrade
fi
"$VENV_PYTHON" -m pip install --upgrade pip
ok "pip upgraded"

step "Installing moviebox with CLI extras"

printf "\n"
read -r -p "Do you want to install pydantic? (Slow build, but recommended) [y/N]: " install_pydantic
install_pydantic=${install_pydantic,,}

fallback_deps=(
    "bs4>=0.0.2"
    "click>=8.2.1"
    "httpx>=0.28.1"
    "rich>=14.1.0"
    "textual>=0.66.0"
    "throttlebuster>=0.1.11"
)

if [[ "$install_pydantic" =~ ^(yes|y)$ ]]; then
    if "$VENV_PYTHON" -m pip install -e ".[cli]"; then
        ok "moviebox installed via standard setup"
    else
        warn "Standard install failed, trying Termux compatibility fallback"
        fallback_deps+=("pydantic==2.9.2")
        "$VENV_PYTHON" -m pip install --no-deps -e .
        "$VENV_PYTHON" -m pip install "${fallback_deps[@]}"
        ok "moviebox and pydantic installed with fallback dependency set"
    fi
else
    warn "Pydantic installation skipped. Forcing fallback proxy."
    "$VENV_PYTHON" -m pip install --no-deps -e .
    "$VENV_PYTHON" -m pip install "${fallback_deps[@]}"
    ok "moviebox installed without pydantic"
fi

step "Configuring shell integration"
setup_shell_integration

step "Verifying CLI entrypoint"
"$MOVIEBOX_BIN" --help >/dev/null
ok "moviebox CLI is ready"

printf "\n${GREEN}Install complete.${NC}\n"
if [ "$SHELL_RC_FILE_USED" = "${HOME}/.zshrc" ]; then
    printf '%b\n' "- Open a new terminal (or run ${CYAN}source ~/.zshrc${NC}) to enable auto-venv + completion."
else
    printf '%b\n' "- Open a new terminal (or run ${CYAN}source ~/.bashrc${NC}) to enable auto-venv + completion."
fi
printf '%b\n' "- Run now: ${CYAN}moviebox interactive-tui${NC}"
printf '%b\n' "- Termux playback uses explicit player selection (MPV/MPVEX/VLC/MX) in Run page."
printf '%b\n' "- Optional player: ${CYAN}pkg install mpv${NC}"
printf '%b\n' "- Disable shell setup on rerun with: ${CYAN}MOVIEBOX_SKIP_SHELL_SETUP=1 ./install-termux.sh${NC}"
