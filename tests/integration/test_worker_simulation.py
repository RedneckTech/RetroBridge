"""Integration tests — full job processing pipeline with PTY simulation."""
import logging
import os
import tempfile
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from retrobridge.models import Device, DevicePort, Job, User
from retrobridge.simulation import create_job_simulation
from worker import claim_job, run_job_on_device


@pytest.fixture
def job_app():
    from retrobridge import create_app
    app = create_app('config.TestConfig')
    from retrobridge.models import Base
    Base.metadata.create_all(bind=app.db_engine)

    # Override temp dirs
    app.config['UPLOAD_DIR'] = tempfile.mkdtemp()
    app.config['OUTPUT_DIR'] = tempfile.mkdtemp()

    yield app
    app.db_session.remove()


@pytest.fixture
def job_session(job_app):
    return job_app.db_session


@pytest.fixture
def setup_job_env(job_session):
    user = User(username='testuser', email='test@example.com',
                password_hash=generate_password_hash('password'))
    device = Device(name='centurion')
    job_session.add(user)
    job_session.add(device)
    job_session.flush()

    port = DevicePort(
        device_id=device.id, port_label='TTY0',
        dev_path='/dev/null', purpose='job_queue',
        baud=9600, max_concurrent_jobs=1,
        max_runtime_seconds=30, idle_timeout_seconds=3,
        pre_transfer_cmds='["TEST CMD\\r"]',
        post_transfer_cmds=None,
    )
    job_session.add(port)
    job_session.commit()

    return {'user': user, 'device': device, 'port': port}


class TestWorkerSimulation:
    def test_full_job_pipeline(self, job_session, setup_job_env):
        """End-to-end: create job, start PTY sim, run worker, verify output."""
        sim = create_job_simulation('centurion')
        try:
            port = setup_job_env['port']
            port.dev_path = sim['slave_name']
            job_session.commit()

            # Create a test upload file
            upload_dir = Path(tempfile.mkdtemp())
            job_subdir = upload_dir / 'job-999'
            job_subdir.mkdir()
            test_file = job_subdir / 'test.bin'
            test_file.write_bytes(b'\xDE\xAD\xBE\xEF' * 32)

            job = Job(
                user_id=setup_job_env['user'].id,
                device_id=setup_job_env['device'].id,
                original_filename='test.bin',
                stored_filename=f'job-999/test.bin',
                status='queued',
                priority=5,
            )
            job_session.add(job)
            job_session.commit()

            old_upload = os.environ.get('RETROBRIDGE_UPLOAD_DIR')
            old_output = os.environ.get('RETROBRIDGE_OUTPUT_DIR')
            os.environ['RETROBRIDGE_UPLOAD_DIR'] = str(upload_dir)
            os.environ['RETROBRIDGE_OUTPUT_DIR'] = str(
                Path(tempfile.mkdtemp()))

            try:
                claimed = claim_job(job_session, 'centurion')
                assert claimed is not None
                assert claimed.status == 'running'

                success = run_job_on_device(claimed, port,
                                             logging.getLogger('test'))
                job_session.add(claimed)
                job_session.commit()

                assert success is True
                assert claimed.status == 'completed'
                assert claimed.runtime_seconds is not None
                assert claimed.output_path is not None
                assert os.path.exists(claimed.output_path)
            finally:
                if old_upload:
                    os.environ['RETROBRIDGE_UPLOAD_DIR'] = old_upload
                else:
                    os.environ.pop('RETROBRIDGE_UPLOAD_DIR', None)
                if old_output:
                    os.environ['RETROBRIDGE_OUTPUT_DIR'] = old_output
                else:
                    os.environ.pop('RETROBRIDGE_OUTPUT_DIR', None)
        finally:
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)

    def test_job_fails_with_missing_file(self, job_session, setup_job_env):
        """Worker marks job as failed when upload file is missing."""
        sim = create_job_simulation('centurion')
        try:
            port = setup_job_env['port']
            port.dev_path = sim['slave_name']
            job_session.commit()

            job = Job(
                user_id=setup_job_env['user'].id,
                device_id=setup_job_env['device'].id,
                original_filename='missing.bin',
                stored_filename='nonexistent/missing.bin',
                status='queued',
            )
            job_session.add(job)
            job_session.commit()

            claimed = claim_job(job_session, 'centurion')
            assert claimed is not None

            success = run_job_on_device(claimed, port,
                                         logging.getLogger('test'))
            job_session.add(claimed)
            job_session.commit()

            assert success is False
            assert claimed.status == 'failed'
        finally:
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)

    def test_claims_highest_priority(self, job_session, setup_job_env):
        """Worker claims the highest priority queued job first."""
        port = setup_job_env['port']
        user = setup_job_env['user']
        device = setup_job_env['device']

        job_low = Job(user_id=user.id, device_id=device.id,
                      original_filename='low.bin', status='queued',
                      priority=1)
        job_high = Job(user_id=user.id, device_id=device.id,
                       original_filename='high.bin', status='queued',
                       priority=9)
        job_session.add_all([job_low, job_high])
        job_session.commit()

        claimed = claim_job(job_session, 'centurion')
        assert claimed.original_filename == 'high.bin'

    def test_concurrency_limit(self, job_session, setup_job_env):
        """Worker does not claim jobs when port is at max concurrency."""
        port = setup_job_env['port']
        user = setup_job_env['user']
        device = setup_job_env['device']

        port.max_concurrent_jobs = 1
        running = Job(user_id=user.id, device_id=device.id, port_id=port.id,
                      original_filename='running.bin', status='running')
        queued = Job(user_id=user.id, device_id=device.id,
                     original_filename='queued.bin', status='queued')
        job_session.add_all([running, queued])
        job_session.commit()

        claimed = claim_job(job_session, 'centurion')
        assert claimed is None
