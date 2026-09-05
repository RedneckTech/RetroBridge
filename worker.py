#!/usr/bin/env python3
"""
RetroBridge Job Worker
======================
Standalone daemon that polls the database for queued jobs targeting a specific
device, atomically claims them, transfers programs over RS-232 via XMODEM,
captures serial output, and updates job status.

Usage:
    python worker.py --device centurion
    python worker.py --device pdp11 --poll-interval 5
"""

import argparse
import errno
import json
import logging
import os
import select
import signal
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from serial import Serial, SerialException
from sqlalchemy import create_engine, func, select as sa_select, update
from sqlalchemy.orm import Session, sessionmaker
from xmodem import XMODEM, XMODEM1k

load_dotenv()

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from retrobridge.models import Base, Device, DevicePort, Job, User  # noqa: E402
from retrobridge.transport import open_transport, transport_uses_baud  # noqa: E402
from retrobridge.integrations.email import (  # noqa: E402
    notify_job_completed,
    _load_settings_from_db,
)

LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

JOB_LEASE_SECONDS = 300
JOB_HEARTBEAT_INTERVAL = 30

_NEWLINE_SEQUENCES = {'cr': '\r', 'lf': '\n', 'crlf': '\r\n'}


def _resolve_newline_mode(job, port):
    """Return the newline mode to use, preferring job-level overrides."""
    return job.override_newline_mode or port.newline_mode or 'crlf'


def _resolve_cmds(job, port, kind):
    """Return the pre/post transfer command list, preferring job overrides."""
    if kind == 'pre':
        raw = job.override_pre_transfer_cmds or port.pre_transfer_cmds
    elif kind == 'post':
        raw = job.override_post_transfer_cmds or port.post_transfer_cmds
    else:
        raise ValueError(f'Unknown command kind: {kind!r}')

    if not raw:
        return []

    try:
        cmds = json.loads(raw)
    except json.JSONDecodeError:
        cmds = [raw]

    if isinstance(cmds, str):
        cmds = [cmds]
    return cmds or []


def _apply_newline(cmd, mode):
    """Ensure *cmd* ends with the configured newline sequence.

    If the command already ends with a recognised line ending it is left
    untouched so that explicit endings (e.g. ``\\r``) are preserved.
    """
    if not cmd:
        return cmd
    if cmd.endswith('\r\n') or cmd.endswith('\r') or cmd.endswith('\n'):
        return cmd
    newline = _NEWLINE_SEQUENCES.get(mode, '\r\n')
    return cmd + newline


def build_engine():
    db_uri = config.get_database_uri()

    connect_args = config.BaseConfig.SQLALCHEMY_ENGINE_OPTIONS.get(
        'connect_args', {'timeout': 10},
    )

    engine = create_engine(db_uri, connect_args=connect_args)

    from retrobridge.sqlite_provision import configure_sqlite_engine

    env = os.environ.get('FLASK_ENV', 'development')
    if env == 'production' and hasattr(config.ProdConfig, 'SQLITE_PRAGMAS'):
        pragma_config = {'SQLITE_PRAGMAS': config.ProdConfig.SQLITE_PRAGMAS}
    else:
        pragma_config = None

    configure_sqlite_engine(engine, pragma_config)

    return engine


def setup_logging(device_name):
    log_dir = os.environ.get(
        'RETROBRIDGE_LOG_DIR',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs'),
    )
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f'worker-{device_name}.log')
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(f'worker.{device_name}')


def get_serial_params(port):
    parity_map = {
        'N': 'N', 'E': 'E', 'O': 'O', 'M': 'M', 'S': 'S',
    }

    return {
        'port': port.dev_path,
        'baudrate': port.baud if port.baud else 9600,
        'bytesize': port.data_bits if port.data_bits else 8,
        'parity': parity_map.get(port.parity or 'N', 'N'),
        'stopbits': port.stop_bits if port.stop_bits else 1,
        'timeout': 0.5,
        'rtscts': port.flow_control == 'rtscts',
        'xonxoff': port.flow_control == 'xonxoff',
    }


def _fd_read(fd, size, timeout):
    """Read from fd with select-based timeout. Returns data or b'' on EOF/timeout."""
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return b''
    try:
        return os.read(fd, size)
    except OSError as e:
        if e.errno == errno.EIO:
            return b''
        raise


def _fd_write(fd, data):
    """Write all data to fd, handling partial writes."""
    total = 0
    while total < len(data):
        n = os.write(fd, data[total:])
        if n <= 0:
            raise OSError("fd write returned 0 or negative")
        total += n
    return total


class JobCancelledError(Exception):
    """Raised when a job is cancelled mid-transfer."""


def _check_job_cancelled(job, session_factory):
    """Re-read job from DB; raise if cancel_requested or status is canceled."""
    if session_factory:
        s = session_factory()
        try:
            j = s.get(Job, job.id)
            if j and (j.cancel_requested or j.status == 'canceled'):
                raise JobCancelledError("job was cancelled")
        finally:
            s.close()


def _worker_id(device_name):
    return f"{socket.gethostname()}:{os.getpid()}:{device_name}"


def _send_heartbeat(job_id, session_factory, logger):
    """Update heartbeat_at and lease_expires_at on the claimed job."""
    try:
        now = datetime.now(timezone.utc)
        session = session_factory()
        session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=JOB_LEASE_SECONDS),
            )
        )
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        logger.debug('Heartbeat update failed, will retry next cycle')
    finally:
        try:
            session.close()
        except Exception:
            pass


def recover_stale_jobs(session, device_id, logger=None):
    """Reset jobs with expired leases back to queued, or cancel if requested."""
    now = datetime.now(timezone.utc)

    stale_cancel_requested = session.execute(
        update(Job)
        .where(
            Job.device_id == device_id,
            Job.status == 'running',
            Job.lease_expires_at.isnot(None),
            Job.lease_expires_at < now,
            Job.cancel_requested.is_(True),
        )
        .values(
            status='canceled',
            port_id=None,
            started_at=None,
            worker_pid=None,
            claimed_by=None,
            claimed_at=None,
            lease_expires_at=None,
            heartbeat_at=None,
            error_message='Canceled during stale recovery',
        )
    )
    if stale_cancel_requested.rowcount:
        session.commit()
        if logger:
            logger.info(
                'Canceled %d stale job(s) with cancel_requested for device id %d',
                stale_cancel_requested.rowcount, device_id,
            )
        return

    result = session.execute(
        update(Job)
        .where(
            Job.device_id == device_id,
            Job.status == 'running',
            Job.lease_expires_at.isnot(None),
            Job.lease_expires_at < now,
        )
        .values(
            status='queued',
            port_id=None,
            started_at=None,
            worker_pid=None,
            claimed_by=None,
            claimed_at=None,
            lease_expires_at=None,
            heartbeat_at=None,
        )
    )
    if result.rowcount:
        session.commit()
        if logger:
            logger.info(
                'Recovered %d stale job(s) for device id %d',
                result.rowcount, device_id,
            )


def claim_job(session: Session, device_name: str, logger=None) -> Job | None:
    device = session.query(Device).filter_by(name=device_name, is_enabled=True).first()
    if not device:
        return None

    recover_stale_jobs(session, device.id, logger)

    job_ports = (
        session.query(DevicePort)
        .filter_by(device_id=device.id, purpose='job_queue', is_enabled=True)
        .all()
    )
    if not job_ports:
        return None

    try:
        for port in job_ports:
            now = datetime.now(timezone.utc)
            lease_until = now + timedelta(seconds=JOB_LEASE_SECONDS)
            wid = _worker_id(device_name)

            # Atomic claim with an inline concurrency guard: only consider a
            # queued job if the number of currently running jobs on this port
            # is below max_concurrent_jobs. This prevents two workers from
            # both claiming past the limit after seeing the same pre-check
            # running count.
            running_count_subq = (
                sa_select(func.count(Job.id))
                .where(Job.port_id == port.id, Job.status == 'running')
                .scalar_subquery()
            )
            result = session.execute(
                update(Job)
                .where(
                    Job.id == (
                        sa_select(Job.id)
                        .where(
                            Job.device_id == device.id,
                            Job.status == 'queued',
                            Job.cancel_requested.is_(False),
                            running_count_subq < port.max_concurrent_jobs,
                        )
                        .order_by(Job.priority.desc(), Job.created_at.asc())
                        .limit(1)
                        .scalar_subquery()
                    )
                )
                .values(
                    status='running',
                    port_id=port.id,
                    started_at=now,
                    worker_pid=os.getpid(),
                    claimed_by=wid,
                    claimed_at=now,
                    lease_expires_at=lease_until,
                    heartbeat_at=now,
                )
                .returning(Job.id)
            )
            row = result.fetchone()

            if row is None:
                session.rollback()
                continue

            session.commit()
            job = session.get(Job, row[0])
            if job and logger:
                logger.info(
                    'Claimed job #%d (%s) on port %s',
                    job.id, job.original_filename, port.port_label,
                )
            return job

        return None
    except Exception:
        session.rollback()
        return None


def run_job_on_device(job: Job, port: DevicePort, logger: logging.Logger,
                      session_factory=None) -> bool:
    """
    Execute a job on the given serial port.
    Returns True on success, False on failure.
    Updates the job record in the database on completion/failure.
    """
    basedir = os.path.dirname(os.path.abspath(__file__))
    outputs_dir = Path(os.environ.get('RETROBRIDGE_OUTPUT_DIR', os.path.join(basedir, 'outputs')))
    uploads_dir = Path(os.environ.get('RETROBRIDGE_UPLOAD_DIR', os.path.join(basedir, 'uploads')))

    job_output_dir = outputs_dir / f'job-{job.id}'
    job_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_output_dir / 'session.log'

    job.output_path = str(output_path)

    upload_file = uploads_dir / (job.stored_filename or '')
    if not upload_file.exists():
        logger.error(f'Uploaded file not found: {upload_file}')
        job.status = 'failed'
        job.error_message = f'Uploaded file not found: {upload_file}'
        job.finished_at = datetime.now(timezone.utc)
        return False

    serial_params = get_serial_params(port)
    ser = None

    try:
        _check_job_cancelled(job, session_factory)

        transport = (port.transport or 'serial')
        if transport_uses_baud(port):
            logger.info(f'Opening {transport} port: {serial_params["port"]} '
                         f'({serial_params["baudrate"]} baud, {port.parity}{port.data_bits}{port.stop_bits})')
        else:
            logger.info(f'Opening {transport} connection: {serial_params["port"]}')

        ser = open_transport(port)
        time.sleep(0.5)

        with open(output_path, 'a', encoding='utf-8', errors='replace') as out_f:
            def _log_line(line, direction=''):
                ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
                prefix = f'[{ts}]'
                if direction:
                    prefix += f' [{direction}]'
                out_f.write(f'{prefix} {line}\n')
                out_f.flush()
                logger.debug(f'{direction} {line.rstrip()}')

            _log_line(f'Job #{job.id} started on {port.dev_path}', 'SYS')

            # Drain any initial data before pre-transfer
            time.sleep(0.2)
            try:
                while True:
                    chunk = _fd_read(ser.fd, 1024, 0.2)
                    if not chunk:
                        break
                    _log_line(chunk.decode('utf-8', errors='replace'), 'RX')
            except (OSError, SerialException):
                pass

            # Execute pre-transfer commands (no drain between cmd and XMODEM)
            newline_mode = _resolve_newline_mode(job, port)
            pre_cmds = _resolve_cmds(job, port, 'pre')

            for cmd in pre_cmds:
                cmd = _apply_newline(cmd, newline_mode)
                logger.info(f'Sending pre-transfer command: {repr(cmd)}')
                _fd_write(ser.fd, cmd.encode('utf-8', errors='replace'))
                _log_line(cmd, 'TX')

            # Transfer file via XMODEM
            time.sleep(0.3)
            logger.info(f'Starting XMODEM transfer of {upload_file}')
            _log_line(f'Starting XMODEM transfer: {job.original_filename}', 'SYS')

            def getc(size, timeout=1):
                _check_job_cancelled(job, session_factory)
                data = _fd_read(ser.fd, size, timeout)
                return data if data else None

            def putc(data, timeout=1):
                _check_job_cancelled(job, session_factory)
                return _fd_write(ser.fd, data)

            proto = port.transfer_protocol or 'xmodem'
            if proto == 'xmodem1k':
                modem = XMODEM1k(getc, putc)
            else:
                modem = XMODEM(getc, putc)

            with open(upload_file, 'rb') as f:
                try:
                    success = modem.send(f, retry=8)
                except JobCancelledError:
                    _log_line('Job cancelled during XMODEM transfer', 'SYS')
                    job.status = 'canceled'
                    job.error_message = 'Job canceled by administrator'
                    job.finished_at = datetime.now(timezone.utc)
                    return False

            if not success:
                logger.error('XMODEM transfer failed')
                _log_line('XMODEM transfer FAILED', 'SYS')
                job.status = 'failed'
                job.error_message = 'XMODEM transfer failed'
                job.finished_at = datetime.now(timezone.utc)
                return False

            logger.info('XMODEM transfer complete')

            # Execute post-transfer commands
            post_cmds = _resolve_cmds(job, port, 'post')

            for cmd in post_cmds:
                cmd = _apply_newline(cmd, newline_mode)
                logger.info(f'Sending post-transfer command: {repr(cmd)}')
                _fd_write(ser.fd, cmd.encode('utf-8', errors='replace'))
                _log_line(cmd, 'TX')
                time.sleep(0.3)

            # Capture output with idle timeout
            idle_timeout = port.idle_timeout_seconds or 5
            max_runtime = port.max_runtime_seconds or 300
            start_time = time.time()
            last_activity = start_time
            last_heartbeat = start_time

            logger.info(f'Capturing output (idle timeout: {idle_timeout}s, max runtime: {max_runtime}s)')
            _log_line(f'Capturing output...', 'SYS')

            while True:
                elapsed = time.time() - start_time
                if elapsed > max_runtime:
                    _log_line(f'Maximum runtime ({max_runtime}s) reached', 'SYS')
                    break

                if session_factory and (elapsed - last_heartbeat) >= JOB_HEARTBEAT_INTERVAL:
                    _send_heartbeat(job.id, session_factory, logger)
                    last_heartbeat = elapsed

                try:
                    _check_job_cancelled(job, session_factory)
                except JobCancelledError:
                    break

                try:
                    data = _fd_read(ser.fd, 1024, 0.2)
                except (OSError, SerialException):
                    _log_line('PTY closed — output capture complete', 'SYS')
                    break

                if data:
                    decoded = data.decode('utf-8', errors='replace')
                    _log_line(decoded, 'RX')
                    last_activity = time.time()
                else:
                    if time.time() - last_activity > idle_timeout:
                        _log_line(f'Idle timeout ({idle_timeout}s) reached', 'SYS')
                        break
                    time.sleep(0.1)

            try:
                _check_job_cancelled(job, session_factory)
                job.status = 'completed'
                job.finished_at = datetime.now(timezone.utc)
                job.runtime_seconds = int(time.time() - start_time)
                job.exit_code = 0
                _log_line(f'Job completed successfully ({job.runtime_seconds}s)', 'SYS')
                return True
            except JobCancelledError:
                _log_line('Job cancelled during output capture', 'SYS')
                job.status = 'canceled'
                job.error_message = 'Job canceled by administrator'
                job.finished_at = datetime.now(timezone.utc)
                job.runtime_seconds = int(time.time() - start_time)
                return False

    except SerialException as e:
        logger.error(f'Serial error: {e}')
        job.status = 'failed'
        job.error_message = f'Serial error: {e}'
        job.finished_at = datetime.now(timezone.utc)
        return False
    except JobCancelledError:
        logger.info(f'Job #{job.id} cancelled')
        if not job.status or job.status == 'running':
            job.status = 'canceled'
            job.error_message = 'Job canceled by administrator'
            job.finished_at = datetime.now(timezone.utc)
        return False
    except Exception as e:
        logger.exception(f'Unexpected error processing job #{job.id}')
        job.status = 'failed'
        job.error_message = f'Internal error: {e}'
        job.finished_at = datetime.now(timezone.utc)
        return False
    finally:
        if ser and ser.is_open:
            try:
                ser.close()
            except Exception:
                pass
        logger.info(f'Serial port closed: {port.dev_path}')


def worker_loop(device_name: str, poll_interval: int = 5):
    logger = setup_logging(device_name)
    logger.info(f'Worker starting for device: {device_name}')
    logger.info(f'Poll interval: {poll_interval}s')

    engine = build_engine()
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    shutdown_flag = False

    def handle_signal(signum, frame):
        nonlocal shutdown_flag
        sig_name = signal.Signals(signum).name
        logger.info(f'Received {sig_name}, shutting down...')
        shutdown_flag = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while not shutdown_flag:
        session = SessionLocal()
        try:
            job = claim_job(session, device_name, logger)
            if job:
                port = job.port
                if not port:
                    logger.error(f'No port assigned for job #{job.id}')
                    job.status = 'failed'
                    job.error_message = 'No port assigned'
                    job.finished_at = datetime.now(timezone.utc)
                    session.commit()
                    continue

                logger.info(f'Claimed job #{job.id}: {job.original_filename} '
                             f'on port {port.port_label} ({port.dev_path})')

                success = run_job_on_device(job, port, logger, SessionLocal)

                session.add(job)
                session.commit()

                logger.info(f'Job #{job.id} {job.status}')

                # Send email notification if user has opted in
                user = session.query(User).filter_by(id=job.user_id).first()
                if user and user.email_notify_jobs and job.status in ('completed', 'failed', 'canceled'):
                    try:
                        settings = _load_settings_from_db(session)
                        notify_job_completed(user, job, settings=settings)
                    except Exception:
                        logger.exception('Failed to send job completion email for job #%s', job.id)

            # Check for force-canceled jobs
            canceled = (
                session.query(Job)
                .filter_by(device_id=job.device_id if job else None, status='canceled')
                .all()
            )
            for cj in canceled:
                logger.info(f'Job #{cj.id} was force-canceled')

            # Cancel any queued jobs with cancel_requested that weren't claimed
            orphaned = (
                session.query(Job)
                .filter_by(device_id=job.device_id if job else None)
                .filter(Job.status == 'queued', Job.cancel_requested.is_(True))
                .all()
            )
            for oj in orphaned:
                oj.status = 'canceled'
                session.commit()
                logger.info(f'Job #{oj.id} was canceled (queued with cancel_requested)')
        except Exception as e:
            logger.exception(f'Error in worker loop: {e}')
            session.rollback()
        finally:
            session.close()

        if shutdown_flag:
            break

        time.sleep(poll_interval)

    logger.info('Worker shut down')


def main():
    parser = argparse.ArgumentParser(description='RetroBridge Job Worker')
    parser.add_argument('--device', required=True, help='Device name (e.g., centurion, pdp11)')
    parser.add_argument('--poll-interval', type=int, default=5,
                        help='Seconds between job polls (default: 5)')
    args = parser.parse_args()

    worker_loop(args.device, args.poll_interval)


if __name__ == '__main__':
    main()
