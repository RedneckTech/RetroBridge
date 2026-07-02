#!/usr/bin/env bash
# =============================================================================
# RetroBridge — Emulator Launcher
# =============================================================================
#
# Starts Open SIMH (PDP-11) and CPU7Plus (Centurion) emulators with the
# example configs in this directory, then prints RetroBridge DevicePort
# configuration snippets for the admin panel.
#
# Usage:
#   ./start.sh                    # start both emulators
#   ./start.sh --pdp11            # PDP-11 only
#   ./start.sh --centurion        # Centurion only
#
# Prerequisites:
#   - simh-pdp11 (Open SIMH PDP-11 emulator) on PATH
#   - cpu7plus (CPU7Plus Centurion emulator) on PATH  (optional)
#   - Bootable OS disk images alongside the .ini configs
#       pdp11-rsts.dsk    (for SIMH)
#       centurion-os.dsk  (for CPU7Plus)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PDP11=0
CENTURION=0

if [ $# -eq 0 ]; then
    PDP11=1
    CENTURION=1
else
    for arg in "$@"; do
        case "$arg" in
            --pdp11)     PDP11=1 ;;
            --centurion) CENTURION=1 ;;
            --help|-h)
                echo "Usage: $0 [--pdp11] [--centurion]"
                echo ""
                echo "Starts emulators for RetroBridge integration."
                echo "Default (no flags): start both."
                exit 0
                ;;
            *)
                echo "Unknown flag: $arg"
                exit 1
                ;;
        esac
    done
fi

cleanup() {
    trap '' INT TERM
    echo ""
    echo "[*] Stopping emulators..."
    kill 0 2>/dev/null
    wait 2>/dev/null
    exit 0
}
trap cleanup INT TERM

echo ""
echo "  ┌─────────────────────────────────────────────────────────────┐"
echo "  │        RetroBridge Emulator Launcher                       │"
echo "  └─────────────────────────────────────────────────────────────┘"
echo ""

if [ "$PDP11" -eq 1 ]; then
    if command -v pdp11 &>/dev/null || command -v simh-pdp11 &>/dev/null; then
        echo "[*] Starting SIMH PDP-11..."
        SIMH_BIN=$(command -v pdp11 || command -v simh-pdp11)
        "$SIMH_BIN" "$SCRIPT_DIR/simh-pdp11.ini" &
        echo "    PID: $!"
    else
        echo "[!] SIMH PDP-11 not found (expected 'pdp11' or 'simh-pdp11' on PATH)"
    fi
fi

if [ "$CENTURION" -eq 1 ]; then
    if command -v cpu7plus &>/dev/null; then
        echo "[*] Starting CPU7Plus Centurion..."
        cpu7plus "$SCRIPT_DIR/cpu7plus.ini" &
        echo "    PID: $!"
    else
        echo "[!] CPU7Plus not found (expected 'cpu7plus' on PATH)"
    fi
fi

echo ""
echo "───────────────────────────────────────────────────────────────"
echo " RetroBridge Admin Panel — DevicePort Configuration"
echo "───────────────────────────────────────────────────────────────"
echo ""

if [ "$PDP11" -eq 1 ]; then
    echo "  PDP-11/44 (SIMH):"
    echo "    transport=tcp  dev_path=127.0.0.1:10023  purpose=job_queue       transfer_protocol=xmodem  newline_mode=crlf"
    echo "    transport=tcp  dev_path=127.0.0.1:10024  purpose=interactive    newline_mode=crlf"
    echo "    transport=tcp  dev_path=127.0.0.1:10025  purpose=interactive    newline_mode=crlf"
    echo "    transport=tcp  dev_path=127.0.0.1:10026  purpose=interactive    newline_mode=crlf"
    echo ""
fi

if [ "$CENTURION" -eq 1 ]; then
    echo "  Centurion CPU-6 (CPU7Plus):"
    echo "    transport=tcp  dev_path=127.0.0.1:10901  purpose=job_queue       transfer_protocol=xmodem  newline_mode=crlf"
    echo "    transport=tcp  dev_path=127.0.0.1:10902  purpose=interactive    newline_mode=crlf"
    echo "    transport=tcp  dev_path=127.0.0.1:10903  purpose=interactive    newline_mode=crlf"
    echo ""
fi

echo "[*] Emulators running. Press Ctrl+C to stop."
echo ""

wait
