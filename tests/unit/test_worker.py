"""Unit tests for the job worker."""
import os
from unittest.mock import Mock, patch, MagicMock, call

from retrobridge.models import User, Device, DevicePort, Job
from worker import claim_job, get_serial_params


def _setup_device_and_port(db_session, device_name='centurion', purpose='job_queue',
                            is_enabled=True, **port_kwargs):
    device = Device(name=device_name, is_enabled=is_enabled)
    db_session.add(device)
    db_session.flush()

    port = DevicePort(
        device_id=device.id,
        port_label=port_kwargs.pop('port_label', 'TTY0'),
        dev_path=port_kwargs.pop('dev_path', '/dev/tty0'),
        purpose=purpose,
        **port_kwargs,
    )
    db_session.add(port)
    db_session.flush()
    return device, port


class TestClaimJob:
    def test_claims_highest_priority_job(self, db_session):
        device, port = _setup_device_and_port(db_session)

        user = User(username='testuser', email='test@example.com', password_hash='hash')
        db_session.add(user)
        db_session.flush()

        job_low = Job(user_id=user.id, device_id=device.id,
                      original_filename='low.bin', status='queued', priority=0)
        job_high = Job(user_id=user.id, device_id=device.id,
                       original_filename='high.bin', status='queued', priority=9)
        db_session.add_all([job_low, job_high])
        db_session.commit()

        claimed = claim_job(db_session, 'centurion')
        assert claimed is not None
        assert claimed.original_filename == 'high.bin'
        assert claimed.status == 'running'
        assert claimed.port_id == port.id
        assert claimed.started_at is not None
        assert claimed.worker_pid == os.getpid()

    def test_returns_none_when_no_queued_jobs(self, db_session):
        _setup_device_and_port(db_session)
        db_session.commit()

        claimed = claim_job(db_session, 'centurion')
        assert claimed is None

    def test_returns_none_when_device_disabled(self, db_session):
        _setup_device_and_port(db_session, is_enabled=False)
        db_session.commit()

        claimed = claim_job(db_session, 'centurion')
        assert claimed is None

    def test_returns_none_when_no_job_ports(self, db_session):
        _setup_device_and_port(db_session, purpose='interactive')
        db_session.commit()

        claimed = claim_job(db_session, 'centurion')
        assert claimed is None

    def test_respects_concurrency_limit(self, db_session):
        device, port = _setup_device_and_port(db_session, max_concurrent_jobs=1)

        user = User(username='testuser', email='test@example.com', password_hash='hash')
        db_session.add(user)
        db_session.flush()

        running_job = Job(user_id=user.id, device_id=device.id,
                          port_id=port.id,
                          original_filename='running.bin', status='running')
        queued_job = Job(user_id=user.id, device_id=device.id,
                         original_filename='queued.bin', status='queued')
        db_session.add_all([running_job, queued_job])
        db_session.commit()

        claimed = claim_job(db_session, 'centurion')
        assert claimed is None

    def test_unknown_device_returns_none(self, db_session):
        claimed = claim_job(db_session, 'nonexistent')
        assert claimed is None

    def test_skips_disabled_ports(self, db_session):
        device, port = _setup_device_and_port(db_session, is_enabled=False)
        db_session.commit()

        claimed = claim_job(db_session, 'centurion')
        assert claimed is None


class TestSerialParams:
    def test_default_params(self):
        port = DevicePort(
            port_label='TTY0', dev_path='/dev/ttyUSB0',
            purpose='job_queue',
        )
        params = get_serial_params(port)
        assert params['port'] == '/dev/ttyUSB0'
        assert params['baudrate'] == 9600
        assert params['bytesize'] == 8
        assert params['parity'] == 'N'
        assert params['stopbits'] == 1
        assert params['rtscts'] is False
        assert params['xonxoff'] is False

    def test_custom_params(self):
        port = DevicePort(
            port_label='TTY1', dev_path='/dev/ttyS0',
            purpose='job_queue', baud=19200, data_bits=7,
            parity='E', stop_bits=2, flow_control='rtscts',
        )
        params = get_serial_params(port)
        assert params['baudrate'] == 19200
        assert params['bytesize'] == 7
        assert params['parity'] == 'E'
        assert params['stopbits'] == 2
        assert params['rtscts'] is True

    def test_xonxoff_flow_control(self):
        port = DevicePort(
            port_label='TTY0', dev_path='/dev/ttyUSB0',
            purpose='job_queue', flow_control='xonxoff',
        )
        params = get_serial_params(port)
        assert params['rtscts'] is False
        assert params['xonxoff'] is True
