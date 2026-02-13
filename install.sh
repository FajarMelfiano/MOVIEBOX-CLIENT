#!/bin/bash
# Moviebox Enhanced - Linux/macOS Installation Script
# Enhanced TUI with streamlined UX and animation search

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════╗"
echo "║                                          ║"
echo "║  🎬 MOVIEBOX ENHANCED - INSTALLER        ║"
echo "║                                          ║"
echo "╚══════════════════════════════════════════╝"
echo -e "${NC}"
echo ""

# Check Python
echo -e "${BLUE}[1/6]${NC} Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 not found!${NC}"
    echo ""
    echo "Please install Python 3.9 or higher:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "  Fedora/RHEL:   sudo dnf install python3 python3-pip"
    echo "  macOS:         brew install python3"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "${GREEN}✓${NC} Found Python $PYTHON_VERSION"
echo ""

# Check pip
echo -e "${BLUE}[2/6]${NC} Checking pip..."
if ! command -v pip3 &> /dev/null && ! python3 -m pip --version &> /dev/null; then
    echo -e "${YELLOW}⚠ pip not found, installing...${NC}"
    python3 -m ensurepip --default-pip
fi
echo -e "${GREEN}✓${NC} pip available"
echo ""

# Create virtual environment
echo -e "${BLUE}[3/6]${NC} Setting up virtual environment..."
if [ -d ".venv" ]; then
    # Check if venv has pip
    if [ ! -f ".venv/bin/pip" ]; then
        echo -e "${YELLOW}⚠ Existing venv is broken, recreating...${NC}"
        rm -rf .venv
        python3 -m venv .venv
        echo -e "${GREEN}✓${NC} Virtual environment created"
    else
        echo -e "${YELLOW}⚠ .venv already exists, using existing environment${NC}"
    fi
else
    echo "Creating new virtual environment..."
    python3 -m venv .venv
    echo -e "${GREEN}✓${NC} Virtual environment created"
fi
echo ""

# Activate virtual environment
echo -e "${BLUE}[4/6]${NC} Activating environment..."
source .venv/bin/activate

# Verify we're using venv python
VENV_PYTHON=$(which python3)
if [[ "$VENV_PYTHON" != *".venv"* ]]; then
    echo -e "${YELLOW}⚠ Warning: Not using venv python, forcing...${NC}"
    export PATH="$(pwd)/.venv/bin:$PATH"
fi
echo -e "${GREEN}✓${NC} Environment activated"
echo ""

# Upgrade pip (use venv pip explicitly)
echo -e "${BLUE}[5/6]${NC} Upgrading pip..."
.venv/bin/pip install --upgrade pip --quiet
echo -e "${GREEN}✓${NC} pip upgraded"
echo ""

# Install package (use venv pip explicitly)
echo -e "${BLUE}[6/6]${NC} Installing moviebox-api..."
echo "This may take a minute..."
.venv/bin/pip install -e ".[cli]" --quiet

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Installation complete!"
else
    echo -e "${RED}❌ Installation failed!${NC}"
    exit 1
fi
echo ""

# Check optional dependencies
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Optional: Media Players (for streaming)${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if command -v mpv &> /dev/null; then
    echo -e "${GREEN}✓${NC} MPV player found"
else
    echo -e "${YELLOW}⚠${NC} MPV not found - Install for streaming support:"
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "  Ubuntu/Debian: ${CYAN}sudo apt install mpv${NC}"
        echo "  Fedora/RHEL:   ${CYAN}sudo dnf install mpv${NC}"
        echo "  Arch Linux:    ${CYAN}sudo pacman -S mpv${NC}"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  macOS:         ${CYAN}brew install mpv${NC}"
    fi
fi

if command -v vlc &> /dev/null; then
    echo -e "${GREEN}✓${NC} VLC player found"
fi

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Installation Complete!${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}📝 Quick Start:${NC}"
echo ""
echo "  1. Activate environment:"
echo -e "     ${CYAN}source .venv/bin/activate${NC}"
echo ""
echo "  2. Run interactive menu:"
echo -e "     ${CYAN}moviebox interactive${NC}"
echo ""
echo "  3. Or download directly:"
echo -e "     ${CYAN}moviebox download-movie \"Avatar\"${NC}"
echo ""
echo -e "${YELLOW}🎬 Features:${NC}"
echo "  • Direct episode access for TV series"
echo "  • Animation search tab"
echo "  • Smart pagination"
echo "  • 10+ subtitle languages"
echo "  • Quality selection (BEST/1080P/720P/480P)"
echo ""
echo -e "${YELLOW}📚 Documentation:${NC}"
echo -e "  ${CYAN}https://github.com/orionbyte-85/moviebox-api${NC}"
echo ""
echo -e "${GREEN}Happy watching! 🍿${NC}"
echo ""
