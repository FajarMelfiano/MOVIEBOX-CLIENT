# Moviebox Enhanced - Windows PowerShell Installation Script
# Enhanced TUI with streamlined UX and animation search

Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                                          ║" -ForegroundColor Cyan
Write-Host "║  🎬 MOVIEBOX ENHANCED - INSTALLER        ║" -ForegroundColor Cyan
Write-Host "║                                          ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "[1/6] Checking Python installation..." -ForegroundColor Blue
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Found $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Python 3.9+ from:" -ForegroundColor Yellow
    Write-Host "  https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Make sure to check 'Add Python to PATH' during installation!" -ForegroundColor Yellow
    pause
    exit 1
}
Write-Host ""

# Check pip
Write-Host "[2/6] Checking pip..." -ForegroundColor Blue
try {
    $pipVersion = python -m pip --version 2>&1
    Write-Host "✓ pip available" -ForegroundColor Green
} catch {
    Write-Host "⚠ pip not found, installing..." -ForegroundColor Yellow
    python -m ensurepip --default-pip
}
Write-Host ""

# Create virtual environment
Write-Host "[3/6] Setting up virtual environment..." -ForegroundColor Blue
if (Test-Path ".venv") {
    Write-Host "⚠ .venv already exists, using existing environment" -ForegroundColor Yellow
} else {
    Write-Host "Creating new virtual environment..."
    python -m venv .venv
    Write-Host "✓ Virtual environment created" -ForegroundColor Green
}
Write-Host ""

# Activate virtual environment
Write-Host "[4/6] Activating environment..." -ForegroundColor Blue
& .\.venv\Scripts\Activate.ps1
Write-Host "✓ Environment activated" -ForegroundColor Green
Write-Host ""

# Upgrade pip
Write-Host "[5/6] Upgrading pip..." -ForegroundColor Blue
python -m pip install --upgrade pip --quiet
Write-Host "✓ pip upgraded" -ForegroundColor Green
Write-Host ""

# Install package
Write-Host "[6/6] Installing moviebox-api..." -ForegroundColor Blue
Write-Host "This may take a minute..."
python -m pip install -e ".[cli]" --quiet

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Installation complete!" -ForegroundColor Green
} else {
    Write-Host "❌ Installation failed!" -ForegroundColor Red
    pause
    exit 1
}
Write-Host ""

# Check optional dependencies
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "Optional: Media Players (for streaming)" -ForegroundColor Yellow
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

if (Get-Command mpv -ErrorAction SilentlyContinue) {
    Write-Host "✓ MPV player found" -ForegroundColor Green
} else {
    Write-Host "⚠ MPV not found - Download for streaming:" -ForegroundColor Yellow
    Write-Host "  https://mpv.io/installation/" -ForegroundColor Cyan
}

if (Get-Command vlc -ErrorAction SilentlyContinue) {
    Write-Host "✓ VLC player found" -ForegroundColor Green
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "✅ Installation Complete!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
Write-Host "📝 Quick Start:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1. Activate environment:" 
Write-Host "     .\.venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "  2. Run interactive menu:"
Write-Host "     moviebox interactive" -ForegroundColor Cyan
Write-Host ""
Write-Host "  3. Or download directly:"
Write-Host "     moviebox download-movie `"Avatar`"" -ForegroundColor Cyan
Write-Host ""
Write-Host "🎬 Features:" -ForegroundColor Yellow
Write-Host "  • Direct episode access for TV series"
Write-Host "  • Animation search tab"
Write-Host "  • Smart pagination"
Write-Host "  • 10+ subtitle languages"
Write-Host "  • Quality selection (BEST/1080P/720P/480P)"
Write-Host ""
Write-Host "Happy watching! 🍿" -ForegroundColor Green
Write-Host ""
pause
