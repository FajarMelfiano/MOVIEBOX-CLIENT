# Moviebox Enhanced - Installation Guide

Complete installation guide for all platforms.

## 📦 Installation Methods

### 🐧 Linux

```bash
# Clone your fork
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api

# Run installer
chmod +x install.sh
./install.sh

# Activate and run
source .venv/bin/activate
moviebox interactive
```

**One-liner install:**
```bash
git clone https://github.com/orionbyte-85/moviebox-api.git && cd moviebox-api && chmod +x install.sh && ./install.sh
```

---

### 🍎 macOS

Same as Linux:

```bash
# Clone your fork
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api

# Run installer
chmod +x install.sh
./install.sh

# Activate and run
source .venv/bin/activate
moviebox interactive
```

**Optional - Install MPV for streaming:**
```bash
brew install mpv
```

---

### 🪟 Windows

#### Method 1: PowerShell (Recommended)

```powershell
# Clone your fork
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api

# Run installer
.\install.ps1

# Activate and run
.\.venv\Scripts\Activate.ps1
moviebox interactive
```

#### Method 2: Command Prompt

```cmd
REM Clone your fork
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api

REM Run installer
install.bat

REM Activate and run
.venv\Scripts\activate.bat
moviebox interactive
```

**Note:** If you get security warnings:
```powershell
# Run PowerShell as Administrator, then:
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

### 📱 Android (Termux)

```bash
# Install Termux from F-Droid (NOT Play Store!)
# Open Termux and run:

# Install git
pkg install git

# Clone your fork
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api

# Run Termux installer
chmod +x install-termux.sh
./install-termux.sh

# Reload shell
source ~/.bashrc

# Run
moviebox-interactive
```

**Quick Install (One-liner):**
```bash
pkg install git -y && git clone https://github.com/orionbyte-85/moviebox-api.git && cd moviebox-api && chmod +x install-termux.sh && ./install-termux.sh
```

---

## 🚀 Quick Start

After installation on any platform:

### Interactive Menu
```bash
moviebox interactive
```

### Direct Downloads
```bash
# Download movie
moviebox download-movie "Avatar"

# Download TV series
moviebox download-series "Game of Thrones" -s 1 -e 1

# Stream with MPV
moviebox download-movie "Avatar" --stream-via mpv
```

---

## 🎬 New Features in Your Fork

- ✅ **Streamlined TV Series UX** - Direct to episodes!
- ✅ **Animation Search** - Dedicated search tab
- ✅ **Smart Pagination** - Total counts & page estimates
- ✅ **10+ Languages** - Subtitle support
- ✅ **Quality Selection** - BEST/1080P/720P/480P
- ✅ **Mirror Servers** - 7 server options

---

## 🛠️ Manual Installation (Advanced)

If installers don't work, manual install:

### All Platforms

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/moviebox-api.git
cd moviebox-api

# Create virtual environment
python -m venv .venv

# Activate
# Linux/Mac:
source .venv/bin/activate
# Windows CMD:
.venv\Scripts\activate.bat
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# Install
pip install -e ".[cli]"

# Run
moviebox interactive
```

---

## 🎯 Platform-Specific Tips

### Linux
- Install MPV: `sudo apt install mpv` (Ubuntu/Debian)
- Install VLC: `sudo apt install vlc`

### macOS
- Install via Homebrew: `brew install mpv vlc`

### Windows
- Download MPV: https://mpv.io/installation/
- Download VLC: https://www.videolan.org/

### Termux/Android
- Use F-Droid version (better than Play Store)
- Install MPV: `pkg install mpv`
- Termux shortcuts:
  - Volume Down + Q = Exit
  - Volume Down + C = Ctrl+C

---

## ❓ Troubleshooting

### "Python not found"
Install Python 3.9+ from python.org

### "Permission denied" (Linux/Mac)
```bash
chmod +x install.sh
```

### "Cannot load script" (Windows PowerShell)
```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Termux: "Package not found"
```bash
pkg update
pkg upgrade
```

### Dependencies fail
```bash
# Try upgrading pip first
pip install --upgrade pip

# Then retry installation
pip install -e ".[cli]"
```

---

## 📚 More Help

- Issues: https://github.com/orionbyte-85/moviebox-api/issues
- Original Repo: https://github.com/Simatwa/moviebox-api
- Documentation: See README.md

---

**Happy Watching! 🎬🍿**
