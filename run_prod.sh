#!/usr/bin/env bash
set -euo pipefail

# Production launcher for RetroBridge using gunicorn + gthread workers.
# Threads make long-polling endpoints (SSE job events, SocketIO) efficient
# and allow a small number of workers to handle many concurrent connections.
# (eventlet was removed: 0.36.x crashes on Python 3.13+ during monkey-patch.)
#
# Usage:
#   export DATABASE_URL=sqlite:////var/lib/retrobridge/retrobridge.db
#   export SECRET_KEY=$(openssl rand -hex 32)
#   ./run_prod.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Never fall back to DevConfig (DEBUG=True) in production.  This must be
# exported before the app boots; ProdConfig.validate() then fails fast if
# SECRET_KEY is missing.
export FLASK_ENV=production

if [ -z "${SECRET_KEY:-}" ]; then
    echo "[!] SECRET_KEY is not set — refusing to start."
    echo "    export SECRET_KEY=\$(openssl rand -hex 32)"
    exit 1
fi

HOST="${FLASK_HOST:-127.0.0.1}"
PORT="${FLASK_PORT:-5000}"
WORKERS="${GUNICORN_WORKERS:-1}"
THREADS="${GUNICORN_THREADS:-64}"

# Prefer the project venv's gunicorn; fall back to PATH.
GUNICORN="${GUNICORN_BIN:-${SCRIPT_DIR}/venv/bin/gunicorn}"
if [ ! -x "${GUNICORN}" ]; then
    if command -v gunicorn >/dev/null 2>&1; then
        GUNICORN="$(command -v gunicorn)"
    else
        echo "[!] gunicorn not found (looked in ${SCRIPT_DIR}/venv/bin and PATH)."
        echo "    Install dependencies: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
        exit 1
    fi
fi

# SocketIO has no message queue: emits (session_closed, terminal_output,
# force-disconnect) do not cross worker processes.  A single gthread worker
# with many threads handles concurrency correctly.
if [ "${WORKERS}" -gt 1 ]; then
    echo "[!] WARNING: ${WORKERS} gunicorn workers requested, but SocketIO has"
    echo "    no message queue — realtime events are worker-local.  Use"
    echo "    GUNICORN_WORKERS=1 unless message_queue='redis://...' is configured."
fi

echo "[*] Starting RetroBridge production server on ${HOST}:${PORT}"
echo "    Workers: ${WORKERS} (gthread, ${THREADS} threads each)"

exec "${GUNICORN}" \
    -k gthread \
    -w "${WORKERS}" \
    --threads "${THREADS}" \
    -b "${HOST}:${PORT}" \
    --access-logfile - \
    --error-logfile - \
    wsgi:app
