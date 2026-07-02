# RetroBridge

**Bridge modern web workflows to vintage minicomputers over RS-232.**

RetroBridge is a Flask web application that lets users submit programs for batch execution on vintage minicomputers and interactively log into them through a browser-based terminal emulator — all over RS-232 serial connections.

Currently targets the **Centurion CPU-6** and **DEC PDP-11/44**, both multi-user, multi-port systems. Job-dedicated ports handle automated program transfers and output capture, while interactive ports provide real-time terminal sessions via WebSocket.

---

## Features

- **Job queue with scheduling** — Upload programs, queue them per-device, and let background workers handle transfer via XMODEM
- **Live job updates via SSE** — Job detail pages stream status changes and output in real time with Server-Sent Events; dashboard auto-refreshes
- **Web-based interactive terminal** — Log into vintage systems through your browser using xterm.js + WebSocket, with full bidirectional serial bridging
- **Multi-transport device support** — Connect via local RS-232, PTY, raw TCP, Telnet, or RFC 2217 remote serial
- **Emulated systems as production targets** — Connect Open SIMH (PDP-11) or CPU7Plus (Centurion) emulators via TCP and use them as first-class devices alongside real hardware
- **Multi-port device support** — Each vintage machine can have multiple ports, partitioned into job-queue and interactive pools
- **Per-port serial configuration** — Baud rate, parity, stop bits, flow control, and line-ending conversion configurable per port
- **Admin panel** — Manage users, devices, ports, jobs, terminal sessions, and global settings
- **PTY-based simulation** — Develop and test without hardware using built-in pseudo-terminal simulation for both job processing and terminal sessions
- **Role-based access control** — Regular users manage their own jobs and sessions; admins have full control
- **Admin force-disconnect** — Admins can terminate terminal sessions remotely; the `session_closed` event pushes to the client's browser via Socket.IO
- **Audit logging** — Every byte sent and received on job ports is timestamped; optional per-session keystroke/output logging for terminal sessions
- **Upload security** — File content validated against magic bytes (rejects ELF, PE, archives, images), text/binary detection per extension, size limits enforced before disk write
- **Health check endpoints** — Liveness (`GET /health`) and readiness (`GET /ready`) probes for load balancers and container orchestration
- **SQLite backup system** — CLI commands for online backup/restore with automatic pruning and a standalone cron script

---

## Architecture

```
Browser ──HTTPS──▶ nginx ──HTTP──▶ gunicorn ──▶ Flask App ──▶ SQLite (WAL)
                    │  └─WebSocket──▶ Flask-SocketIO (eventlet)
                    │  └─SSE stream──▶ /api/jobs/<id>/events
                    │
Worker (Centurion) ──transport──▶ Centurion CPU-6 (job ports)
Worker (PDP-11)    ──transport──▶ PDP-11/44      (job ports)
Terminal Sessions  ──transport──▶ Both machines   (interactive ports)
Emulated Systems   ──TCP/Telnet──▶ SIMH / CPU7Plus (production)

transport ∈ { serial, pty, tcp, telnet, rfc2217 }
```

Workers communicate with the Flask app **only through the SQLite database** (poll/claim/update pattern). Terminal sessions bridge WebSocket ↔ serial/network in real time via eventlet green threads. Job status and output stream to browsers via Server-Sent Events.

---

## Tech Stack

| Layer          | Technology                                          |
| -------------- | --------------------------------------------------- |
| Backend        | Python 3.11+, Flask 3.x, Flask-SocketIO 5.x, python-dotenv |
| ORM / DB       | SQLAlchemy 2.0, SQLite (WAL mode)                   |
| Serial I/O     | pyserial 3.5, xmodem 0.4, raw sockets (TCP/Telnet)  |
| Live Updates   | Server-Sent Events (job status/output streaming)     |
| Frontend       | Bootstrap 5, Jinja2, xterm.js 5.x                   |
| WebSocket      | Flask-SocketIO + eventlet                           |
| WSGI Server    | gunicorn                                            |
| Reverse Proxy  | nginx (TLS termination, WebSocket proxying)         |
| Process Mgmt   | systemd, run.sh (dev convenience)                   |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Linux with systemd (for production deployment)
- RS-232 serial adapters (USB or PCIe) connected to vintage hardware — *or use PTY simulation for development*

### Quick Start with `run.sh`

The easiest way to get a dev environment running:

```bash
./run.sh
```

This script:
- Creates a virtual environment and installs dependencies if needed
- Detects stale database schemas (missing columns from model changes) and offers to recreate
- Initializes and seeds the database on first run
- Starts the Flask dev server
- Launches PTY terminal simulations for each configured device

Use `Ctrl+C` to stop all services. Set `PTY_DEVICES` to control which simulations start:

```bash
PTY_DEVICES="centurion" ./run.sh
```

### Manual Setup

```bash
# Clone the repo
git clone git@github.com:RedneckTech/RetroBridge.git
cd RetroBridge

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment — copy the example and edit as needed
cp .env.example .env

# Initialize the database
flask init-db

# Seed default devices and admin user
flask seed

# Start the dev server
flask run
```

### Schema Changes

When the data model changes (new columns added), the dev database must be recreated:

```bash
rm instance/retrobridge_dev.db && flask init-db && flask seed
```

`run.sh` detects this automatically and prompts before recreating.

### Development with Simulation (no hardware required)

```bash
# Run a simulated job worker (PTY-based, mimics vintage machine)
flask simulation-worker --device centurion

# In another terminal, start a PTY-based interactive terminal simulation
flask simulation-terminal --device centurion
```

### Database Backups

```bash
# Create a compressed backup with automatic pruning
flask db backup

# Uncompressed backup with a custom label
flask db backup --no-compress --label before-upgrade

# List existing backups with human-readable sizes
flask db list-backups -h

# Restore from a backup (requires confirmation)
flask db restore /path/to/backup.db.gz
```

A standalone cron-friendly script is also available:
```
0 3 * * * /srv/retrobridge/venv/bin/python /srv/retrobridge/deploy/backup.py
```

### Health Check Endpoints

| Endpoint       | Purpose       | Returns                                          |
| -------------- | ------------- | ------------------------------------------------ |
| `GET /health`  | Liveness      | `200 {"status": "ok"}`                           |
| `GET /ready`   | Readiness     | `200` with per-check detail, or `503` degraded   |

### Default Admin Login

After running `flask seed`:
- **Username:** `admin`
- **Password:** `admin`

*Change this immediately in production.*

---

## Serial Transports

Each device port specifies a **transport** type and **address**. Transports are configured per-port through the admin panel.

| Transport   | Address Format          | Use Case                                                     |
| ----------- | ----------------------- | ------------------------------------------------------------ |
| `serial`    | `/dev/ttyUSB0`          | Physical RS-232 adapter (USB, PCIe, onboard)                 |
| `pty`       | `/tmp/centurion_tty0`   | Pseudo-terminal (simulation, socat bridge)                   |
| `tcp`       | `host:port`             | Raw TCP — emulators, serial-to-Ethernet adapters             |
| `telnet`    | `host:port`             | Telnet — legacy terminal servers, some SIMH configs          |
| `rfc2217`   | `host:port`             | RFC 2217 remote serial with modem control signals            |

Baud rate, parity, and flow control apply to `serial`, `pty`, and `rfc2217` transports. They are ignored for `tcp` and `telnet` (the emulator or remote adapter handles the physical serial side).

### Connecting Emulated Systems

Vintage hardware is not required. Software emulators can be used as production targets:

```bash
# Start Open SIMH (PDP-11) exposing serial ports on TCP
simh-pdp11 pdp11.ini    # e.g., port 10023 = job queue, 10024 = interactive

# Start CPU7Plus (Centurion) exposing serial ports on TCP
cpu7plus centurion.ini  # e.g., port 10901 = job queue, 10902 = interactive
```

Then configure ports in the admin panel:

```
transport=tcp  dev_path=127.0.0.1:10023  purpose=job_queue       transfer_protocol=xmodem
transport=tcp  dev_path=127.0.0.1:10024  purpose=interactive    newline_mode=crlf
```

Emulated systems appear as first-class devices in the admin panel and function identically to physical hardware. See [SDD.md §10.5](SDD.md#105-connecting-emulated-systems) for multi-port setups, socat bridging, and RFC 2217 serial-to-Ethernet adapters.

---

## Configuration

### Environment

Configuration is loaded from environment variables, optionally sourced from a `.env` file (loaded automatically at startup via `python-dotenv`). Copy `.env.example` to `.env` and edit for your setup.

Key variables:

| Variable                   | Default                        | Description                            |
| -------------------------- | ------------------------------ | -------------------------------------- |
| `FLASK_ENV`                | `development`                  | `development`, `production`, `testing` |
| `SECRET_KEY`               | `change-me-in-production`      | Session signing key (required in prod) |
| `DATABASE_URL`             | `sqlite:///instance/retrobridge_dev.db` | SQLite database path          |
| `BACKUP_DIR`               | `backups/`                     | Database backup directory              |
| `BACKUP_RETENTION_DAYS`    | `30`                           | Max age before auto-pruning            |
| `BACKUP_RETENTION_COUNT`   | `10`                           | Max backups before auto-pruning        |

### Config Classes

Configuration classes live in `config.py`:

| Class         | Purpose                              |
| ------------- | ------------------------------------ |
| `DevConfig`   | Development (debug on, PTY defaults) |
| `ProdConfig`  | Production (real serial paths)       |
| `TestConfig`  | Testing (in-memory SQLite)           |

Activate with `FLASK_ENV` environment variable.

### SQLite Tuning

Production automatically enables **WAL mode** and performance pragmas (busy timeout, mmap I/O, cache size, FK enforcement, temp store). These are set per-connection by `retrobridge/sqlite_provision.py` and overridable via the `SQLITE_PRAGMAS` config dict.

### Production Startup Validation

When `FLASK_ENV=production`, the app validates at boot:

- **`SECRET_KEY`** — must be a unique, non-default value
- **Config values** — retention settings are positive integers, `BACKUP_DIR` is writable, `MAX_CONTENT_LENGTH` is >= 1 MiB
- **Database reachability** — runs `SELECT 1` against the configured URI; startup aborts if unreachable

These checks are skipped in `development` and `testing` modes.

Per-port serial settings (baud, parity, flow control, etc.) are managed through the admin panel and stored in the `device_ports` table.

---

## Deployment

Production deployment uses systemd + nginx. See [SDD.md §8](SDD.md#8-deployment-design) for:

- systemd unit files for the web app and per-device workers
- nginx configuration with TLS and WebSocket proxying
- udev rules for stable serial device symlinks
- logrotate configuration

Directory layout on disk:
```
/srv/retrobridge/
├── retrobridge/        # Application package
│   ├── transport.py    # Transport abstraction (serial, pty, tcp, telnet, rfc2217)
│   └── ...
├── deploy/             # Production deployment scripts
│   └── backup.py       # Standalone cron backup script
├── worker.py           # Worker daemon
├── cli.py              # Flask CLI commands
├── config.py           # Configuration classes
├── run.sh              # Dev convenience launcher (schema checks + PTY sims)
├── requirements.txt
├── wsgi.py             # Gunicorn entry point
├── instance/           # SQLite database (auto-created)
├── backups/            # Database backups (auto-created)
├── uploads/            # User program uploads
├── outputs/            # Job session capture logs
├── session_logs/       # Per-session terminal keystroke/output logs
└── logs/               # Application and worker logs
```

---

## Contributing

This is a community project — contributions are welcome!

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-thing`)
3. Make your changes
4. Run the tests (`pytest tests/ -v`)
5. Commit and push
6. Open a pull request

### Development Guidelines

- Follow the existing Flask blueprint pattern for new features
- Use SQLAlchemy ORM for all database access (no raw SQL in route handlers)
- Add tests for new functionality (`tests/unit/`, `tests/integration/`, or `tests/e2e/`)
- PTY simulation is available for testing without hardware

### Testing

```bash
# Run all tests
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# With coverage
pytest tests/ --cov=retrobridge --cov-report=html
```

---

## License

RetroBridge is licensed under the [GNU General Public License v3.0](LICENSE).

---

## Author

**Jacob C. Pfeiff** — [RedneckTech](https://github.com/RedneckTech)
