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
PTY_DEVICES="${PTY_DEVICES:-centurion pdp11}"

cleanup() {
    trap '' INT TERM
    echo ""
    echo "[*] Shutting down..."
    kill 0 2>/dev/null
    wait 2>/dev/null
    exit 0
}
trap cleanup INT TERM

echo ""
echo "  ┌─────────────────────────────────────────────────────────────┐"
echo "  │                R E T R O B R I D G E  v0.1.0                │"
echo "  │  ───────────────────────────────────────────────────────────│"
echo "  │  Server:   http://${HOST}:${PORT}                           │"
echo "  │  PTY Sims: ${PTY_DEVICES}                                   │"
echo "  │  Ctrl+C    to stop all                                      │"
echo "  └─────────────────────────────────────────────────────────────┘"
echo ""

# Start web server in background
flask --app wsgi:app run --host "$HOST" --port "$PORT" &
WEB_PID=$!
sleep 1

# Start PTY terminal simulations for each device
SIM_PIDS=()
for device in $PTY_DEVICES; do
    echo "[*] Starting PTY terminal for $device..."
    flask --app wsgi:app simulation-terminal --device "$device" &
    SIM_PIDS+=($!)
done

echo ""
echo "[*] All services running. Press Ctrl+C to stop."
echo ""

# Wait for any child to exit (or Ctrl+C)
wait
