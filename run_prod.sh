#!/usr/bin/env bash
set -euo pipefail

# Production launcher for RetroBridge using gunicorn + eventlet workers.
# Eventlet makes long-polling endpoints (SSE job events, SocketIO) efficient
# and allows a small number of workers to handle many concurrent connections.
#
# Usage:
#   export DATABASE_URL=sqlite:////var/lib/retrobridge/retrobridge.db
#   export SECRET_KEY=$(openssl rand -hex 32)
#   ./run_prod.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${FLASK_HOST:-127.0.0.1}"
PORT="${FLASK_PORT:-5000}"
WORKERS="${GUNICORN_WORKERS:-4}"

echo "[*] Starting RetroBridge production server on ${HOST}:${PORT}"
echo "    Workers: ${WORKERS} (eventlet)"

exec gunicorn \
    -k eventlet \
    -w "${WORKERS}" \
    -b "${HOST}:${PORT}" \
    --access-logfile - \
    --error-logfile - \
    wsgi_eventlet:app
