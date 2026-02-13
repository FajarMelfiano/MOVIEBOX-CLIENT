#!/bin/bash
# Convenience script to run Stremio addon with auto-venv activation

# Ensure we're in the project directory
cd "$(dirname "$0")"

# Check if venv exists
if [ -d ".venv" ]; then
    echo "Using existing .venv..."
    source .venv/bin/activate
else
    echo "Creating .venv..."
    uv venv
    source .venv/bin/activate
    uv pip install -e ".[cli]"
fi

# Ensure port 7000 is clean (kill any lingering process)
PID=$(lsof -ti:7000 2>/dev/null)
if [ ! -z "$PID" ]; then
    echo "Stopping existing server on port 7000 (PID $PID)..."
    kill -9 $PID
    sleep 1
fi

# Run the server
echo "Starting MovieBox Stremio Addon..."
python -m moviebox_api.stremio
