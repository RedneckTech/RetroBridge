#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/venv"
DB_FILE="$SCRIPT_DIR/instance/retrobridge_dev.db"

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

needs_recreate() {
    if [ ! -f "$1" ]; then
        return 0
    fi
    # Check for a known column to detect stale schema
    python3 -c "
import sqlite3
conn = sqlite3.connect('$1')
cur = conn.cursor()
cur.execute(\"SELECT transport FROM device_ports LIMIT 0\")
conn.close()
" 2>/dev/null
}

if [ -f "$DB_FILE" ]; then
    if ! needs_recreate "$DB_FILE"; then
        echo "[!] Database schema is stale (missing columns)."
        echo "    This happens when the data model changed."
        if [ -t 0 ]; then
            read -p "[?] Recreate database? This will DESTROY all data. [y/N] " answer
        else
            answer=n
        fi
        if [ "${answer,,}" = "y" ] || [ "${answer,,}" = "yes" ]; then
            rm -f "$DB_FILE"
            echo "[*] Old database removed. Recreating..."
        else
            echo "[!] Skipping. Some features may not work."
            echo "    Run: rm instance/retrobridge_dev.db && flask init-db && flask seed"
        fi
    fi
fi

if [ ! -f "$DB_FILE" ]; then
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
