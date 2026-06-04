#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "[*] Virtual environment not found. Creating one..."
    python3 -m venv "$VENV_DIR"
    echo "[*] Installing dependencies..."
    "$VENV_DIR/bin/pip" install --upgrade pip -q
    "$VENV_DIR/bin/pip" install -r requirements.txt -q
    echo "[+] Dependencies installed."
fi

echo "[*] Activating virtual environment..."
source "$VENV_DIR/bin/activate"

if [ ! -f "$SCRIPT_DIR/instance/retrobridge_dev.db" ]; then
    echo "[*] Initializing database..."
    flask --app wsgi:app init-db
    flask --app wsgi:app seed
    echo "[+] Database ready."
fi

HOST="${FLASK_HOST:-127.0.0.1}"
PORT="${FLASK_PORT:-5000}"

echo ""
echo "  ┌─────────────────────────────────────────────────────────────┐"
echo "  │  R E T R O B R I D G E   B B S   v0.1.0                    │"
echo "  │  ────────────────────────────────────────────────────────   │"
echo "  │  Server:  http://${HOST}:${PORT}                              │"
echo "  │  Ctrl+C  to stop                                           │"
echo "  └─────────────────────────────────────────────────────────────┘"
echo ""

exec flask --app wsgi:app run --host "$HOST" --port "$PORT"
