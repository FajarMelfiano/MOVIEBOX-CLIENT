<div align="center">

# 🎬 Moviebox Enhanced

**Ultimate Python wrapper for moviebox.ph with Enhanced Interactive TUI**

[![PyPI version](https://badge.fury.io/py/moviebox-api.svg)](https://pypi.org/project/moviebox-api)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](https://unlicense.org/)
[![Downloads](https://pepy.tech/badge/moviebox-api)](https://pepy.tech/project/moviebox-api)

**Search • Download • Stream** movies and TV series with a beautiful terminal interface

[Features](#-features) • [Installation](#-installation) • [Quick Start](#-quick-start) • [Documentation](#-documentation)

![Demo](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)

</div>

---

## ✨ What's New in Enhanced Edition

🚀 **Streamlined TV Series UX** - Direct episode access, skip menus!  
🎨 **Animation Search** - Dedicated tab for anime & animated content  
📊 **Smart Pagination** - Total counts & estimated pages  
🎭 **Enhanced Quality Selection** - 4 quality levels, 10+ subtitle languages  
🌐 **Mirror Servers** - 7 server options for reliability  
💻 **Cross-Platform Installers** - One-click install for Linux/Mac/Windows/Android

---

## 🎯 Features

### 🎬 Enhanced Interactive TUI

<details>
<summary><b>📺 Streamlined TV Series</b></summary>

- **Direct Episode Access** - Skip action menus, go straight to episodes
- **Full Season Browser** - See all seasons and episodes instantly
- **Binge-Watching Friendly** - Optimized for marathon viewing
- **Episode Counts** - Know exactly how many episodes available

</details>

<details>
<summary><b>🎨 Animation Search</b></summary>

- **Dedicated Search Tab** - Menu option [3] for anime/animated content
- **Specialized Results** - Filtered for animation content
- **Same Features** - All TUI enhancements work for anime

</details>

<details>
<summary><b>📊 Smart Pagination</b></summary>

- **Total Item Counts** - See total results across all pages
- **Page Estimates** - "Page 2 of ~9+" display
- **Better Navigation** - Previous/Next with context

</details>

<details>
<summary><b>⚙️ Quality & Subtitles</b></summary>

**Quality Options:**
- 🎬 BEST - Highest available (Recommended)
- 📺 1080P - Full HD
- 💿 720P - HD
- 📱 480P - SD

**Subtitle Languages:**
🇮🇩 Indonesian • 🇬🇧 English • 🇪🇸 Spanish • 🇫🇷 French  
🇨🇳 Chinese • 🇯🇵 Japanese • 🇰🇷 Korean • 🇸🇦 Arabic  
🇵🇹 Portuguese • 🇷🇺 Russian • + Custom

</details>

### 📥 Core Features

- ⚡ **Super Fast Downloads** - 5x faster than standard downloads
- 🎥 **Stream with MPV/VLC** - Watch without downloading
- 📝 **Smart Subtitles** - Auto-download in your language
- 🔄 **Async Support** - Fully asynchronous operations
- 🐍 **Clean Python API** - Easy integration with Pydantic models
- 🔍 **Search & Discovery** - Find trending and popular content

---

## 📦 Installation

### 🚀 Quick Install (Recommended)

Choose your platform:

<details open>
<summary><b>🐧 Linux / 🍎 macOS</b></summary>

```bash
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
chmod +x install.sh
./install.sh
```

Then activate and run:
```bash
source .venv/bin/activate
moviebox interactive
```

</details>

<details>
<summary><b>🪟 Windows (PowerShell)</b></summary>

```powershell
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
.\install.ps1
```

Then activate and run:
```powershell
.\.venv\Scripts\Activate.ps1
moviebox interactive
```

</details>

<details>
<summary><b>🪟 Windows (CMD)</b></summary>

```cmd
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
install.bat
```

Then activate and run:
```cmd
.venv\Scripts\activate.bat
moviebox interactive
```

</details>

<details>
<summary><b>📱 Android (Termux)</b></summary>

```bash
pkg install git -y
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
chmod +x install-termux.sh
./install-termux.sh
source ~/.bashrc
moviebox-interactive
```

**Note:** Use Termux from [F-Droid](https://f-droid.org/), not Play Store!

</details>

### 📚 Detailed Installation

See **[INSTALL.md](./INSTALL.md)** for:
- Manual installation steps
- Troubleshooting guide
- Platform-specific tips
- Media player setup

### 🎯 Install from PyPI (Original)

For the original package (without enhancements):

```bash
pip install "moviebox-api[cli]"
```

**Why install from source instead?**
- ✅ Get latest enhanced features
- ✅ Streamlined TV series UX
- ✅ Animation search tab
- ✅ Direct episode access
- ✅ Your custom modifications

---

## 🚀 Quick Start

### Interactive Menu (Easiest)

```bash
moviebox interactive
```

```
╔══════════════════════════════════════════╗
║                                          ║
║  🎬 MOVIEBOX - Stream & Download         ║
║                                          ║
╚══════════════════════════════════════════╝

[1] 🎬 Search Movies
[2] 📺 Search TV Series
[3] 🎨 Search Animation     ← NEW!
[4] 📚 Search All Content
[5] ⭐ Trending
[0] 🚪 Exit
```

**Enhanced Workflow:**

1. Select **[3] Animation** for anime
2. Search: *"Demon King Academy"*
3. **Instantly see episodes** (no action menu!)
4. Pick episode → Stream or Download
5. Select quality → Choose subtitles
6. Watch! 🍿

### Command Line Examples

```bash
# Download movie
moviebox download-movie "Avatar"

# Download TV series episode
moviebox download-series "Game of Thrones" -s 1 -e 1

# Stream with MPV (requires mpv player)
moviebox download-movie "Avatar" --stream-via mpv

# Download with specific quality
moviebox download-movie "Avatar" --quality 1080p

# Download with subtitles
moviebox download-series "Breaking Bad" -s 1 -e 1 --language Indonesian
```

### Python API

```python
from moviebox_api import MovieAuto
import asyncio

async def main():
    auto = MovieAuto()
    movie_file, subtitle_file = await auto.run("Avatar")
    print(f"Downloaded: {movie_file.saved_to}")

asyncio.run(main())
```

---

## 📖 Documentation

### 📚 Guides

- **[Installation Guide](./INSTALL.md)** - Detailed setup for all platforms
- **[API Documentation](./docs/README.md)** - Full API reference
- **[Examples](./docs/examples/)** - Code examples and use cases

### ⚡ Quick Reference

<details>
<summary><b>Download Commands</b></summary>

**Movies:**
```bash
moviebox download-movie "Title" [OPTIONS]
  -y, --year YEAR           Filter by year
  -q, --quality QUALITY     Video quality
  -x, --language LANGUAGE   Subtitle language
  -Y, --yes                 Auto-confirm
  -X, --stream-via PLAYER   Stream instead of download
```

**TV Series:**
```bash
moviebox download-series "Title" -s SEASON -e EPISODE [OPTIONS]
  -l, --limit NUMBER        Episodes to download
  -A, --auto-mode          Download all seasons
  --format group           Organize by season folders
```

</details>

<details>
<summary><b>Mirror Servers</b></summary>

If default server is slow or blocked:

```bash
# Show available mirrors
moviebox mirror-hosts

# Set environment variable
export MOVIEBOX_API_HOST="h5.aoneroom.com"  # Linux/Mac
set MOVIEBOX_API_HOST=h5.aoneroom.com       # Windows
```

Available mirrors:
- h5.aoneroom.com
- movieboxapp.in
- moviebox.pk
- moviebox.ph
- moviebox.id
- v.moviebox.ph
- netnaija.video

</details>

<details>
<summary><b>Media Players</b></summary>

**Install MPV (Recommended):**

```bash
# Ubuntu/Debian
sudo apt install mpv

# macOS
brew install mpv

# Windows
# Download from https://mpv.io/installation/

# Termux
pkg install mpv
```

**Stream Example:**
```bash
moviebox download-movie "Avatar" --stream-via mpv --quality 720p
```

</details>

---

## 🎨 Features Showcase

### Before vs After

**Before (Original):**
```
TV Series → Actions Menu → [3] View Episodes → Episodes
3 clicks, slow navigation
```

**After (Enhanced):**
```
TV Series → Episodes Immediately! ✨
1 click, instant access
```

### Enhanced Features

| Feature | Original | Enhanced | Benefit |
|---------|----------|----------|---------|
| TV Series Access | 3 clicks | 1 click | ⚡ Faster |
| Animation Search | No | Yes | 🎨 Dedicated |
| Pagination Info | Basic | Smart | 📊 Detailed |
| Subtitle Languages | Manual | 10+ options | 🌍 Global |
| Episode Data | Limited | Complete | 📺 Full info |
| Installation | Pip only | 4 platforms | 💻 Universal |

---

## 🛠️ Advanced Usage

### Batch Downloads

Download entire series:
```bash
moviebox download-series "Breaking Bad" -s 1 -e 1 --auto-mode
```

Organize by folders:
```bash
moviebox download-series "Game of Thrones" -s 1 -e 1 \
  --auto-mode --format group
```

### Custom Configuration

```python
from moviebox_api import MovieAuto

auto = MovieAuto(
    caption_language="Spanish",
    quality="720p",
    download_dir="~/Movies"
)
```

### Progress Tracking

```python
async def progress_callback(progress):
    percent = (progress.downloaded_size / progress.expected_size) * 100
    print(f"[{percent:.1f}%] {progress.saved_to.name}")

await auto.run("Avatar", progress_hook=progress_callback)
```

---

## 🔧 Troubleshooting

<details>
<summary><b>Virtual Environment Issues</b></summary>

**"externally-managed-environment" error:**

The installer automatically handles this by using venv pip directly.

**Manual fix:**
```bash
.venv/bin/pip install -e ".[cli]"  # Use venv pip explicitly
```

</details>

<details>
<summary><b>Windows PowerShell Security</b></summary>

**"Cannot load script" error:**

```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

</details>

<details>
<summary><b>Termux Installation</b></summary>

**Package errors:**
```bash
pkg update && pkg upgrade
pkg install python build-essential
```

**Use F-Droid version** for best compatibility.

</details>

---

## 🤝 Contributing

Contributions welcome! This is an enhanced fork focused on TUI improvements.

**Original Repository:** [Simatwa/moviebox-api](https://github.com/Simatwa/moviebox-api)

### Development Setup

```bash
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
python -m venv .venv
source .venv/bin/activate
pip install -e ".[cli]"
```

---

## 📜 License

This is free and unencumbered software released into the **public domain** (Unlicense).

See [LICENSE](./LICENSE) for details.

---

## ⚠️ Disclaimer

> "All videos and pictures on MovieBox are from the Internet, and their copyrights belong to the original creators. We only provide webpage services and do not store, record, or upload any content."  
> — *moviebox.ph*

This tool is for educational purposes. Respect copyright laws in your jurisdiction.

---

## 🌟 Acknowledgments

- **Original Author:** [Simatwa](https://github.com/Simatwa) for the amazing base project
- **Contributors:** See [contributors page](https://github.com/Simatwa/moviebox-api/graphs/contributors)
- **You:** For using and improving this project!

---

<div align="center">

### 🎬 Ready to Watch?

```bash
git clone https://github.com/orionbyte-85/moviebox-api.git
cd moviebox-api
./install.sh
source .venv/bin/activate
moviebox interactive
```

**Made with ❤️ for the community**

[⬆ Back to Top](#-moviebox-enhanced)

</div>
# MOVIEBOX-CLIENT
# MOVIEBOX-CLIENT
