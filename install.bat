@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo Moviebox installer (Windows CMD)
echo.

echo [step] Checking Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [error] Python 3.10+ is required. Install from https://www.python.org/downloads/
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PY_VERSION=%%v"
echo [ok] Using Python %PY_VERSION%

echo [step] Creating virtual environment
if exist ".venv\Scripts\python.exe" (
    echo [ok] Reusing existing .venv
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo [error] Failed to create .venv
        exit /b 1
    )
    echo [ok] Created .venv
)

set "VENV_PY=.venv\Scripts\python.exe"
set "MOVIEBOX_EXE=.venv\Scripts\moviebox.exe"

echo [step] Upgrading pip
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
    echo [error] Failed to upgrade pip
    exit /b 1
)
echo [ok] pip upgraded

echo [step] Installing moviebox with CLI extras
"%VENV_PY%" -m pip install -e ".[cli]"
if errorlevel 1 (
    echo [error] Installation failed
    exit /b 1
)
echo [ok] moviebox installed

echo [step] Verifying CLI entrypoint
"%MOVIEBOX_EXE%" --help >nul 2>&1
if errorlevel 1 (
    echo [error] moviebox executable check failed
    exit /b 1
)
echo [ok] moviebox CLI is ready

echo.
echo Install complete.
echo - Run now: .venv\Scripts\activate.bat ^&^& moviebox interactive-tui
echo - Legacy menu is still available: moviebox interactive
echo - For auto-venv and completion setup on Windows, use install.ps1 in PowerShell.

exit /b 0
