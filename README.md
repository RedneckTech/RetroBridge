# RetroBridge

**Bridge modern web workflows to vintage minicomputers over RS-232.**

RetroBridge is a Flask web application that lets users submit programs for batch execution on vintage minicomputers and interactively log into them through a browser-based terminal emulator — all over RS-232 serial connections.

Currently targets the **Centurion CPU-6** and **DEC PDP-11/44**, both multi-user, multi-port systems. Job-dedicated ports handle automated program transfers and output capture, while interactive ports provide real-time terminal sessions via WebSocket.

---

## Features

- **Job queue with scheduling** — Upload programs, queue them per-device, and let background workers handle serial transfer via XMODEM
- **Web-based interactive terminal** — Log into vintage systems through your browser using xterm.js + WebSocket, with full bidirectional serial bridging
- **Multi-port device support** — Each vintage machine can have multiple RS-232 ports, partitioned into job-queue and interactive pools
- **Per-port serial configuration** — Baud rate, parity, stop bits, flow control, and line-ending conversion configurable per port
- **Admin panel** — Manage users, devices, ports, jobs, terminal sessions, and global settings
- **PTY-based simulation** — Develop and test without hardware using built-in pseudo-terminal simulation for both job processing and terminal sessions
- **Role-based access control** — Regular users manage their own jobs and sessions; admins have full control
- **Audit logging** — Every byte sent and received on job ports is timestamped; optional keystroke logging for terminal sessions

---

## Architecture

```
Browser ──HTTPS──▶ nginx ──HTTP──▶ gunicorn ──▶ Flask App ──▶ SQLite (WAL)
                        └─WebSocket──▶ Flask-SocketIO (eventlet)

Worker (Centurion) ──RS-232──▶ Centurion CPU-6 (job ports)
Worker (PDP-11)    ──RS-232──▶ PDP-11/44      (job ports)
Terminal Sessions  ──RS-232──▶ Both machines   (interactive ports)
```

Workers communicate with the Flask app **only through the SQLite database** (poll/claim/update pattern). Terminal sessions bridge WebSocket ↔ RS-232 in real time via eventlet green threads.

---

## Tech Stack

| Layer          | Technology                                          |
| -------------- | --------------------------------------------------- |
| Backend        | Python 3.11+, Flask 3.x, Flask-SocketIO 5.x         |
| ORM / DB       | SQLAlchemy 2.0, SQLite (WAL mode)                   |
| Serial I/O     | pyserial 3.5, xmodem 0.4                            |
| Frontend       | Bootstrap 5, Jinja2, xterm.js 5.x                   |
| WebSocket      | Flask-SocketIO + eventlet                           |
| WSGI Server    | gunicorn                                            |
| Reverse Proxy  | nginx (TLS termination, WebSocket proxying)         |
| Process Mgmt   | systemd                                             |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Linux with systemd (for production deployment)
- RS-232 serial adapters (USB or PCIe) connected to vintage hardware — *or use PTY simulation for development*

### Setup

```bash
# Clone the repo
git clone git@github.com:RedneckTech/RetroBridge.git
cd RetroBridge

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Initialize the database
flask init-db

# Seed default devices and admin user
flask seed

# Start the dev server
flask run
```

### Development with Simulation (no hardware required)

```bash
# Run a simulated job worker (PTY-based, mimics vintage machine)
flask simulation-worker --device centurion

# In another terminal, start a PTY-based interactive terminal simulation
flask simulation-terminal --device centurion
```

### Default Admin Login

After running `flask seed`:
- **Username:** `admin`
- **Password:** `admin`

*Change this immediately in production.*

---

## Configuration

Configuration classes live in `config.py`:

| Class         | Purpose                              |
| ------------- | ------------------------------------ |
| `DevConfig`   | Development (debug on, PTY defaults) |
| `ProdConfig`  | Production (real serial paths)       |
| `TestConfig`  | Testing (in-memory SQLite)           |

Set via `FLASK_ENV` environment variable. Secrets (`SECRET_KEY`, etc.) go in `.env`.

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
├── worker.py           # Worker daemon
├── cli.py              # Flask CLI commands
├── config.py           # Configuration classes
├── requirements.txt
├── wsgi.py             # Gunicorn entry point
├── instance/           # SQLite database (auto-created)
├── uploads/            # User program uploads
├── outputs/            # Job session capture logs
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
