@echo off
REM Moviebox Enhanced - Windows CMD Installation Script
REM Enhanced TUI with streamlined UX and animation search

echo.
echo ╔══════════════════════════════════════════╗
echo ║                                          ║
echo ║  🎬 MOVIEBOX ENHANCED - INSTALLER        ║
echo ║                                          ║
echo ╚══════════════════════════════════════════╝
echo.

REM Check Python
echo [1/6] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python not found!
    echo.
    echo Please install Python 3.9+ from:
    echo   https://www.python.org/downloads/
    echo.
    echo Make sure to check 'Add Python to PATH' during installation!
    pause
    exit /b 1
)
echo ✓ Python found
echo.

REM Check pip
echo [2/6] Checking pip...
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠ pip not found, installing...
    python -m ensurepip --default-pip
)
echo ✓ pip available
echo.

REM Create virtual environment
echo [3/6] Setting up virtual environment...
if exist .venv (
    echo ⚠ .venv already exists, using existing environment
) else (
    echo Creating new virtual environment...
    python -m venv .venv
    echo ✓ Virtual environment created
)
echo.

REM Activate virtual environment
echo [4/6] Activating environment...
call .venv\Scripts\activate.bat
echo ✓ Environment activated
echo.

REM Upgrade pip
echo [5/6] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo ✓ pip upgraded
echo.

REM Install package
echo [6/6] Installing moviebox-api...
echo This may take a minute...
python -m pip install -e ".[cli]" --quiet
if %errorlevel% neq 0 (
    echo ❌ Installation failed!
    pause
    exit /b 1
)
echo ✓ Installation complete!
echo.

REM Check optional dependencies
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo Optional: Media Players (for streaming)
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.

where mpv >nul 2>&1
if %errorlevel% equ 0 (
    echo ✓ MPV player found
) else (
    echo ⚠ MPV not found - Download for streaming:
    echo   https://mpv.io/installation/
)

where vlc >nul 2>&1
if %errorlevel% equ 0 (
    echo ✓ VLC player found
)

echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ✅ Installation Complete!
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
echo 📝 Quick Start:
echo.
echo   1. Activate environment:
echo      .venv\Scripts\activate.bat
echo.
echo   2. Run interactive menu:
echo      moviebox interactive
echo.
echo   3. Or download directly:
echo      moviebox download-movie "Avatar"
echo.
echo 🎬 Features:
echo   • Direct episode access for TV series
echo   • Animation search tab
echo   • Smart pagination
echo   • 10+ subtitle languages
echo   • Quality selection (BEST/1080P/720P/480P)
echo.
echo Happy watching! 🍿
echo.
pause
