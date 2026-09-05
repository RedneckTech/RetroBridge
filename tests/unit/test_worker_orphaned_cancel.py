"""Tests for orphaned cancel request processing in the worker loop."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from retrobridge.models import Device, DevicePort, Job, User
from worker import worker_loop


def _setup(db_session, device_name='orphdev', username='orphuser'):
    user = User(username=username, email=f'{username}@example.com', password_hash='h')
    device = Device(name=device_name, is_enabled=True)
    db_session.add_all([user, device])
    db_session.flush()
    port = DevicePort(device_id=device.id, port_label='T0', dev_path='/dev/tty0',
                      purpose='job_queue')
    db_session.add(port)
    db_session.flush()
    return user, device, port


def test_orphaned_cancel_request_is_processed_when_no_job_claimed(db_session):
    """When no job is available to claim, queued cancel_requested jobs are
    still marked canceled."""
    user, device, port = _setup(db_session)
    job = Job(user_id=user.id, device_id=device.id, port_id=port.id,
              original_filename='orphan.bin', status='queued',
              cancel_requested=True)
    db_session.add(job)
    db_session.commit()

    logger = MagicMock()
    engine = db_session.bind

    # Run one iteration of the worker loop and then stop.
    with patch('worker.setup_logging', return_value=logger), \
         patch('worker.build_engine', return_value=engine), \
         patch('worker.signal.signal'), \
         patch('worker.time.sleep', side_effect=RuntimeError('stop')):
        try:
            worker_loop(device.name, poll_interval=1)
        except RuntimeError:
            pass

    db_session.refresh(job)
    assert job.status == 'canceled'


def test_orphaned_cancel_only_affects_target_device(db_session):
    user, device_a, port_a = _setup(db_session, 'dev_a')
    _, device_b, port_b = _setup(db_session, 'dev_b', username='orphuser_b')
    job_a = Job(user_id=user.id, device_id=device_a.id, port_id=port_a.id,
                original_filename='a.bin', status='queued', cancel_requested=True)
    job_b = Job(user_id=user.id, device_id=device_b.id, port_id=port_b.id,
                original_filename='b.bin', status='queued', cancel_requested=True)
    db_session.add_all([job_a, job_b])
    db_session.commit()

    logger = MagicMock()
    engine = db_session.bind

    with patch('worker.setup_logging', return_value=logger), \
         patch('worker.build_engine', return_value=engine), \
         patch('worker.signal.signal'), \
         patch('worker.time.sleep', side_effect=RuntimeError('stop')):
        try:
            worker_loop(device_a.name, poll_interval=1)
        except RuntimeError:
            pass

    db_session.refresh(job_a)
    db_session.refresh(job_b)
    assert job_a.status == 'canceled'
    assert job_b.status == 'queued'
