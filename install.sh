#!/usr/bin/env bash

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

setup_shell_integration() {
    if [ "${MOVIEBOX_SKIP_SHELL_SETUP:-0}" = "1" ]; then
        warn "Skipping shell integration because MOVIEBOX_SKIP_SHELL_SETUP=1"
        return
    fi

    local shell_name
    local rc_file
    shell_name="$(basename "${SHELL:-}")"
    rc_file=""

    case "$shell_name" in
    bash) rc_file="${HOME}/.bashrc" ;;
    zsh) rc_file="${HOME}/.zshrc" ;;
    *)
        warn "Shell '${shell_name:-unknown}' is not auto-configured (supported: bash, zsh)"
        return
        ;;
    esac

    local marker
    marker="# >>> moviebox shell setup >>>"

    if [ -f "$rc_file" ] && grep -qF "$marker" "$rc_file"; then
        ok "Shell integration already exists in $rc_file"
        return
    fi

    touch "$rc_file"

    local escaped_root
    escaped_root="${SCRIPT_DIR//\"/\\\"}"

    if [ "$shell_name" = "bash" ]; then
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
    else
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
    fi

    ok "Added shell integration to $rc_file"
}

printf "${CYAN}Moviebox installer (Linux/macOS)${NC}\n\n"

step "Checking Python"
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    fail "Python 3.10+ is required but was not found in PATH"
fi

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
"$VENV_PYTHON" -m pip install -e ".[cli]"
ok "moviebox installed"

step "Configuring shell integration"
setup_shell_integration

step "Verifying CLI entrypoint"
"$MOVIEBOX_BIN" --help >/dev/null
ok "moviebox CLI is ready"

printf "\n${GREEN}Install complete.${NC}\n"
printf '%b\n' "- Run now: ${CYAN}source .venv/bin/activate && moviebox interactive-tui${NC}"
printf '%b\n' "- Legacy menu is still available: ${CYAN}moviebox interactive${NC}"
printf '%b\n' "- If shell setup was added, open a new terminal to enable auto-venv + completion."
printf '%b\n' "- Disable shell setup on rerun with: ${CYAN}MOVIEBOX_SKIP_SHELL_SETUP=1 ./install.sh${NC}"
