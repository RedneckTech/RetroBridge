# RetroBridge — Software Design Description

**Document Version:** 1.0
**Date:** 2026-05-28
**Author:** Jacob C. Pfeiff

---

## Table of Contents

1. [Introduction](#1-introduction)
   - 1.1 [Purpose](#11-purpose)
   - 1.2 [Scope](#12-scope)
   - 1.3 [Definitions and Acronyms](#13-definitions-and-acronyms)
   - 1.4 [References](#14-references)
   - 1.5 [Overview](#15-overview)
2. [Architectural Design](#2-architectural-design)
   - 2.1 [System Context Diagram](#21-system-context-diagram)
   - 2.2 [Process Model](#22-process-model)
   - 2.3 [Request/Response Flow](#23-requestresponse-flow)
3. [Module Decomposition](#3-module-decomposition)
   - 3.1 [Package: `retrobridge/__init__.py`](#31-package-retrobridge__init__py)
   - 3.2 [Blueprint: `retrobridge/auth/` — Authentication](#32-blueprint-retrobridgeauth--authentication)
   - 3.3 [Blueprint: `retrobridge/jobs/` — Job Management](#33-blueprint-retrobridgejobs--job-management)
   - 3.4 [Blueprint: `retrobridge/api/` — REST API](#34-blueprint-retrobridgeapi--rest-api)
   - 3.5 [Blueprint: `retrobridge/terminal/` — Interactive Terminal Sessions](#35-blueprint-retbridgeterminal--interactive-terminal-sessions)
   - 3.6 [Blueprint: `retrobridge/admin/` — Administration](#36-blueprint-retrobridgeadmin--administration)
   - 3.7 [Shared: `retrobridge/models.py`](#37-shared-retbridgemodelspy)
   - 3.8 [Templates: `retrobridge/templates/`](#38-templates-retbridgetemplates)
   - 3.9 [Static Assets: `retrobridge/static/`](#39-static-assets-retbridgestatic)
   - 3.10 [Worker: `worker.py` (Standalone)](#310-worker-workerpy-standalone)
   - 3.11 [CLI: `cli.py`](#311-cli-clipy)
4. [Dependency Description](#4-dependency-description)
   - 4.1 [Inter-module Dependencies](#41-inter-module-dependencies)
   - 4.2 [External Dependencies](#42-external-dependencies)
   - 4.3 [Inter-process Dependencies](#43-inter-process-dependencies)
5. [Data Design](#5-data-design)
   - 5.1 [User Model](#51-user-model)
   - 5.2 [Device Model](#52-device-model)
   - 5.3 [DevicePort Model](#53-deviceport-model)
   - 5.4 [Job Model](#54-job-model)
   - 5.5 [Job Status State Machine](#55-job-status-state-machine)
   - 5.6 [AdminSetting Model](#56-adminsetting-model)
   - 5.7 [TerminalSession Model](#57-terminalsession-model)
   - 5.8 [File Storage Layout](#58-file-storage-layout)
6. [Interface Design](#6-interface-design)
   - 6.1 [REST API Endpoints](#61-rest-api-endpoints)
   - 6.2 [WebSocket API (Flask-SocketIO)](#62-websocket-api-flask-socketio)
   - 6.3 [Web UI Pages](#63-web-ui-pages)
   - 6.4 [Serial Transport Interface](#64-serial-transport-interface)
7. [Detailed Design](#7-detailed-design)
   - 7.1 [Authentication Flow](#71-authentication-flow)
   - 7.2 [Job Upload Flow](#72-job-upload-flow)
   - 7.3 [Interactive Terminal Session Flow](#73-interactive-terminal-session-flow)
   - 7.4 [PTY Simulation for Development Testing](#74-pty-simulation-for-development-testing)
   - 7.5 [Admin Operations](#75-admin-operations)
8. [Deployment Design](#8-deployment-design)
   - 8.1 [Directory Structure](#81-directory-structure)
   - 8.2 [systemd Service Units](#82-systemd-service-units)
   - 8.3 [nginx Configuration](#83-nginx-configuration)
   - 8.4 [udev Rules](#84-udev-rules)
   - 8.5 [logrotate Configuration](#85-logrotate-configuration)
9. [Security Design](#9-security-design)
   - 9.1 [Authentication Security](#91-authentication-security)
   - 9.2 [Authorization](#92-authorization)
   - 9.3 [Input Validation and Injection Prevention](#93-input-validation-and-injection-prevention)
   - 9.4 [Rate Limiting](#94-rate-limiting)
   - 9.5 [Worker Privilege Separation](#95-worker-privilege-separation)
   - 9.6 [Network Isolation](#96-network-isolation)
   - 9.7 [Audit Logging](#97-audit-logging)
   - 9.8 [Terminal Session Security](#98-terminal-session-security)
10. [Testing Strategy](#10-testing-strategy)
   - 10.1 [Unit Tests](#101-unit-tests-testsunit)
   - 10.2 [Integration Tests](#102-integration-tests-testsintegration)
   - 10.3 [End-to-End Tests](#103-end-to-end-tests-testse2e)
- 10.4 [Hardware Dry-Run Tests](#104-hardware-dry-run-tests)
- 10.5 [Connecting Emulated Systems](#105-connecting-emulated-systems)
- 10.6 [Test Execution](#106-test-execution)

---

## 1. Introduction

### 1.1 Purpose

RetroBridge is a web application that enables users to submit programs for execution on vintage minicomputers (specifically a Centurion CPU-6 and a PDP-11/44) over RS-232 serial connections, and to interactively log into those systems via a web-based terminal emulator. It provides a job queue with scheduling, serial transfer, session output capture, real-time interactive terminal sessions, and user/device management via an admin panel. Both machines are multi-user, multi-port systems; RetroBridge allocates a subset of RS-232 ports for automated job processing and the remainder for interactive user terminal sessions — bridging modern web-based workflows with legacy serial-attached hardware.

### 1.2 Scope

| Included                                              | Excluded                                         |
| ----------------------------------------------------- | ------------------------------------------------ |
| Flask 3.x web application                             | Hardware-level maintenance of vintage machines   |
| Flask-SocketIO with WebSocket support                 | Multi-server clustering or horizontal scaling    |
| SQLAlchemy 2.0 ORM with SQLite backend                | Native mobile applications                       |
| Bootstrap 5 + Jinja2 templates                        | Firmware/loader development for target devices   |
| xterm.js web-based terminal emulator                  | Redis/RabbitMQ queue backends (v2 consideration) |
| Admin panel for user/device/job/port management       |                                                  |
| Background worker daemons for job-based serial I/O    |                                                  |
| Real-time interactive terminal sessions via WebSocket |                                                  |
| PTY-based simulation for dev/testing                  |                                                  |
| Python 3.11+                                          |                                                  |

### 1.3 Definitions and Acronyms

| Term      | Definition                                                                            |
| --------- | ------------------------------------------------------------------------------------- |
| Centurion | Centurion CPU-6 minicomputer, target vintage system (multi-port, multi-user)          |
| PDP-11    | DEC PDP-11/44 minicomputer, target vintage system (multi-port, multi-user)            |
| RS-232    | EIA RS-232 serial communication standard                                              |
| XMODEM    | Block-oriented file transfer protocol widely supported on vintage systems             |
| WebSocket | Full-duplex communication channel over a single TCP connection (RFC 6455)             |
| xterm.js  | Browser-based terminal emulator used for interactive terminal sessions                |
| PTY       | Pseudo-terminal, used to simulate a serial device in software                         |
| udev      | Linux device manager; used to create stable symlinks for USB and PCIe serial adapters |
| systemd   | Linux init system; manages Flask and worker processes as services                     |
| WAL       | Write-Ahead Logging; SQLite journal mode for improved concurrent read performance     |
| SSE       | Server-Sent Events; unidirectional push from server to browser for live updates       |
| WSGI      | Web Server Gateway Interface; Python web app-to-server protocol                       |
| RTS/CTS   | Request To Send / Clear To Send hardware flow control                                 |
| XON/XOFF  | Software flow control using ASCII control characters                                  |
| CR/LF     | Carriage Return / Line Feed; line ending conventions on vintage vs. modern systems    |

### 1.4 References

1. Flask 3.x documentation — https://flask.palletsprojects.com/
2. SQLAlchemy 2.0 documentation — https://docs.sqlalchemy.org/
3. pyserial documentation — https://pyserial.readthedocs.io/
4. XMODEM protocol specification — Christensen, W. (1977)
5. IEEE 1016-2009 — IEEE Standard for Information Technology — Systems Design — Software Design Descriptions

### 1.5 Overview

Section 2 presents the architectural design, including system context and process models for both job processing and interactive terminal sessions. 

Section 3 decomposes the system into modules and component packages, including the new terminal blueprint and session management. 

Section 4 maps dependencies between modules, external libraries (including Flask-SocketIO and xterm.js), and processes. 

Section 5 specifies the data design including models for devices, per-port configuration, jobs, terminal sessions, and file storage. 

Section 6 describes all external interfaces — REST APIs, WebSocket APIs, web UI pages, and serial protocols. 

Section 7 covers the detailed design of the auth flow, job upload flow, interactive terminal session flow, PTY simulation, and admin operations. 

Section 8 specifies deployment artifacts including systemd units, nginx configuration with WebSocket proxying, and udev rules for multi-port setups. 

Section 9 addresses security design across authentication, authorization, input validation, terminal session isolation, and privilege separation. 

Section 10 defines the testing strategy at unit, integration, and end-to-end levels including terminal session testing.

---

## 2. Architectural Design

### 2.1 System Context Diagram

```
                          ┌──────────────────────────────────────────┐
                          │            nginx (TLS + proxy)            │
                          └────┬──────────────┬──────────────────────┘
                               │ HTTP         │ WebSocket
                          ┌────▼────┐    ┌────▼──────────┐
                          │gunicorn │    │ Flask-SocketIO │
                          │(WSGI)   │    │ (eventlet)     │
                          └────┬────┘    └────┬───────────┘
                               │              │
                          ┌────▼──────────────▼──────┐
                          │    Flask Application      │
                          │  (REST + WebSocket)       │
                          └────────┬─────────────────┘
                                   │
                             [SQL queries]
                                   │
                          ┌────────▼─────────────────┐
                          │   SQLite DB (WAL mode)    │
                          └────────▲─────────────────┘
                                   │
                     ┌─────────────┼─────────────┐
                     │ [polled by] │             │ [reads port config]
                     │             │             │
           ┌─────────▼──────┐  ┌──▼──────────────▼────┐
           │ Job Workers     │  │ Terminal Session      │
           │ (systemd units) │  │ Manager (SocketIO bg) │
           └────────┬────────┘  └──────────┬───────────┘
                    │                      │
              [RS-232 job ports]     [RS-232 interactive ports]
                    │                      │
           ┌────────▼──────┐     ┌─────────▼──────────┐
           │   Centurion   │     │     PDP-11/44       │
           │ (2 job ports) │     │  (2 job ports)      │
           │(N interactive)│     │  (N interactive)    │
           └───────────────┘     └────────────────────┘
```

### 2.2 Process Model

| Process                                   | Role                                                                    | Managed By      | Count                |
| ----------------------------------------- | ----------------------------------------------------------------------- | --------------- | -------------------- |
| nginx                                     | TLS termination, reverse proxy, static file serving, WebSocket proxying | systemd         | 1                    |
| gunicorn (master)                         | WSGI server, spawns worker processes                                    | systemd         | 1                    |
| gunicorn (workers)                        | Handle HTTP requests, execute Flask REST routes                         | gunicorn master | 2–4                  |
| Flask-SocketIO (eventlet)                 | Handle WebSocket connections for interactive terminals                  | gunicorn master | 1 async worker       |
| retrobridge-worker@centurion              | Claim centurion jobs on job-dedicated ports, perform serial transfers   | systemd         | 1                    |
| retrobridge-worker@pdp11                  | Claim pdp11 jobs on job-dedicated ports, perform serial transfers       | systemd         | 1                    |
| Terminal session handler (per connection) | Bridges WebSocket ↔ RS-232 interactive port in real time                | Flask-SocketIO  | 1 per active session |

Inter-process communication for job processing is mediated through the SQLite database in WAL mode. Terminal sessions use WebSocket connections managed by Flask-SocketIO with eventlet async workers. The serial port bridging (WebSocket ↔ RS-232) runs in background threads spawned per active terminal session, reading from the serial port and emitting via WebSocket, and writing user keystrokes to the serial port.

### 2.3 Request/Response Flow

**Job Processing Flow:**

1. **User request**: Browser → nginx (TLS) → gunicorn → Flask route handler
2. **Upload**: Flask validates file, saves to `/srv/retrobridge/uploads/job-<id>/`, inserts Job row with `status='queued'`
3. **Worker**: Polls DB every 5 seconds, atomically claims queued jobs, opens serial port (job-dedicated), transfers file, captures output, updates Job status
4. **Status display**: Browser polls `/api/jobs/<id>/status` or uses SSE for live updates

**Interactive Terminal Flow:**

1. **User navigates** to `/terminal/<device_id>` — Flask renders the terminal page with an xterm.js instance
2. **WebSocket connection**: Browser establishes WebSocket to Flask-SocketIO at namespace `/terminal`
3. **Session request**: Client emits `request_session` event with `device_id`; server checks port availability, creates `TerminalSession` record, opens the RS-232 interactive port
4. **Bidirectional bridge**: 
   - Server spawns a background thread that continuously reads from the serial port and emits `terminal_output` events to the client
   - Client emits `terminal_input` events as the user types; server writes bytes directly to the serial port
5. **Termination**: On WebSocket disconnect, idle timeout, or max session duration, server closes the serial port, marks the session record as ended, and logs the session duration

---

## 3. Module Decomposition

### 3.1 Package: `retrobridge/__init__.py`

- Flask application factory (`create_app()`)
- Configuration loading from `config.py` (classes: `DevConfig`, `ProdConfig`, `TestConfig`)
- Blueprint registration for `auth`, `jobs`, `api`, `terminal`, and `admin`
- Flask-SocketIO initialization (`SocketIO(app, async_mode='eventlet')`)
- Error handlers: 404 (Not Found), 500 (Internal Server Error), 403 (Forbidden)
- SQLAlchemy initialization with Flask app context

### 3.2 Blueprint: `retrobridge/auth/` — Authentication

| File          | Responsibility                                                                                  |
| ------------- | ----------------------------------------------------------------------------------------------- |
| `__init__.py` | Blueprint `auth_bp`, URL prefix `/auth`                                                         |
| `models.py`   | User model (SQLAlchemy, shared via `retrobridge.models`)                                        |
| `routes.py`   | `GET/POST /auth/login`, `GET/POST /auth/register`, `GET /auth/logout`, `GET/POST /auth/profile` |
| `forms.py`    | `LoginForm`, `RegistrationForm`, `ProfileForm` (Flask-WTF)                                      |
| `utils.py`    | `load_user()` callback, `hash_password()`, `check_password()`, `login_required` integration     |

### 3.3 Blueprint: `retrobridge/jobs/` — Job Management

| File          | Responsibility                                                                                                                            |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `__init__.py` | Blueprint `jobs_bp`                                                                                                                       |
| `routes.py`   | `GET /` (dashboard), `GET/POST /jobs/new` (upload), `GET /jobs/<id>` (detail), `GET /jobs/<id>/download` (file), `POST /jobs/<id>/cancel` |
| `forms.py`    | `JobUploadForm` (device dropdown, file field, optional priority)                                                                          |
| `utils.py`    | `create_job()`, `get_job_status()`, `cancel_job()`, `get_user_quota()`, per-user rate limiting helper                                     |

### 3.4 Blueprint: `retrobridge/api/` — REST API

| File          | Responsibility                                                                                                                                          |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `__init__.py` | Blueprint `api_bp`, URL prefix `/api`                                                                                                                   |
| `routes.py`   | `GET /api/jobs` (paginated list), `GET /api/jobs/<id>/status` (JSON), `GET /api/jobs/<id>/output` (log stream), `GET /api/devices` (device status list) |

### 3.5 Blueprint: `retrobridge/terminal/` — Interactive Terminal Sessions

| File          | Responsibility                                                                                                                     |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `__init__.py` | Blueprint `terminal_bp`, URL prefix `/terminal`                                                                                    |
| `routes.py`   | `GET /terminal` (device selection page), `GET /terminal/<device_id>` (terminal emulator page with xterm.js)                        |
| `events.py`   | Flask-SocketIO event handlers: `connect`, `disconnect`, `request_session`, `terminal_input`, `terminal_resize`, `heartbeat`        |
| `utils.py`    | `allocate_port()`, `release_port()`, `create_session()`, `end_session()`, `bridge_serial_to_socket()`, session timeout/enforcement |

### 3.6 Blueprint: `retrobridge/admin/` — Administration

| File          | Responsibility                                                                                                                                                                                 |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `__init__.py` | Blueprint `admin_bp`, URL prefix `/admin`, `@admin_required` decorator applied to all routes                                                                                                   |
| `routes.py`   | `GET /admin/` (dashboard with stats), `GET/POST /admin/users`, `GET/POST /admin/devices`, `GET/POST /admin/device-ports`, `GET /admin/jobs`, `GET /admin/sessions`, `GET/POST /admin/settings` |
| `forms.py`    | `DeviceForm`, `DevicePortForm`, `UserEditForm`, `SettingsForm`                                                                                                                                 |

### 3.7 Shared: `retrobridge/models.py`

- SQLAlchemy `Base` declarative base
- Engine and session factory (`scoped_session` with `sessionmaker`)
- `init_db()` to create tables
- Models: `User`, `Device`, `DevicePort`, `Job`, `TerminalSession`, `AdminSetting`

### 3.8 Templates: `retrobridge/templates/`

| Template                | Purpose                                                                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `base.html`             | Bootstrap 5 navbar (role-aware: shows Admin link for admins, shows Terminal link for all users), flash message area, footer                                   |
| `auth/login.html`       | Login form with username/password fields, link to register                                                                                                    |
| `auth/register.html`    | Registration form: username, email, full name, password, confirm password                                                                                     |
| `auth/profile.html`     | Edit profile: email, full name, password change                                                                                                               |
| `jobs/dashboard.html`   | User's job table (status badges, dates, actions), device status cards (idle/busy, queue length)                                                               |
| `jobs/new.html`         | Upload form: device dropdown (filtered to enabled devices), file picker, optional priority                                                                    |
| `jobs/detail.html`      | Job metadata section, status badge with color coding, timestamps, session log viewer in `<pre>` block, download button, cancel button (conditional on status) |
| `jobs/output.html`      | Raw session log display, full-width `<pre>`                                                                                                                   |
| `terminal/index.html`   | Device selection page: lists devices with available interactive ports, shows session in progress if applicable                                                |
| `terminal/session.html` | Full-page xterm.js terminal emulator with status bar (device name, port, connected duration), disconnect button                                               |
| `admin/dashboard.html`  | Summary stats: total users, total jobs, running jobs, active terminal sessions, device status overview                                                        |
| `admin/users.html`      | User table: username, email, admin toggle, job count, session count, quota, actions (edit/delete)                                                             |
| `admin/devices.html`    | Device table with full serial config, port listing, enable/disable toggle, add/edit forms                                                                     |
| `admin/sessions.html`   | Active and historical terminal session list: user, device, port, start time, duration, status, force-disconnect action                                        |
| `admin/settings.html`   | Global settings form: max upload size, default quotas, idle sleep interval, terminal session limits                                                           |

### 3.9 Static Assets: `retrobridge/static/`

| File             | Purpose                                                                                                                        |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `css/style.css`  | Custom styles layered on Bootstrap 5: status badge colors, log viewer formatting, dashboard card styling, terminal container   |
| `js/main.js`     | AJAX polling for job status updates (configurable interval), SSE client for live log streaming, cancel job confirmation dialog |
| `js/terminal.js` | xterm.js initialization, WebSocket connection management, resize handling, heartbeat keep-alive, session UI controls           |

Bootstrap 5.3 CSS and JS are loaded via CDN in `base.html`. xterm.js and its addons (xterm-addon-fit, xterm-addon-web-links) are loaded via CDN on the terminal page.

### 3.10 Worker: `worker.py` (Standalone)

A standalone Python script outside the Flask application package:

- **`claim_job(conn, device_id)`**: Opens `BEGIN IMMEDIATE` transaction, checks device concurrency limit (only counting job-dedicated ports), atomically selects and updates the next queued job to `running`
- **`run_job_on_device(device, port)`**: Opens serial port per port config, executes pre-transfer commands, performs XMODEM send, captures output until idle timeout, handles timeouts and errors
- **`worker_loop(device_name)`**: Infinite poll loop — claim, run, update status, sleep. Handles SIGTERM/SIGINT for graceful shutdown
- **Logging**: Writes to `/var/log/retrobridge/worker-<device>.log` with timestamps and log levels

### 3.11 CLI: `cli.py`

Flask CLI commands registered via `app.cli`:

| Command                                   | Purpose                                                                                  |
| ----------------------------------------- | ---------------------------------------------------------------------------------------- |
| `flask init-db`                           | Create all tables in SQLite database                                                     |
| `flask seed`                              | Seed database: create admin user, two default devices (Centurion, PDP-11) with PTY paths |
| `flask simulation-worker --device <name>` | Launch a PTY-based simulation worker for testing without hardware                        |

---

## 4. Dependency Description

### 4.1 Inter-module Dependencies

```
retrobridge.models (User, Device, DevicePort, Job, TerminalSession, AdminSetting)
       │
       ├── retrobridge.auth ──────── (imports User, uses Flask-Login)
       │       │
       │       └── login_required + admin_required decorators ──── consumed by all other blueprints
       │
       ├── retrobridge.jobs ──────── (imports Job, Device, DevicePort, User; uses auth.utils)
       │
       ├── retrobridge.api ───────── (imports Job, Device, DevicePort; uses auth.utils)
       │
       ├── retrobridge.terminal ──── (imports Device, DevicePort, TerminalSession; uses auth.utils + SocketIO)
       │
       ├── retrobridge.admin ─────── (imports all models; uses auth.utils + admin_required)
       │
       └── worker.py ─────────────── (imports SQLAlchemy models directly; no Flask or SocketIO dependency)
```

### 4.2 External Dependencies

`requirements.txt`:

```
Flask==3.0.*
Flask-Login==0.6.*
Flask-WTF==1.2.*
Flask-SocketIO==5.3.*
SQLAlchemy==2.0.*
pyserial==3.5
xmodem==0.4.*
gunicorn==21.*
eventlet==0.36.*
werkzeug==3.0.*
email-validator==2.1.*
```

| Dependency      | Version | Purpose                                                  |
| --------------- | ------- | -------------------------------------------------------- |
| Flask           | 3.0.x   | Web framework                                            |
| Flask-Login     | 0.6.x   | Session management, `current_user`, `login_required`     |
| Flask-WTF       | 1.2.x   | CSRF protection, form validation/rendering               |
| Flask-SocketIO  | 5.3.x   | WebSocket support for interactive terminal sessions      |
| SQLAlchemy      | 2.0.x   | ORM, connection pooling, schema management               |
| pyserial        | 3.5     | Serial port I/O for worker processes and terminal bridge |
| xmodem          | 0.4.x   | XMODEM file transfer protocol implementation             |
| gunicorn        | 21.x    | Production WSGI server                                   |
| eventlet        | 0.36.x  | Async worker for Flask-SocketIO (monkey-patches stdlib)  |
| werkzeug        | 3.0.x   | Password hashing utilities (bundled with Flask)          |
| email-validator | 2.1.x   | Email format validation in forms                         |

**System-level dependencies:**

| Dependency  | Purpose                                                            |
| ----------- | ------------------------------------------------------------------ |
| socat       | Bridge emulator TCP serial ports to PTY devices for RetroBridge   |
| screen      | Detached terminal session management (optional, for emulator mgmt) |
| udev        | Stable device symlinks for physical USB/PCIe serial adapters       |

**Client-side dependencies (CDN):**

| Library                     | Purpose                                    |
| --------------------------- | ------------------------------------------ |
| xterm.js 5.x                | Browser-based terminal emulator            |
| xterm-addon-fit 0.8.x       | Auto-resize terminal to container          |
| xterm-addon-web-links 0.9.x | Clickable URL detection in terminal output |

### 4.3 Inter-process Dependencies

```
Flask Application (gunicorn workers)
    │
    │  Reads/Writes
    ▼
SQLite DB (WAL mode, timeout=10)
    ▲
    │  Polls/Claims/Updates
    │
Worker Processes (systemd units)
```

- SQLite is configured with WAL journal mode for concurrent read performance
- `timeout=10` on worker connections to handle busy database gracefully
- Flask uses SQLAlchemy `scoped_session` per request; workers use raw `sqlite3` or SQLAlchemy `Session` per loop iteration
- Job workers communicate via the database only (poll/claim/update)
- Terminal session manager (Flask-SocketIO) reads `DevicePort` config from DB at session start, manages session records in DB, but the serial-WebSocket bridge runs entirely in-memory using eventlet green threads

---

## 5. Data Design

### 5.1 User Model

| Column                  | Type        | Constraints                |
| ----------------------- | ----------- | -------------------------- |
| `id`                    | Integer     | Primary key, autoincrement |
| `username`              | String(64)  | UNIQUE, NOT NULL, indexed  |
| `email`                 | String(120) | UNIQUE, NOT NULL           |
| `password_hash`         | String(256) | NOT NULL                   |
| `full_name`             | String(128) | Nullable                   |
| `is_admin`              | Boolean     | Default False              |
| `max_queued_jobs`       | Integer     | Default 3                  |
| `max_terminal_sessions` | Integer     | Default 1                  |
| `created_at`            | DateTime    | Default `datetime.utcnow`  |
| `last_login`            | DateTime    | Nullable                   |

**Relationships:** `User.jobs` — one-to-many to `Job` (`user_id` FK). `User.terminal_sessions` — one-to-many to `TerminalSession` (`user_id` FK).

### 5.2 Device Model

The Device represents a vintage machine. Serial configuration lives at the port level (see DevicePort). Device-level fields define the machine identity and shared defaults inherited by ports.

| Column         | Type       | Constraints                |
| -------------- | ---------- | -------------------------- |
| `id`           | Integer    | Primary key, autoincrement |
| `name`         | String(32) | UNIQUE, NOT NULL           |
| `display_name` | String(64) | E.g. "Centurion CPU-6"     |
| `is_enabled`   | Boolean    | Default True               |
| `created_at`   | DateTime   | Default `datetime.utcnow`  |

**Relationships:** `Device.ports` — one-to-many to `DevicePort` (`device_id` FK). `Device.jobs` — one-to-many to `Job` (`device_id` FK).

### 5.3 DevicePort Model

Each Device has multiple RS-232 ports. Each port is assigned a `purpose` that determines how RetroBridge uses it. The serial configuration is stored per-port since different ports on the same machine may have different baud rates, parity, etc.

| Column                 | Type        | Constraints                                                               |
| ---------------------- | ----------- | ------------------------------------------------------------------------- |
| `id`                   | Integer     | Primary key, autoincrement                                                |
| `device_id`            | Integer     | ForeignKey → `devices.id`, NOT NULL                                       |
| `port_label`           | String(32)  | E.g. "TTY0", "TTY1", "CONSOLE"                                            |
| `transport`            | String(16)  | Default `'serial'` (valid: serial, pty, tcp, telnet, rfc2217)             |
| `dev_path`             | String(256) | Address/URI for the transport: `/dev/ttyUSB0`, `/tmp/pty`, `host:port`    |
| `purpose`              | String(16)  | `'job_queue'` or `'interactive'`                                          |
| `baud`                 | Integer     | Default 9600                                                              |
| `data_bits`            | Integer     | Default 8                                                                 |
| `parity`               | String(1)   | Default 'N' (valid: N, E, O, M, S)                                        |
| `stop_bits`            | Integer     | Default 1                                                                 |
| `flow_control`         | String(8)   | Default 'none' (valid: none, rtscts, xonxoff)                             |
| `newline_mode`         | String(4)   | Default 'crlf' (valid: cr, lf, crlf)                                      |
| `max_concurrent_jobs`  | Integer     | Default 1 (meaningful only for job_queue ports; always 1 for interactive) |
| `max_runtime_seconds`  | Integer     | Default 300 (job_queue) / 3600 (interactive session max duration)         |
| `idle_timeout_seconds` | Integer     | Default 5 (job_queue) / 300 (interactive session idle timeout)            |
| `pre_transfer_cmds`    | Text        | JSON array — only used for job_queue ports                                |
| `post_transfer_cmds`   | Text        | JSON array — only used for job_queue ports                                |
| `transfer_protocol`    | String(16)  | Default 'xmodem' (only used for job_queue ports)                          |
| `is_enabled`           | Boolean     | Default True                                                              |
| `created_at`           | DateTime    | Default `datetime.utcnow`                                                 |

**Relationships:** `DevicePort.device` — many-to-one to `Device`. `DevicePort.terminal_sessions` — one-to-many to `TerminalSession` (interactive ports only).

### 5.4 Job Model

| Column              | Type        | Constraints                              |
| ------------------- | ----------- | ---------------------------------------- |
| `id`                | Integer     | Primary key, autoincrement               |
| `user_id`           | Integer     | ForeignKey → `users.id`, NOT NULL        |
| `device_id`         | Integer     | ForeignKey → `devices.id`, NOT NULL      |
| `port_id`           | Integer     | ForeignKey → `device_ports.id`, NOT NULL |
| `original_filename` | String(256) | NOT NULL                                 |
| `stored_filename`   | String(512) | Path to uploaded file on disk            |
| `status`            | String(16)  | Default 'queued'                         |
| `priority`          | Integer     | Default 0                                |
| `file_size_bytes`   | Integer     | Nullable                                 |
| `created_at`        | DateTime    | Default `datetime.utcnow`                |
| `started_at`        | DateTime    | Nullable                                 |
| `finished_at`       | DateTime    | Nullable                                 |
| `runtime_seconds`   | Integer     | Nullable                                 |
| `exit_code`         | Integer     | Nullable                                 |
| `output_path`       | String(512) | Path to session log on disk              |
| `error_message`     | Text        | Nullable                                 |
| `worker_pid`        | Integer     | Nullable                                 |

**Indexes:**

- Composite index on `(status, created_at)` for efficient worker polling
- Composite index on `(port_id, status)` for per-port concurrency checks

### 5.5 Job Status State Machine

```
                        ┌─────────┐
                        │ queued  │
                        └────┬────┘
                             │ worker calls claim_job()
                        ┌────▼────┐     ┌──────────┐
                        │ running ├────►│ canceled │ (admin force-cancel)
                        └────┬────┘     └──────────┘
                    ┌────────┴────────┐
              ┌─────▼──────┐   ┌──────▼──────┐
              │ completed  │   │   failed    │
              └────────────┘   └─────────────┘
```

**Transitions:**

| From    | To        | Trigger                                           |
| ------- | --------- | ------------------------------------------------- |
| queued  | running   | Worker atomically claims job                      |
| queued  | canceled  | User cancels their own job (owner only)           |
| running | completed | Worker finishes transfer and capture successfully |
| running | failed    | Transfer error, timeout, or unhandled exception   |
| running | canceled  | Admin force-cancels with `force=true` flag        |

### 5.6 AdminSetting Model

| Column        | Type        | Constraints |
| ------------- | ----------- | ----------- |
| `key`         | String(64)  | Primary key |
| `value`       | Text        | NOT NULL    |
| `description` | String(256) | Nullable    |

**Default keys:** `MAX_UPLOAD_SIZE_BYTES` (8388608), `DEFAULT_MAX_QUEUED_JOBS` (3), `DEFAULT_MAX_TERMINAL_SESSIONS` (1), `IDLE_SLEEP_SECONDS` (5), `MAX_JOBS_PER_HOUR` (10), `MAX_TERMINAL_SESSION_SECONDS` (3600), `TERMINAL_IDLE_TIMEOUT_SECONDS` (300).

### 5.7 TerminalSession Model

| Column              | Type       | Constraints                                                           |
| ------------------- | ---------- | --------------------------------------------------------------------- |
| `id`                | Integer    | Primary key, autoincrement                                            |
| `user_id`           | Integer    | ForeignKey → `users.id`, NOT NULL                                     |
| `device_id`         | Integer    | ForeignKey → `devices.id`, NOT NULL                                   |
| `port_id`           | Integer    | ForeignKey → `device_ports.id`, NOT NULL                              |
| `status`            | String(16) | Default 'active'                                                      |
| `connected_at`      | DateTime   | Default `datetime.utcnow`                                             |
| `disconnected_at`   | DateTime   | Nullable                                                              |
| `duration_seconds`  | Integer    | Nullable, computed at disconnect                                      |
| `bytes_sent`        | Integer    | Default 0, cumulative count                                           |
| `bytes_received`    | Integer    | Default 0, cumulative count                                           |
| `disconnect_reason` | String(64) | Nullable (user_disconnect, timeout, idle_timeout, admin_force, error) |

**Terminal Session State Machine:**

```
                  ┌────────┐
          ┌──────►│ active ├──────┐
          │       └────────┘      │
          │         │  │          │
          │    ┌────┘  └────┐     │
          │    ▼            ▼     │
 ┌────────┴────────┐  ┌──────────┴──────────┐
 │ disconnected    │  │ disconnected         │
 │ (user_disconnect)│  │ (timeout / idle /   │
 └─────────────────┘  │  admin_force / error)│
                      └─────────────────────┘
```

### 5.8 File Storage Layout

```
/srv/retrobridge/
├── instance/
│   └── retrobridge.db              # SQLite database file
├── uploads/
│   └── job-<id>/
│       └── program.bin             # Renamed uploaded program file
├── outputs/
│   └── job-<id>/
│       └── session.log             # Timestamped serial session capture
├── session_logs/                   # Interactive terminal session logs (optional)
│   └── session-<id>/
│       └── terminal.log            # Timestamped keystroke/output log
├── logs/
│   ├── app.log                     # Flask/gunicorn application logs
│   ├── worker-centurion.log        # Centurion worker debug log
│   └── worker-pdp11.log            # PDP-11 worker debug log
├── retrobridge/                    # Application package (source code)
├── worker.py                       # Worker daemon entry point
├── cli.py                          # Flask CLI entry point
├── config.py                       # Configuration classes
├── requirements.txt
├── wsgi.py                         # Gunicorn entry point
└── .env                            # Environment secrets (SECRET_KEY, etc.)
```

---

## 6. Interface Design

### 6.1 REST API Endpoints

| Method   | Path                            | Auth         | Request                                                               | Response                                                                                                                                                                                             |
| -------- | ------------------------------- | ------------ | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET`    | `/api/jobs`                     | user         | Query: `?page=1&per_page=20`                                          | `{ "jobs": [...], "total": int, "pages": int, "current_page": int }`                                                                                                                                 |
| `GET`    | `/api/jobs/<id>/status`         | user (owner) | —                                                                     | `{ "id": int, "status": str, "device": str, "created_at": str, "started_at": str \| null, "finished_at": str \| null, "runtime_seconds": int \| null, "error_message": str \| null }`                |
| `GET`    | `/api/jobs/<id>/output`         | user (owner) | Query: `?tail=1000` (optional, last N lines)                          | `text/plain` streaming response or JSON `{ "lines": [...] }`                                                                                                                                         |
| `GET`    | `/api/devices`                  | user         | —                                                                     | `{ "devices": [{ "id": int, "name": str, "display_name": str, "is_enabled": bool, "interactive_ports_available": int, "interactive_ports_total": int, "queue_length": int, "running_jobs": int }] }` |
| `GET`    | `/api/devices/<id>/ports`       | user         | —                                                                     | `{ "ports": [{ "id": int, "label": str, "purpose": str, "is_enabled": bool, "in_use": bool, "baud": int, ... }] }`                                                                                   |
| `POST`   | `/api/jobs`                     | user         | Multipart form: `file`, `device_id` (int), `priority` (int, optional) | Redirect (302) on success, or JSON `{ "job_id": int }` if `Accept: application/json`                                                                                                                 |
| `POST`   | `/api/jobs/<id>/cancel`         | user (owner) | —                                                                     | `{ "success": true, "message": "Job canceled" }` or `{ "success": false, "message": "Cannot cancel running job" }`                                                                                   |
| `GET`    | `/api/sessions/active`          | admin        | —                                                                     | `{ "sessions": [{ "id": int, "user": str, "device": str, "port": str, "connected_at": str, "duration": int }] }`                                                                                     |
| `POST`   | `/api/sessions/<id>/disconnect` | admin        | —                                                                     | `{ "success": true, "message": "Session terminated" }`                                                                                                                                               |
| `POST`   | `/api/admin/jobs/<id>/cancel`   | admin        | JSON: `{ "force": true }`                                             | `{ "success": true, "message": "Job force-canceled" }`                                                                                                                                               |
| `DELETE` | `/api/admin/users/<id>`         | admin        | —                                                                     | `{ "success": true }` or `{ "success": false, "message": "Cannot delete self" }`                                                                                                                     |

### 6.2 WebSocket API (Flask-SocketIO)

**Namespace:** `/terminal`

| Event (Client → Server) | Payload                        | Description                                                                                                                  |
| ----------------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| `request_session`       | `{ "device_id": int }`         | Request an interactive terminal session on the specified device. Server responds with `session_granted` or `session_denied`. |
| `terminal_input`        | `{ "data": str }`              | User keystrokes to be written to the serial port.                                                                            |
| `terminal_resize`       | `{ "cols": int, "rows": int }` | Terminal window resize event (forwarded to vintage system if supported via SIGWINCH or equivalent).                          |
| `heartbeat`             | `{}`                           | Client keep-alive ping; server echoes with `heartbeat_ack`.                                                                  |

| Event (Server → Client) | Payload                                                                                  | Description                                                                          |
| ----------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `session_granted`       | `{ "session_id": int, "device_name": str, "port_label": str, "cols": int, "rows": int }` | Session successfully allocated; terminal emulator is ready.                          |
| `session_denied`        | `{ "reason": str }`                                                                      | Session request rejected (no ports available, quota exceeded, device disabled).      |
| `terminal_output`       | `{ "data": str }`                                                                        | Raw bytes read from the serial port, forwarded to the xterm.js terminal for display. |
| `heartbeat_ack`         | `{}`                                                                                     | Response to client heartbeat.                                                        |
| `session_closed`        | `{ "reason": str }`                                                                      | Server-initiated session closure (timeout, idle timeout, admin force-disconnect).    |

### 6.3 Web UI Pages

| Route                            | Template                | Auth Required | Description                                                                                                                                                    |
| -------------------------------- | ----------------------- | ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /`                          | `jobs/dashboard.html`   | user          | Dashboard: user's jobs table with status badges, device status cards (idle/busy, queue length), quota indicator                                                |
| `GET /auth/login`                | `auth/login.html`       | none          | Login form: username, password, remember-me checkbox                                                                                                           |
| `POST /auth/login`               | (redirect)              | none          | Authenticate credentials, create Flask-Login session, redirect to `/`                                                                                          |
| `GET /auth/register`             | `auth/register.html`    | none          | Registration form: username, email, full name, password, confirm password                                                                                      |
| `POST /auth/register`            | (redirect)              | none          | Validate form, create user, auto-login, redirect to `/`                                                                                                        |
| `GET /auth/logout`               | (redirect)              | user          | Clear session, redirect to `/auth/login`                                                                                                                       |
| `GET /auth/profile`              | `auth/profile.html`     | user          | View and edit profile: email, full name, change password                                                                                                       |
| `POST /auth/profile`             | (redirect)              | user          | Update profile fields, re-render with flash message                                                                                                            |
| `GET /terminal`                  | `terminal/index.html`   | user          | Device selection page: list devices with available interactive ports, show active session if user already has one                                              |
| `GET /terminal/<device_id>`      | `terminal/session.html` | user          | Full-page xterm.js terminal emulator connected via WebSocket to the device's interactive port; status bar shows device name, port, session duration            |
| `GET /jobs/new`                  | `jobs/new.html`         | user          | Upload form: device dropdown (enabled devices only), file input (restricted extensions), optional priority field                                               |
| `POST /jobs/new`                 | (redirect)              | user          | Validate file size/type, check user quota, save file, create job, redirect to job detail                                                                       |
| `GET /jobs/<id>`                 | `jobs/detail.html`      | user (owner)  | Job metadata panel, status badge (color-coded), timestamps, session log viewer (`<pre>` with line numbers), download link, cancel button (if status is queued) |
| `GET /jobs/<id>/download`        | (file download)         | user (owner)  | Download `session.log` as `attachment; filename="job-<id>-output.log"`                                                                                         |
| `GET /admin`                     | `admin/dashboard.html`  | admin         | Summary cards: total users, total jobs, running jobs, active terminal sessions, device status table                                                            |
| `GET /admin/users`               | `admin/users.html`      | admin         | Paginated user table: username, email, admin badge, job count, terminal session count, quota, edit/delete actions                                              |
| `POST /admin/users/<id>`         | (redirect)              | admin         | Update user: toggle admin, set quotas                                                                                                                          |
| `DELETE /admin/users/<id>`       | (redirect)              | admin         | Delete user (reassign or cascade jobs/sessions)                                                                                                                |
| `GET /admin/devices`             | `admin/devices.html`    | admin         | Device table, per-device port listing with purpose labels, enable/disable toggle, test connection button                                                       |
| `POST /admin/devices/<id>/ports` | (redirect)              | admin         | Add/edit device port configuration                                                                                                                             |
| `GET /admin/sessions`            | `admin/sessions.html`   | admin         | Active and historical terminal sessions: user, device, port, start time, duration, status, force-disconnect action                                             |
| `GET /admin/settings`            | `admin/settings.html`   | admin         | Global settings form populated from `AdminSetting` table: upload limits, quotas, terminal session timeouts                                                     |
| `POST /admin/settings`           | (redirect)              | admin         | Save settings, redirect with flash message                                                                                                                     |

### 6.4 Serial Transport Interface

Each `DevicePort` specifies a **transport** that determines how RetroBridge opens the serial connection. The transport is selected via the `transport` column and its address/URI is stored in `dev_path`. Serial line parameters (baud, parity, flow control, etc.) are configured per-port in the same `DevicePort` record and apply regardless of transport type.

#### Supported Transport Types

| Transport   | `dev_path` Format          | Description                                                                               |
| ----------- | -------------------------- | ----------------------------------------------------------------------------------------- |
| `serial`    | `/dev/ttyUSB0`             | Local RS-232 device via USB, PCIe, or onboard serial port. Opened with `pyserial`.        |
| `pty`       | `/tmp/centurion_tty0`      | Pseudo-terminal (PTY) for simulation or `socat`-bridged emulator ports.                   |
| `tcp`       | `host:port` or `host port` | Raw TCP socket connection. Ideal for emulators, serial-to-Ethernet adapters, and terminal servers. |
| `telnet`    | `host:port` or `host port` | Telnet protocol connection. Used by some vintage terminal servers and legacy emulators that speak telnet negotiation. |
| `rfc2217`   | `host:port` or `host port` | RFC 2217 (Telnet COM Port Control) remote serial port. Exposes full modem control signals (RTS/CTS, DTR/DSR) over TCP via `pyserial`'s `rfc2217://` URL scheme. |

#### Transport Selection Logic

RetroBridge resolves the transport at connection time:

1. If `transport` is `pty`, open the filesystem path directly with `pyserial` (used for simulation and socat bridges).
2. If `transport` is `serial`, open the local device file with `pyserial` (physical RS-232 ports).
3. If `transport` is `tcp`, open a raw TCP socket via `socket.create_connection()` and wrap it with `pyserial.serial_for_url('socket://host:port')` or direct socket I/O to avoid unnecessary pyserial abstractions.
4. If `transport` is `telnet`, connect via TCP and perform minimal telnet option negotiation (reject WILL DO for linemode, echo, suppress go-ahead), then treat as raw bidirectional stream.
5. If `transport` is `rfc2217`, use `pyserial.serial_for_url('rfc2217://host:port')` which handles the RFC 2217 control protocol for baud rate negotiation and modem line access.

#### Transport and Baud Rate

- **serial / pty / rfc2217**: Baud rate, data bits, parity, stop bits, and flow control from `DevicePort` are applied when opening the connection.
- **tcp / telnet**: Baud and line parameters are not meaningful on the TCP side (the emulator or remote serial adapter handles the physical serial side). These `DevicePort` fields are ignored; only `dev_path`, `max_runtime_seconds`, and `idle_timeout_seconds` are used.

#### Shared Port Parameters

All transports share the following `DevicePort` parameters:

**Job queue ports (`purpose='job_queue'`):**

| Parameter              | Description                                                                    | Source                            |
| ---------------------- | ------------------------------------------------------------------------------ | --------------------------------- |
| `transport`            | Connection transport type                                                      | `DevicePort.transport`            |
| `dev_path`             | Address/URI for the selected transport                                         | `DevicePort.dev_path`             |
| `baud`                 | Baud rate (e.g., 9600, 19200) — ignored for tcp/telnet                         | `DevicePort.baud`                 |
| `data_bits`            | Data bits per frame (5–8) — ignored for tcp/telnet                             | `DevicePort.data_bits`            |
| `parity`               | Parity bit (N, E, O, M, S) — ignored for tcp/telnet                            | `DevicePort.parity`               |
| `stop_bits`            | Stop bits (1, 1.5, 2) — ignored for tcp/telnet                                 | `DevicePort.stop_bits`            |
| `flow_control`         | 'none', 'rtscts', or 'xonxoff' — ignored for tcp/telnet                        | `DevicePort.flow_control`         |
| `newline_mode`         | Line ending conversion: 'cr', 'lf', or 'crlf'                                  | `DevicePort.newline_mode`         |
| `transfer_protocol`    | File transfer protocol; initially 'xmodem'                                     | `DevicePort.transfer_protocol`    |
| `pre_transfer_cmds`    | JSON array of strings sent before file transfer (e.g., `["\r", "XMODEM R\r"]`) | `DevicePort.pre_transfer_cmds`    |
| `post_transfer_cmds`   | JSON array of strings sent after file transfer (e.g., `["RUN\r"]`)             | `DevicePort.post_transfer_cmds`   |
| `max_runtime_seconds`  | Maximum seconds before a job is timed out                                      | `DevicePort.max_runtime_seconds`  |
| `idle_timeout_seconds` | Seconds of serial silence before capture is considered complete                | `DevicePort.idle_timeout_seconds` |

**Interactive ports (`purpose='interactive'`):**

| Parameter              | Description                                                               | Source                            |
| ---------------------- | ------------------------------------------------------------------------- | --------------------------------- |
| `transport`            | Connection transport type                                                 | `DevicePort.transport`            |
| `dev_path`             | Address/URI for the selected transport                                    | `DevicePort.dev_path`             |
| `baud`                 | Baud rate — ignored for tcp/telnet                                        | `DevicePort.baud`                 |
| `data_bits`            | Data bits per frame — ignored for tcp/telnet                              | `DevicePort.data_bits`            |
| `parity`               | Parity bit — ignored for tcp/telnet                                       | `DevicePort.parity`               |
| `stop_bits`            | Stop bits — ignored for tcp/telnet                                        | `DevicePort.stop_bits`            |
| `flow_control`         | Hardware or software flow control — ignored for tcp/telnet                | `DevicePort.flow_control`         |
| `newline_mode`         | Line ending conversion for terminal display                               | `DevicePort.newline_mode`         |
| `max_runtime_seconds`  | Maximum terminal session duration (default 3600 = 1 hour)                 | `DevicePort.max_runtime_seconds`  |
| `idle_timeout_seconds` | Seconds of serial inactivity before auto-disconnect (default 300 = 5 min) | `DevicePort.idle_timeout_seconds` |

#### Example Port Configurations

**Physical RS-232 USB adapter (Centurion job port):**
```
transport=serial  dev_path=/dev/centurion_tty0  baud=9600  parity=N  flow_control=rtscts
```

**SIMH PDP-11 emulator via TCP (interactive port):**
```
transport=tcp  dev_path=127.0.0.1:10023  newline_mode=crlf
```

**CPU7Plus emulator via socat PTY bridge (job port):**
```
transport=pty  dev_path=/tmp/cpu7plus_job  baud=9600
```

**Serial-to-Ethernet adapter (RFC 2217, interacting with real hardware over LAN):**
```
transport=rfc2217  dev_path=192.168.1.50:4001  baud=19200  parity=N  flow_control=rtscts
```

**Legacy terminal server (telnet, interactive port):**
```
transport=telnet  dev_path=192.168.1.10:23  newline_mode=crlf
```

**Byte logging:**

- **Job queue ports**: Every byte read from or written to the serial port is timestamped and appended to `outputs/job-<id>/session.log` for audit and debugging.
- **Interactive ports**: Bytes are streamed in real time via WebSocket to the browser terminal. Optional session logging to `session_logs/session-<id>/terminal.log` can be enabled per device via admin settings.

---

## 7. Detailed Design

### 7.1 Authentication Flow

**Registration:**

1. User submits `RegistrationForm` with username, email, full name, password, and password confirmation
2. Server-side validation: username uniqueness, email uniqueness, email format (via `email-validator`), password minimum 8 characters with at least 1 uppercase and 1 digit, passwords match
3. On success: hash password with `werkzeug.security.generate_password_hash()` (pbkdf2:sha256 with salt), create `User` row, call `flask_login.login_user(user)`, redirect to dashboard
4. On failure: re-render form with field-level error messages

**Login:**

1. User submits `LoginForm` with username and password
2. Query `User` by username; if not found or `check_password_hash()` fails, flash "Invalid username or password" and re-render
3. On success: call `login_user(user, remember=form.remember_me.data)`, update `last_login` timestamp, redirect to dashboard (or `next` parameter if present)
4. `flask_login.session_protection = 'strong'` is configured to re-authenticate on IP or user-agent changes

**Session Management:**

- `flask_login.LoginManager` configured in app factory
- `user_loader` callback queries `User` by integer ID
- Session timeout: `REMEMBER_COOKIE_DURATION = timedelta(hours=24)` (configurable)
- Logout clears session and redirects to login page

**Authorization Decorators:**

- `@login_required` — standard Flask-Login; redirects unauthenticated users to login
- `@admin_required` — custom decorator wrapping `@login_required` that additionally checks `current_user.is_admin`, returns 403 if not admin
- Job ownership: `GET /jobs/<id>` and `POST /jobs/<id>/cancel` additionally verify `job.user_id == current_user.id` unless user is admin

### 7.2 Job Upload Flow

1. Authenticated user navigates to `GET /jobs/new`
2. Form renders device dropdown populated from `Device.query.filter_by(is_enabled=True).all()` — shows display name and current availability
3. User selects device, chooses file, optionally sets priority (0–9)
4. On submit (`POST /jobs/new`):
   - **File validation**: Check extension against allowed list (`.bin`, `.hex`, `.obj`, `.asm`, `.s`, `.txt`); validate MIME type; enforce `MAX_UPLOAD_SIZE_BYTES` from `AdminSetting` table (default 8 MB)
   - **Quota check**: Count user's `queued + running` jobs; reject if ≥ `user.max_queued_jobs`
   - **Rate limiting**: Check user has not exceeded `MAX_JOBS_PER_HOUR` submissions (`AdminSetting`)
   - **File storage**: Create directory `/srv/retrobridge/uploads/job-<id>/`, save file as `program.bin`
   - **DB insert**: `INSERT INTO jobs (user_id, device_id, original_filename, stored_filename, file_size_bytes, priority, status) VALUES (...)` with `status='queued'`
     - Flash success message with job ID, redirect to `GET /jobs/<id>`

### 7.3 Interactive Terminal Session Flow

**Session Establishment:**

1. Authenticated user navigates to `GET /terminal` — sees a list of devices that have at least one enabled interactive port (`DevicePort.purpose='interactive'` and `is_enabled=True`)
2. If the user already has an active terminal session (count of active `TerminalSession` records for this user ≥ `user.max_terminal_sessions`), the page shows the existing session with an option to resume or disconnect
3. User selects a device and navigates to `GET /terminal/<device_id>`
4. Page loads xterm.js with the `xterm-addon-fit` addon for auto-resize. The browser establishes a WebSocket connection to Flask-SocketIO at namespace `/terminal`
5. On WebSocket `connect`, the client emits a `request_session` event with `{ "device_id": <id> }`

**Server-side Session Allocation:**

1. Flask-SocketIO handler receives `request_session`
2. Verify user is authenticated via Flask-Login session cookie propagated through the WebSocket handshake
3. Check user quota: `SELECT COUNT(*) FROM terminal_sessions WHERE user_id=? AND status='active'` — reject if ≥ `user.max_terminal_sessions`
4. Find an available interactive port on the requested device: `SELECT * FROM device_ports WHERE device_id=? AND purpose='interactive' AND is_enabled=True` — then check that no active `TerminalSession` is using any of these ports. Pick the first free port.
5. If no port available, emit `session_denied` with reason "All interactive ports are currently in use"
6. On success:
   - Create `TerminalSession` record: `INSERT INTO terminal_sessions (user_id, device_id, port_id, status) VALUES (...)`
   - Open the serial port via `pyserial` using the `DevicePort` configuration
   - Spawn an eventlet green thread that continuously reads from the serial port and emits `terminal_output` events to the client
   - Emit `session_granted` with `{ "session_id": <id>, "device_name": "...", "port_label": "...", "cols": 80, "rows": 24 }`

**Bidirectional Serial Bridge:**

- **Client → Serial**: On `terminal_input` events, the server writes the raw `data` bytes directly to the serial port via `ser.write(data.encode())`. No translation or buffering — the vintage system sees exactly what the user types.
- **Serial → Client**: The background green thread reads from `ser.read(1024)` in a loop with a short timeout. Any bytes read are emitted via `terminal_output` to the client. xterm.js renders them in the browser terminal.
- **Resize events**: On `terminal_resize`, the server may send a SIGWINCH-equivalent escape sequence if the vintage OS supports it. Otherwise, the resize is cosmetic (xterm.js adjusts its display dimensions).
- **Heartbeat**: Client sends `heartbeat` every 30 seconds; server responds with `heartbeat_ack`. If the server misses 3 consecutive heartbeats, it closes the session.

**Session Termination:**

Sessions end via any of the following paths:

| Trigger                | Flow                                                                                                                                                                           |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Client disconnects     | WebSocket `disconnect` event → close serial port → update `TerminalSession` with `status='disconnected'`, `disconnect_reason='user_disconnect'`, compute `duration_seconds`    |
| Max session duration   | Background timer reaches `DevicePort.max_runtime_seconds` → emit `session_closed` to client → close serial port → update DB with `disconnect_reason='timeout'`                 |
| Idle timeout           | No `terminal_input` or serial output for `DevicePort.idle_timeout_seconds` → emit `session_closed` → close serial → update DB with `disconnect_reason='idle_timeout'`          |
| Admin force-disconnect | Admin issues `POST /api/sessions/<id>/disconnect` → server calls `socketio.emit('session_closed', to=sid)` → closes serial → updates DB with `disconnect_reason='admin_force'` |
| Server error           | Exception in serial read/write → emit `session_closed` with error → close port → update DB with `disconnect_reason='error'`                                                    |

### 7.4 PTY Simulation for Development Testing

Since no vintage hardware is available during initial development, the system supports PTY-based simulation for both job processing and interactive terminal sessions.

**Job Simulation (`flask simulation-worker --device <name>`):**

1. Creates a PTY master/slave pair using `os.openpty()`
2. Updates the job queue port's `dev_path` to the slave PTY path
3. Forks a child process connected to the slave that mimics a vintage machine:
   - Listens for a CR/newline, then sends a minimal prompt (e.g., `READY\r\n`)
   - Waits for pre-transfer commands, echoes them back
   - After a delay, sends XMODEM 'C' character to initiate CRC transfer
   - Receives XMODEM blocks using the `xmodem` library, writes them to a temp file
   - Sends ACK/NAK as appropriate
   - Sends simulated output (e.g., "PROGRAM LOADED. EXECUTING...\nHello, World!\n")
   - Dwells for a configurable period, then exits
4. The job worker (`worker.py`) connects to the master PTY end, performing the same flow as with real hardware
5. This enables end-to-end integration testing of the full upload → claim → transfer → capture pipeline without physical devices

**Terminal Simulation (`flask simulation-terminal --device <name>`):**

1. Creates a PTY master/slave pair for an interactive port
2. Updates the interactive port's `dev_path` to the slave PTY path
3. Child process mimics a vintage multi-user OS login sequence:
   - Prints a banner (e.g., "CENTURION CPU-6 — MULTI-USER OS v4.2\r\n")
   - Displays a login prompt: "USERNAME: "
   - Reads input, echoes characters, then prompts "PASSWORD: "
   - On any input, simulates a successful login and presents a command shell prompt (e.g., "A>\` ")
   - Responds to basic fake commands (`DIR`, `HELP`, `RUN`, `STATUS`) with canned output
   - Supports rudimentary line editing (backspace)
4. User connects via the terminal UI; the Flask-SocketIO bridge connects to the master PTY end
5. Enables full testing of the WebSocket ↔ serial bridge, session timeouts, and disconnect handling without hardware

### 7.5 Admin Operations

**User Management (`/admin/users`):**

- Table displays all users with columns: ID, username, email, admin status badge, job count, terminal session count, quotas (`max_queued_jobs`, `max_terminal_sessions`), registration date, actions
- Edit: inline or modal form to toggle `is_admin`, adjust `max_queued_jobs` and `max_terminal_sessions`, edit email/full name
- Delete: confirmation modal; on confirm, either reassign user's jobs and sessions to admin or cascade-delete (configurable)
- Cannot delete own admin account

**Device Management (`/admin/devices`):**

- Table displays all devices with columns: name, display name, number of ports (by purpose), enabled status
- Each device row expands to show its ports: port label, dev_path, purpose badge (job_queue/interactive), baud, parity, flow control, enabled status, current usage
- Add device: form with name, display_name. Ports are added separately.
- Add/edit port: form with all `DevicePort` fields; `purpose` dropdown (`job_queue` / `interactive`) determines which additional fields are shown
- Toggle port enable/disable: instant AJAX toggle; disabled ports are not allocated to jobs or sessions
- Test connection: button opens serial port at `dev_path`, sends a harmless probe, reports success/failure

**Job Administration (`/admin/jobs`):**

- View all jobs across all users, filterable by status (queued/running/completed/failed/canceled), device, port, user
- Force-cancel running jobs: sets status to `canceled`, the worker detects this on next poll and aborts
- View any job's session log and metadata
- Re-queue failed jobs: reset status to `queued`, clear error message

**Terminal Session Administration (`/admin/sessions`):**

- View all active terminal sessions: user, device, port label, connected at, duration, bytes sent/received
- View session history: all past sessions with disconnect reason
- Force-disconnect: sends `session_closed` via SocketIO to the target client, closes serial port, updates DB
- Session log viewer: if per-session logging is enabled, view the terminal session log

**Global Settings (`/admin/settings`):**

- Form renders all `AdminSetting` rows as labeled fields
- Editable keys: `MAX_UPLOAD_SIZE_BYTES`, `DEFAULT_MAX_QUEUED_JOBS`, `DEFAULT_MAX_TERMINAL_SESSIONS`, `IDLE_SLEEP_SECONDS`, `MAX_JOBS_PER_HOUR`, `MAX_TERMINAL_SESSION_SECONDS`, `TERMINAL_IDLE_TIMEOUT_SECONDS`
- On save, values are written to the `adminsetting` table; workers and routes read from this table at runtime

---

## 8. Deployment Design

### 8.1 Directory Structure

```
/srv/retrobridge/
├── retrobridge/                # Python application package
│   ├── __init__.py             # create_app() factory
│   ├── models.py               # SQLAlchemy models (User, Device, Job, AdminSetting)
│   ├── auth/
│   │   ├── __init__.py         # auth_bp Blueprint
│   │   ├── routes.py
│   │   ├── forms.py
│   │   └── utils.py
│   ├── jobs/
│   │   ├── __init__.py         # jobs_bp Blueprint
│   │   ├── routes.py
│   │   ├── forms.py
│   │   └── utils.py
│   ├── api/
│   │   ├── __init__.py         # api_bp Blueprint
│   │   └── routes.py
│   ├── terminal/
│   │   ├── __init__.py         # terminal_bp Blueprint
│   │   ├── routes.py
│   │   ├── events.py           # Flask-SocketIO event handlers
│   │   └── utils.py            # Serial bridge, port allocation
│   ├── admin/
│   │   ├── __init__.py         # admin_bp Blueprint
│   │   ├── routes.py
│   │   └── forms.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── auth/
│   │   ├── jobs/
│   │   ├── terminal/
│   │   └── admin/
│   └── static/
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── main.js
├── instance/                   # Flask instance folder (generated)
│   └── retrobridge.db
├── uploads/                    # User program uploads (outside package)
│   └── job-<id>/
├── outputs/                    # Session capture logs (outside package)
│   └── job-<id>/
├── logs/                       # Application and worker logs
│   ├── app.log
│   ├── worker-centurion.log
│   └── worker-pdp11.log
├── worker.py                   # Worker daemon script
├── cli.py                      # Flask CLI commands
├── config.py                   # Config classes (DevConfig, ProdConfig, TestConfig)
├── requirements.txt
├── wsgi.py                     # Gunicorn entry point: from retrobridge import create_app; app = create_app()
└── .env                        # Environment secrets (SECRET_KEY, etc.)
```

### 8.2 systemd Service Units

**Web Application — `/etc/systemd/system/retrobridge-web.service`:**

```ini
[Unit]
Description=RetroBridge Web Application (gunicorn + eventlet for WebSocket)
After=network.target

[Service]
User=retrobridge
Group=www-data
WorkingDirectory=/srv/retrobridge
Environment="FLASK_ENV=production"
ExecStart=/srv/retrobridge/venv/bin/gunicorn -k eventlet -w 1 -b 127.0.0.1:8000 wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Worker (Centurion) — `/etc/systemd/system/retrobridge-worker@centurion.service`:**

```ini
[Unit]
Description=RetroBridge Serial Worker for Centurion
After=network.target retrobridge-web.service

[Service]
User=retrobridge
Group=dialout
WorkingDirectory=/srv/retrobridge
ExecStart=/srv/retrobridge/venv/bin/python3 /srv/retrobridge/worker.py --device centurion
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Worker (PDP-11) — `/etc/systemd/system/retrobridge-worker@pdp11.service`:**

```ini
[Unit]
Description=RetroBridge Serial Worker for PDP-11
After=network.target retrobridge-web.service

[Service]
User=retrobridge
Group=dialout
WorkingDirectory=/srv/retrobridge
ExecStart=/srv/retrobridge/venv/bin/python3 /srv/retrobridge/worker.py --device pdp11
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 8.3 nginx Configuration

`/etc/nginx/sites-available/retrobridge`:

```nginx
server {
    listen 443 ssl;
    server_name retrobridge.example.com;

    ssl_certificate     /etc/letsencrypt/live/retrobridge.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/retrobridge.example.com/privkey.pem;

    client_max_body_size 16M;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location /static/ {
        alias /srv/retrobridge/retrobridge/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Socket.IO WebSocket endpoint
    location /socket.io/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400s;  # Long-lived WebSocket connections
        proxy_send_timeout 86400s;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}

server {
    listen 80;
    server_name retrobridge.example.com;
    return 301 https://$host$request_uri;
}
```

### 8.4 udev Rules

`/etc/udev/rules.d/99-retrobridge-serial.rules`:

```
# Centurion CPU-6 — Serial adapter #1 (job queue port TTY0)
# USB example:
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A1001", MODE="0660", GROUP="dialout", SYMLINK+="centurion_tty0"
# PCIe example (native serial ports appear as /dev/ttyS*; use devpath or PCI slot for stable naming):
# SUBSYSTEM=="tty", KERNELS=="0000:02:00.0", MODE="0660", GROUP="dialout", SYMLINK+="centurion_tty0"

# Centurion CPU-6 — Serial adapter #2 (job queue port TTY1)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A1002", MODE="0660", GROUP="dialout", SYMLINK+="centurion_tty1"

# Centurion CPU-6 — Serial adapter #3 (interactive port TTY2)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A1003", MODE="0660", GROUP="dialout", SYMLINK+="centurion_tty2"

# Centurion CPU-6 — additional interactive ports as needed...
# SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A1004", MODE="0660", GROUP="dialout", SYMLINK+="centurion_tty3"

# PDP-11/44 — Serial adapter #1 (job queue port)
SUBSYSTEM=="tty", ATTRS{idVendor}=="067b", ATTRS{idProduct}=="2303", ATTRS{serial}=="B2001", MODE="0660", GROUP="dialout", SYMLINK+="pdp11_tty0"

# PDP-11/44 — Serial adapter #2 (interactive port)
SUBSYSTEM=="tty", ATTRS{idVendor}=="067b", ATTRS{idProduct}=="2303", ATTRS{serial}=="B2002", MODE="0660", GROUP="dialout", SYMLINK+="pdp11_tty1"

# PDP-11/44 — additional ports as needed...

# For PCIe multi-port serial cards, match by PCI device path or driver:
# Example: SUBSYSTEM=="tty", DRIVERS=="serial", KERNELS=="0000:03:00.0", MODE="0660", GROUP="dialout", SYMLINK+="pdp11_tty0"
```

- **USB adapters**: The `idVendor` and `idProduct` values must be updated to match the actual USB-serial adapters after identifying them with `lsusb`. Match individual adapters by `ATTRS{serial}` to create distinct symlinks per port.
- **PCIe adapters**: For PCIe multi-port serial cards (e.g., StarTech, Moxa, Brainboxes), identify the PCI device path via `udevadm info -a -n /dev/ttyS0` and match by `KERNELS` (PCI slot address) or `DRIVERS`. PCIe native serial ports typically appear as `/dev/ttyS*` rather than `/dev/ttyUSB*`.

The rules can be reloaded with:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### 8.5 logrotate Configuration

`/etc/logrotate.d/retrobridge`:

```
/srv/retrobridge/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

---

## 9. Security Design

### 9.1 Authentication Security

- **Password hashing**: `werkzeug.security.generate_password_hash()` using PBKDF2-SHA256 with a random salt per user. No plaintext passwords are ever stored.
- **Password policy**: Minimum 8 characters, at least 1 uppercase letter, at least 1 digit. Enforced server-side in `RegistrationForm` validators.
- **Login throttling**: Consecutive failed login attempts from the same IP are tracked (or per-username); after 5 failures within 15 minutes, further attempts are rejected for a cooldown period.
- **Session protection**: Flask-Login configured with `SESSION_PROTECTION = 'strong'`, which invalidates sessions when the client IP or User-Agent changes.
- **Remember-me token**: Uses Flask-Login's secure cookie with HTTPOnly and Secure flags (when served over HTTPS via nginx).

### 9.2 Authorization

- **Role-based access control (RBAC)**:
  - **Unauthenticated**: Can only access login, register, and static assets
  - **Regular user**: Can manage own jobs, view own dashboard, manage own terminal sessions, edit own profile
  - **Admin**: Full access to admin panel; can view/edit/delete any user, device, port, job, or terminal session
- **Job ownership enforcement**: All job routes (`/jobs/<id>`, `/api/jobs/<id>/status`, `/api/jobs/<id>/output`) verify `job.user_id == current_user.id` or `current_user.is_admin` before serving data or accepting actions
- **Terminal session enforcement**: WebSocket `request_session` handler verifies the Flask-Login session from the WebSocket handshake. Users can only view/disconnect their own sessions. Admins can view and force-disconnect any session.
- **Decorator enforcement**: `@login_required` on all blueprints except auth; `@admin_required` on admin blueprint; both raise 403 (Forbidden) on violation

### 9.3 Input Validation and Injection Prevention

- **SQL Injection**: All database access uses SQLAlchemy ORM parameterized queries. No raw SQL strings are concatenated with user input anywhere in route handlers. Worker `claim_job()` uses parameterized queries even with raw `sqlite3`.
- **Cross-Site Scripting (XSS)**: Jinja2 templates use auto-escaping by default. Session log output is rendered inside `<pre>` tags with escaped content. No use of `|safe` filter on user-generated content.
- **Cross-Site Request Forgery (CSRF)**: Flask-WTF provides CSRF protection on all forms. Every form includes `{{ form.hidden_tag() }}` which renders the CSRF token. API endpoints that mutate state validate the CSRF token or use an alternative token scheme.
- **File upload validation**:
  - Allowed extensions: `.bin`, `.hex`, `.obj`, `.asm`, `.s`, `.txt`
  - MIME type checked against actual file content (not just the client-supplied Content-Type header)
  - Maximum file size enforced before saving to disk (`MAX_UPLOAD_SIZE_BYTES`, default 8 MB)
  - Files stored outside the web root under `/srv/retrobridge/uploads/` — never directly accessible via URL
  - Downloaded only through the `/jobs/<id>/download` route which enforces authentication and ownership

### 9.4 Rate Limiting

- **Per-user job submission**: Maximum 10 jobs per hour (configurable via `AdminSetting.MAX_JOBS_PER_HOUR`). Tracked via a counter in the `adminsetting` table or an in-memory store, keyed by `user_id:hour`.
- **Per-user queue depth**: Maximum `user.max_queued_jobs` (default 3) jobs in `queued` or `running` status simultaneously.
- **API polling**: Status endpoints have no explicit rate limit (lightweight queries), but excessive polling clients may trigger a 429 response.

### 9.5 Worker Privilege Separation

- The `retrobridge` system user runs the web application (gunicorn) and belongs to the `www-data` group for nginx socket access
- The same `retrobridge` user runs worker processes but is additionally a member of the `dialout` group for serial port access
- Workers have no shell access, no sudo privileges, and no write access outside of `/srv/retrobridge/uploads/`, `/srv/retrobridge/outputs/`, and `/srv/retrobridge/logs/`
- The SQLite database file is owned by `retrobridge:www-data` with mode `0660`

### 9.6 Network Isolation

- The vintage hardware should be connected to the host server via dedicated USB or PCIe serial adapters
- The vintage machines should not be accessible from any network (isolated serial-only)
- The web application is exposed only over HTTPS via nginx; plain HTTP is redirected

### 9.7 Audit Logging

- Every job state transition is recorded with timestamps (`created_at`, `started_at`, `finished_at`)
- Worker logs capture every byte sent and received with timestamps in `session.log`
- Every terminal session is recorded with `connected_at`, `disconnected_at`, `duration_seconds`, `bytes_sent`, `bytes_received`, and `disconnect_reason`
- Optional per-session terminal logging (`session_logs/session-<id>/terminal.log`) captures all keystrokes and output for auditing
- Application logs capture authentication events, admin actions, and errors
- Logs are rotated daily with 30-day retention

### 9.8 Terminal Session Security

- **Session authentication**: WebSocket connections are authenticated via the Flask-Login session cookie propagated through the nginx proxy. Unauthenticated WebSocket connections are rejected on `connect`.
- **Per-user session limits**: Each user is limited to `max_terminal_sessions` (default 1) concurrent interactive sessions. Enforced at `request_session` time.
- **Session timeouts**: Every interactive port has a `max_runtime_seconds` (default 3600) and `idle_timeout_seconds` (default 300). The server enforces both — max duration via a background timer, idle via no-input/output detection.
- **Port isolation**: Each interactive terminal session exclusively locks one `DevicePort` for its duration. No other user can connect to the same port simultaneously. Port allocation is atomic (check-and-claim in DB).
- **Admin force-disconnect**: Admins can terminate any active session via the admin panel or API. The server sends `session_closed` to the target client and closes the serial port.
- **Keystroke logging**: If per-session terminal logging is enabled (configurable per device), all bytes sent and received are timestamped and written to `session_logs/session-<id>/terminal.log`. This is disabled by default for privacy and must be explicitly enabled by an admin.

---

## 10. Testing Strategy

### 10.1 Unit Tests (`tests/unit/`)

| Test File                | Scope                                                                                                                                                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `test_models.py`         | User creation and password hashing; Device and DevicePort config validation (parity, flow control, purpose enum checks); Job and TerminalSession status transitions; AdminSetting read/write                       |
| `test_auth.py`           | Registration form validation (password complexity, email format, username uniqueness); Login form submission with valid/invalid credentials; Session management (user_loader, anonymous_user)                      |
| `test_job_claiming.py`   | Atomic job claiming with BEGIN IMMEDIATE transaction; Port-level concurrency limit enforcement (race condition simulation with multiple workers claiming the same port); Quota enforcement for per-user job limits |
| `test_terminal_ports.py` | Interactive port availability tracking; User session quota enforcement; Port allocation and release atomicity; Concurrent session request rejection when ports are exhausted                                       |

**Framework:** `pytest` with `pytest-flask` for Flask application context. SQLite in-memory database for test isolation.

### 10.2 Integration Tests (`tests/integration/`)

| Test File                   | Scope                                                                                                                                                                                                                                 |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_worker_simulation.py` | PTY-based end-to-end: spawn simulation PTY, create a job in DB targeting the simulation port, run worker claim-and-execute cycle once, verify job status transitions to `completed` and output file contains expected session content |
| `test_terminal_session.py`  | PTY-based terminal simulation: spawn PTY simulating vintage OS, connect via Flask-SocketIO test client, send keystrokes, verify terminal output received, test disconnect and timeout handling                                        |
| `test_upload_flow.py`       | HTTP POST multipart upload through Flask test client with simulated login; Verify file saved to correct path; Verify Job row created with `status='queued'` and correct metadata; Verify quota check rejects upload when at limit     |
| `test_api.py`               | All REST endpoints tested via Flask test client; Verify pagination, status responses, authentication required on protected endpoints, ownership enforcement                                                                           |

### 10.3 End-to-End Tests (`tests/e2e/`)

| Scenario                   | Steps                                                                                             | Assertions                                                                                                         |
| -------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Full job path              | Register → Login → Upload file → Worker processes (simulated) → View job detail → Download output | Job status = `completed`; output file is downloadable and non-empty; session log shows transfer and output         |
| Full terminal session path | Login → Navigate to terminal → Select device → Connect → Type commands → View output → Disconnect | Terminal connection established; keystrokes echoed; output displayed; session record created with correct duration |
| Terminal session timeout   | Connect to terminal → Remain idle for `idle_timeout_seconds`                                      | Session auto-disconnects with `disconnect_reason='idle_timeout'`; port released for other users                    |
| Terminal session denial    | Connect to terminal → Exhaust available ports → Second user attempts connection on same device    | Second user receives `session_denied` with "All interactive ports are currently in use"                            |
| Cancel flow                | Create job → Cancel from job detail page                                                          | Job status = `canceled`; cancel button hidden after cancellation                                                   |
| Admin user management      | Admin login → View users list → Toggle admin on a user → Edit quotas                              | User row updated; changed user gains/loses admin access                                                            |
| Admin port management      | Admin login → View device ports → Add interactive port → Change baud → Disable port → Enable port | Port CRUD works; disabled ports excluded from allocation                                                           |
| Admin force-disconnect     | User connects to terminal → Admin views sessions → Force-disconnect                               | User receives `session_closed`; session record updated with `disconnect_reason='admin_force'`                      |
| Quota enforcement          | Create 3 queued jobs → Attempt 4th upload                                                         | 4th upload rejected with quota exceeded message                                                                    |
| Unauthorized access        | Anonymous user attempts `/jobs/new`                                                               | Redirected to login; after login, redirected back to `/jobs/new`                                                   |

### 10.4 Hardware Dry-Run Tests

- **USB/PCIe loopback adapter**: Connect TX to RX on a USB or PCIe serial adapter. Configure a `DevicePort` entry pointing to the loopback path. Submit a job; verify the worker can open the port, send data, and capture the echoed bytes.
- **Terminal loopback test**: Configure an interactive port pointing to a loopback adapter. Connect via the terminal UI; type characters and verify they are echoed back in the xterm.js window.
- **PTY simulation**: The `flask simulation-worker` and `flask simulation-terminal` commands provide full PTY-based mocks that exercise the XMODEM transfer path, WebSocket bridge, timeout handling, and session capture logic without requiring physical hardware.
- **Real hardware integration**: After PTY tests pass, connect actual vintage machines and run a minimal "hello world" type program on a job port and an interactive login session on a terminal port to validate baud rates, handshaking, and line ending settings.

### 10.5 Connecting Emulated Systems

Vintage hardware is not a prerequisite — RetroBridge can connect to software emulators running full vintage operating systems in production. Emulated systems behave identically to real hardware from RetroBridge's perspective: they expose RS-232 serial ports (over TCP or PTY) that RetroBridge bridges to the web UI for job processing and interactive terminal sessions via the transport types defined in §6.4.

| Emulator      | Target Machine  | Operating Systems                                  | Serial Ports                              |
| ------------- | --------------- | --------------------------------------------------- | ----------------------------------------- |
| **Open SIMH** | PDP-11/44       | RSTS/E, RT-11, 2.11 BSD Unix, RSX-11M              | TCP endpoints or PTY pairs                |
| **CPU7Plus**  | Centurion CPU-6 | Centurion Multi-User OS, BOS/5+                    | TCP endpoints or PTY pairs                |

#### Connecting via TCP (recommended)

The simplest approach is direct TCP — configure the `DevicePort` with `transport=tcp` and `dev_path=host:port`. RetroBridge opens a raw TCP socket to the emulator's serial port. No socat bridge is needed:

```
DevicePort: transport=tcp  dev_path=127.0.0.1:10023  purpose=interactive
DevicePort: transport=tcp  dev_path=127.0.0.1:10024  purpose=job_queue
```

For emulators that expose telnet (e.g., some SIMH configurations), use `transport=telnet`:

```
DevicePort: transport=telnet  dev_path=127.0.0.1:23  purpose=interactive
```

#### Connecting via socat (PTY fallback)

If an emulator only exposes PTY device paths, or if you prefer PTY-based bridging, use `socat` to bridge TCP to a PTY and configure the port with `transport=pty`:

```bash
# Bridge SIMH PDP-11 port 10023 → PTY for RetroBridge
socat PTY,link=/tmp/simh_pdp11_tty0,raw,echo=0 TCP:localhost:10023
```

The PTY path is then configured as `transport=pty  dev_path=/tmp/simh_pdp11_tty0`.

#### Multiple ports per emulator

Most emulators can expose multiple serial ports. Each port becomes a separate `DevicePort` in RetroBridge, partitioned into job-queue and interactive pools just like physical hardware. With direct TCP transport, each port simply uses a different emulator port number:

```
# SIMH PDP-11: port 10023 = job queue, port 10024 = interactive
DevicePort: transport=tcp  dev_path=127.0.0.1:10023  purpose=job_queue       transfer_protocol=xmodem
DevicePort: transport=tcp  dev_path=127.0.0.1:10024  purpose=interactive    newline_mode=crlf

# CPU7Plus: port 10901 = job queue, port 10902 = interactive
DevicePort: transport=tcp  dev_path=127.0.0.1:10901  purpose=job_queue       transfer_protocol=xmodem
DevicePort: transport=tcp  dev_path=127.0.0.1:10902  purpose=interactive    newline_mode=crlf
```

When connecting over a network to serial-to-Ethernet adapters bridging real hardware, use `transport=rfc2217` for full modem signal access:

```
DevicePort: transport=rfc2217  dev_path=192.168.1.50:4001  baud=19200  parity=N  flow_control=rtscts
```

#### Production use

Emulated systems connected this way are treated as first-class production devices. They appear in the admin panel alongside physical hardware, participate fully in the job queue and terminal session pools, and have no functional limitations compared to real machines. This is the recommended path for:

- Development and testing without vintage hardware
- Providing additional capacity alongside physical machines
- Running installations entirely on emulated systems
- Disaster recovery and redundancy via replicated emulator images

### 10.6 Test Execution

```bash
# Run all tests
pytest tests/ -v

# Run unit tests only
pytest tests/unit/ -v

# Run integration tests (requires PTY)
pytest tests/integration/ -v

# Run with coverage report
pytest tests/ --cov=retrobridge --cov-report=html
```
