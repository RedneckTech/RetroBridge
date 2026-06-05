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
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from serial import Serial, SerialException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from xmodem import XMODEM1k

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from retrobridge.models import Base, Device, DevicePort, Job  # noqa: E402

LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def build_engine():
    env = os.environ.get('FLASK_ENV', 'development')
    basedir = os.path.dirname(os.path.abspath(__file__))

    if env == 'production':
        db_path = os.path.join(basedir, 'instance', 'retrobridge.db')
    else:
        db_path = os.environ.get(
            'DATABASE_URL',
            f'sqlite:///{os.path.join(basedir, "instance", "retrobridge_dev.db")}',
        )
        if db_path.startswith('sqlite:///'):
            pass
        else:
            db_path = f'sqlite:///{os.path.join(basedir, "instance", "retrobridge_dev.db")}'

    if not str(db_path).startswith('sqlite:///'):
        db_path = f'sqlite:///{os.path.join(basedir, "instance", "retrobridge_dev.db")}'

    return create_engine(
        db_path,
        connect_args={'timeout': 10},
    )


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


def _manual_xmodem_send(ser, stream, _log_line):
    """Minimal XMODEM sender as fallback."""
    file_size = stream.seek(0, 2)
    stream.seek(0)

    # Wait for 'C' (CRC mode)
    ser.timeout = 10
    c = ser.read(1)
    if c != b'C':
        _log_line('XMODEM handshake failed: no C received', 'SYS')
        return False

    block_num = 1
    while True:
        data = stream.read(128)
        if not data:
            break
        if len(data) < 128:
            data = data.ljust(128, b'\x1a')

        blk = bytes([block_num])
        blk_cmpl = bytes([255 - block_num])
        block = b'\x01' + blk + blk_cmpl + data
        cksum = sum(data) % 256
        block += bytes([cksum])

        ser.write(block)
        ser.timeout = 5
        ack = ser.read(1)
        if ack != b'\x06':
            _log_line(f'XMODEM: expected ACK, got {repr(ack)}', 'SYS')
            return False

        block_num = (block_num + 1) % 256

    # Send EOT
    ser.write(b'\x04')
    ser.timeout = 5
    ack = ser.read(1)
    if ack == b'\x06':
        _log_line('XMODEM transfer complete', 'SYS')
        return True

    _log_line(f'XMODEM: expected ACK after EOT, got {repr(ack)}', 'SYS')
    return False


def claim_job(session: Session, device_name: str) -> Job | None:
    device = session.query(Device).filter_by(name=device_name, is_enabled=True).first()
    if not device:
        return None

    # Find all enabled job_queue ports for this device
    job_ports = (
        session.query(DevicePort)
        .filter_by(device_id=device.id, purpose='job_queue', is_enabled=True)
        .all()
    )
    if not job_ports:
        return None

    try:
        # For each port, find a queued job that could run on it
        for port in job_ports:
            running_count = (
                session.query(Job)
                .filter_by(port_id=port.id, status='running')
                .count()
            )
            if running_count >= port.max_concurrent_jobs:
                continue

            job = (
                session.query(Job)
                .filter(Job.device_id == device.id, Job.status == 'queued')
                .order_by(Job.priority.desc(), Job.created_at.asc())
                .first()
            )
            if not job:
                continue

            job.status = 'running'
            job.port_id = port.id
            job.started_at = datetime.now(timezone.utc)
            job.worker_pid = os.getpid()
            session.commit()
            return job

        return None
    except Exception:
        session.rollback()
        return None


def run_job_on_device(job: Job, port: DevicePort, logger: logging.Logger) -> bool:
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
        logger.info(f'Opening serial port: {serial_params["port"]} '
                     f'({serial_params["baudrate"]} baud, {port.parity}{port.data_bits}{port.stop_bits})')

        ser = Serial(**serial_params)
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
            while ser.in_waiting:
                data = ser.read(ser.in_waiting)
                _log_line(data.decode('utf-8', errors='replace'), 'RX')

            # Execute pre-transfer commands (no drain between cmd and XMODEM)
            pre_cmds = []
            if port.pre_transfer_cmds:
                try:
                    pre_cmds = json.loads(port.pre_transfer_cmds)
                except json.JSONDecodeError:
                    pre_cmds = [port.pre_transfer_cmds]

            for cmd in pre_cmds:
                logger.info(f'Sending pre-transfer command: {repr(cmd)}')
                ser.write(cmd.encode('utf-8', errors='replace'))
                _log_line(cmd, 'TX')

            # Transfer file via XMODEM (library first, manual fallback)
            time.sleep(0.3)
            logger.info(f'Starting XMODEM transfer of {upload_file}')
            _log_line(f'Starting XMODEM transfer: {job.original_filename}', 'SYS')

            with open(upload_file, 'rb') as f:
                success = _manual_xmodem_send(ser, f, _log_line)
                if not success:
                    f.seek(0)
                    def getc(size, timeout=1):
                        ser.timeout = timeout
                        return ser.read(size) or b''
                    def putc(data, timeout=1):
                        ser.timeout = timeout
                        return ser.write(data)
                    modem = XMODEM1k(getc, putc)
                    success = modem.send(f, retry=8)

            if not success:
                logger.error('XMODEM transfer failed')
                _log_line('XMODEM transfer FAILED', 'SYS')
                job.status = 'failed'
                job.error_message = 'XMODEM transfer failed'
                job.finished_at = datetime.now(timezone.utc)
                return False

            logger.info('XMODEM transfer complete')

            # Execute post-transfer commands
            post_cmds = []
            if port.post_transfer_cmds:
                try:
                    post_cmds = json.loads(port.post_transfer_cmds)
                except json.JSONDecodeError:
                    post_cmds = [port.post_transfer_cmds]

            for cmd in post_cmds:
                logger.info(f'Sending post-transfer command: {repr(cmd)}')
                ser.write(cmd.encode('utf-8', errors='replace'))
                _log_line(cmd, 'TX')
                time.sleep(0.3)

            # Capture output with idle timeout
            idle_timeout = port.idle_timeout_seconds or 5
            max_runtime = port.max_runtime_seconds or 300
            start_time = time.time()
            last_activity = start_time

            logger.info(f'Capturing output (idle timeout: {idle_timeout}s, max runtime: {max_runtime}s)')
            _log_line(f'Capturing output...', 'SYS')

            while True:
                elapsed = time.time() - start_time
                if elapsed > max_runtime:
                    _log_line(f'Maximum runtime ({max_runtime}s) reached', 'SYS')
                    break

                try:
                    if ser.in_waiting:
                        try:
                            data = ser.read(ser.in_waiting)
                        except SerialException:
                            data = None
                        if data:
                            decoded = data.decode('utf-8', errors='replace')
                            _log_line(decoded, 'RX')
                            last_activity = time.time()
                    else:
                        time.sleep(0.1)
                        if time.time() - last_activity > idle_timeout:
                            _log_line(f'Idle timeout ({idle_timeout}s) reached', 'SYS')
                            break
                except (OSError, SerialException):
                    _log_line('PTY closed — output capture complete', 'SYS')
                    break

            job.status = 'completed'
            job.finished_at = datetime.now(timezone.utc)
            job.runtime_seconds = int(time.time() - start_time)
            job.exit_code = 0
            _log_line(f'Job completed successfully ({job.runtime_seconds}s)', 'SYS')
            return True

    except SerialException as e:
        logger.error(f'Serial error: {e}')
        job.status = 'failed'
        job.error_message = f'Serial error: {e}'
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
            job = claim_job(session, device_name)
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

                success = run_job_on_device(job, port, logger)

                session.add(job)
                session.commit()

                status = 'completed' if success else 'failed'
                logger.info(f'Job #{job.id} {status}')

            # Check for force-canceled jobs
            canceled = (
                session.query(Job)
                .filter_by(device_id=job.device_id if job else None, status='canceled')
                .all()
            )
            for cj in canceled:
                logger.info(f'Job #{cj.id} was force-canceled')
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
