#!/data/data/com.termux/files/usr/bin/bash
# Moviebox Enhanced - Termux/Android Installation Script
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
echo "║  🎬 MOVIEBOX ENHANCED - TERMUX           ║"
echo "║                                          ║"
echo "╚══════════════════════════════════════════╝"
echo -e "${NC}"
echo ""

echo -e "${YELLOW}📱 Termux/Android Installation${NC}"
echo ""

# Update packages
echo -e "${BLUE}[1/6]${NC} Updating Termux packages..."
pkg update -y
echo -e "${GREEN}✓${NC} Packages updated"
echo ""

# Install Python
echo -e "${BLUE}[2/6]${NC} Installing Python..."
if ! command -v python &> /dev/null; then
    pkg install python -y
fi
PYTHON_VERSION=$(python --version | cut -d' ' -f2)
echo -e "${GREEN}✓${NC} Python $PYTHON_VERSION installed"
echo ""

# Install build dependencies
echo -e "${BLUE}[3/6]${NC} Installing build dependencies..."
pkg install build-essential libffi openssl -y
echo -e "${GREEN}✓${NC} Dependencies installed"
echo ""

# Install pip packages
echo -e "${BLUE}[4/6]${NC} Installing Python packages..."
# pip install --upgrade pip --quiet

# Termux requires special installation (no deps first)
echo "Installing moviebox-api (this may take a few minutes)..."
pip install --no-deps .
pip install 'pydantic==2.9.2'
pip install rich click bs4 httpx throttlebuster
echo -e "${GREEN}✓${NC} Packages installed"
echo ""

# Install optional dependencies
echo -e "${BLUE}[5/6]${NC} Installing optional packages..."
echo "Installing CLI dependencies..."
pip install rich-click --quiet 2>/dev/null || echo "Some optional packages skipped"
echo -e "${GREEN}✓${NC} Optional packages installed"
echo ""

# Setup alias
echo -e "${BLUE}[6/6]${NC} Setting up shortcuts..."
if ! grep -q "alias moviebox=" ~/.bashrc; then
    echo "" >> ~/.bashrc
    echo "# Moviebox Enhanced aliases" >> ~/.bashrc
    echo "alias moviebox='python -m moviebox_api'" >> ~/.bashrc
    echo "alias moviebox-interactive='python -m moviebox_api interactive'" >> ~/.bashrc
fi
source ~/.bashrc
echo -e "${GREEN}✓${NC} Shortcuts configured"
echo ""

# Check optional players
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Optional: Media Players${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if command -v mpv &> /dev/null; then
    echo -e "${GREEN}✓${NC} MPV player found"
else
    echo -e "${YELLOW}⚠${NC} MPV not found - Install for streaming:"
    echo "  ${CYAN}pkg install mpv${NC}"
fi

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Installation Complete!${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}📝 Quick Start:${NC}"
echo ""
echo "  1. Reload shell (to activate aliases):"
echo -e "     ${CYAN}source ~/.bashrc${NC}"
echo ""
echo "  2. Run interactive menu:"
echo -e "     ${CYAN}moviebox-interactive${NC}"
echo "     or"
echo -e "     ${CYAN}python -m moviebox_api interactive${NC}"
echo ""
echo "  3. Download directly:"
echo -e "     ${CYAN}moviebox download-movie \"Avatar\"${NC}"
echo ""
echo -e "${YELLOW}🎬 Features:${NC}"
echo "  • Direct episode access for TV series"
echo "  • Animation search tab"
echo "  • Smart pagination"
echo "  • 10+ subtitle languages"
echo "  • Works great on Android!"
echo ""
echo -e "${YELLOW}💡 Termux Tips:${NC}"
echo "  • Use volume down + q to exit programs"
echo "  • Install MPV: ${CYAN}pkg install mpv${NC}"
echo "  • For better experience: ${CYAN}pkg install termux-api${NC}"
echo ""
echo -e "${GREEN}Happy watching on Android! 📱🍿${NC}"
echo ""
