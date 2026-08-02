"""Unit tests for the job worker."""
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from retrobridge.models import User, Device, DevicePort, Job
from worker import (JOB_LEASE_SECONDS, claim_job, get_serial_params,
                    recover_stale_jobs)


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
        assert claimed.claimed_by is not None
        assert claimed.claimed_by.endswith(':centurion')
        assert claimed.claimed_at is not None
        assert claimed.lease_expires_at is not None
        assert claimed.heartbeat_at is not None
        assert claimed.lease_expires_at > claimed.claimed_at

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
        _setup_device_and_port(db_session, port_label='DISABLED', is_enabled=False)
        db_session.commit()

        claimed = claim_job(db_session, 'centurion')
        assert claimed is None

    def test_concurrent_claim_only_one_succeeds(self, app):
        engine = app.db_engine
        session1 = Session(bind=engine)
        session2 = Session(bind=engine)

        try:
            device = Device(name='concurrent_dev', is_enabled=True)
            session1.add(device)
            session1.flush()
            port = DevicePort(
                device_id=device.id, port_label='C0', dev_path='/dev/ct0',
                purpose='job_queue',
            )
            session1.add(port)
            session1.flush()

            user = User(username='cuser', email='c@example.com', password_hash='h')
            session1.add(user)
            session1.flush()

            job = Job(user_id=user.id, device_id=device.id,
                      original_filename='only.bin', status='queued', priority=0)
            session1.add(job)
            session1.commit()
            session2.commit()

            claimed1 = claim_job(session1, 'concurrent_dev')
            claimed2 = claim_job(session2, 'concurrent_dev')

            claims = [c for c in (claimed1, claimed2) if c is not None]
            assert len(claims) == 1
            assert claims[0].original_filename == 'only.bin'
        finally:
            session1.close()
            session2.close()

    def test_concurrent_claim_picks_next_job(self, app):
        engine = app.db_engine
        session1 = Session(bind=engine)
        session2 = Session(bind=engine)

        try:
            device = Device(name='cd2', is_enabled=True)
            session1.add(device)
            session1.flush()
            port = DevicePort(
                device_id=device.id, port_label='C0', dev_path='/dev/ct0',
                purpose='job_queue', max_concurrent_jobs=2,
            )
            session1.add(port)
            session1.flush()

            user = User(username='cu2', email='c2@example.com', password_hash='h')
            session1.add(user)
            session1.flush()

            job_a = Job(user_id=user.id, device_id=device.id,
                        original_filename='a.bin', status='queued', priority=0)
            job_b = Job(user_id=user.id, device_id=device.id,
                        original_filename='b.bin', status='queued', priority=0)
            session1.add_all([job_a, job_b])
            session1.commit()
            session2.commit()

            claimed1 = claim_job(session1, 'cd2')
            claimed2 = claim_job(session2, 'cd2')

            assert claimed1 is not None
            assert claimed2 is not None
            assert claimed1.id != claimed2.id
            assert {claimed1.original_filename, claimed2.original_filename} == {'a.bin', 'b.bin'}
        finally:
            session1.close()
            session2.close()


class TestRecoverStaleJobs:
    def test_expired_lease_reset_to_queued(self, db_session):
        device, port = _setup_device_and_port(db_session)

        user = User(username='staleuser', email='s@example.com', password_hash='h')
        db_session.add(user)
        db_session.flush()

        now = datetime.now(timezone.utc)
        expired = now - timedelta(seconds=600)
        job = Job(
            user_id=user.id, device_id=device.id,
            original_filename='orphan.bin', status='running',
            port_id=port.id, started_at=expired, worker_pid=99999,
            claimed_by='ghost:99999:centurion', claimed_at=expired,
            lease_expires_at=now - timedelta(seconds=60),
            heartbeat_at=expired,
        )
        db_session.add(job)
        db_session.commit()

        recover_stale_jobs(db_session, device.id)

        db_session.expire_all()
        refreshed = db_session.get(Job, job.id)
        assert refreshed.status == 'queued'
        assert refreshed.port_id is None
        assert refreshed.started_at is None
        assert refreshed.worker_pid is None
        assert refreshed.claimed_by is None
        assert refreshed.claimed_at is None
        assert refreshed.lease_expires_at is None
        assert refreshed.heartbeat_at is None

    def test_active_lease_not_reset(self, db_session):
        device, port = _setup_device_and_port(db_session)

        user = User(username='activeuser', email='a@example.com', password_hash='h')
        db_session.add(user)
        db_session.flush()

        now = datetime.now(timezone.utc)
        future = now + timedelta(seconds=600)
        job = Job(
            user_id=user.id, device_id=device.id,
            original_filename='alive.bin', status='running',
            port_id=port.id, started_at=now, worker_pid=12345,
            claimed_by='alive:12345:centurion', claimed_at=now,
            lease_expires_at=future, heartbeat_at=now,
        )
        db_session.add(job)
        db_session.commit()

        recover_stale_jobs(db_session, device.id)

        db_session.expire_all()
        refreshed = db_session.get(Job, job.id)
        assert refreshed.status == 'running'
        assert refreshed.port_id == port.id
        assert refreshed.claimed_by == 'alive:12345:centurion'
        assert refreshed.lease_expires_at == future.replace(tzinfo=None)

    def test_claim_job_recovers_stale_before_claiming(self, db_session):
        device, port = _setup_device_and_port(db_session)

        user = User(username='recuser', email='r@example.com', password_hash='h')
        db_session.add(user)
        db_session.flush()

        now = datetime.now(timezone.utc)
        expired = now - timedelta(seconds=600)
        stale = Job(
            user_id=user.id, device_id=device.id,
            original_filename='stale.bin', status='running',
            port_id=port.id, started_at=expired, worker_pid=99999,
            claimed_by='dead:99999:centurion', claimed_at=expired,
            lease_expires_at=now - timedelta(seconds=60),
            heartbeat_at=expired,
            created_at=now - timedelta(seconds=1200),
        )
        new_job = Job(
            user_id=user.id, device_id=device.id,
            original_filename='fresh.bin', status='queued', priority=1,
            created_at=now - timedelta(seconds=1),
        )
        db_session.add_all([stale, new_job])
        db_session.commit()

        claimed = claim_job(db_session, 'centurion')

        assert claimed is not None
        assert claimed.original_filename == 'fresh.bin'

        db_session.expire_all()
        stale_refreshed = db_session.get(Job, stale.id)
        assert stale_refreshed.status == 'queued'
        assert stale_refreshed.claimed_by is None

    def test_no_lease_column_skipped(self, db_session):
        device, port = _setup_device_and_port(db_session)

        user = User(username='nolease', email='nl@example.com', password_hash='h')
        db_session.add(user)
        db_session.flush()

        job = Job(
            user_id=user.id, device_id=device.id,
            original_filename='legacy.bin', status='running',
            port_id=port.id, started_at=datetime.now(timezone.utc),
            worker_pid=55555,
        )
        db_session.add(job)
        db_session.commit()

        recover_stale_jobs(db_session, device.id)

        db_session.expire_all()
        refreshed = db_session.get(Job, job.id)
        assert refreshed.status == 'running'


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
