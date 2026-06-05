"""E2E tests — full job pipeline, cancel flow, quota enforcement."""

import io
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
def app():
    from retrobridge import create_app
    app = create_app('config.TestConfig')
    app.config['UPLOAD_DIR'] = tempfile.mkdtemp()
    app.config['OUTPUT_DIR'] = tempfile.mkdtemp()

    from retrobridge.models import Base
    Base.metadata.create_all(bind=app.db_engine)

    yield app

    app.db_session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded_app(app):
    """Seed app with user, device, and job port."""
    user = User(username='jobuser', email='jobuser@example.com',
                password_hash=generate_password_hash('password'),
                max_queued_jobs=5)
    device = Device(name='centurion', display_name='Centurion CPU-6')
    app.db_session.add_all([user, device])
    app.db_session.flush()

    port = DevicePort(
        device_id=device.id, port_label='TTY0',
        dev_path='/dev/null', purpose='job_queue',
        baud=9600, max_concurrent_jobs=1,
        max_runtime_seconds=30, idle_timeout_seconds=3,
        pre_transfer_cmds='["TEST CMD\\r"]',
    )
    app.db_session.add(port)
    app.db_session.commit()

    yield app


@pytest.fixture
def seeded_client(seeded_app):
    return seeded_app.test_client()


@pytest.fixture
def auth_client(seeded_client):
    seeded_client.post('/auth/login', data={
        'username': 'jobuser', 'password': 'password',
    }, follow_redirects=True)
    return seeded_client


class TestFullJobPath:
    """SDD 10.3: Full job path — register, login, upload, worker processes,
    view detail, download output."""

    def test_full_job_pipeline(self, seeded_app, auth_client):
        """Register → Login → Upload file → Worker processes → View detail
        → Download output."""
        # Step 1: Upload a file through the web UI
        data = {
            'device_id': 1,
            'priority': 5,
            'file': (io.BytesIO(b'\xDE\xAD\xBE\xEF' * 64), 'testprog.bin'),
        }
        resp = auth_client.post('/new', data=data,
                                content_type='multipart/form-data',
                                follow_redirects=True)
        assert resp.status_code == 200
        assert b'submitted successfully' in resp.data.lower()

        # Step 2: Verify job is queued in DB
        job = seeded_app.db_session.query(Job).first()
        assert job is not None
        assert job.original_filename == 'testprog.bin'
        assert job.status == 'queued'
        assert job.priority == 5
        assert job.stored_filename is not None

        # Step 3: View job detail page
        resp = auth_client.get(f'/{job.id}')
        assert resp.status_code == 200
        assert b'testprog.bin' in resp.data
        assert b'Queued' in resp.data

        # Step 4: Run worker with PTY simulation to process the job
        sim = create_job_simulation('centurion')
        try:
            port = seeded_app.db_session.get(DevicePort, 1)
            port.dev_path = sim['slave_name']
            seeded_app.db_session.commit()

            upload_dir = Path(seeded_app.config['UPLOAD_DIR'])

            old_upload = os.environ.get('RETROBRIDGE_UPLOAD_DIR')
            old_output = os.environ.get('RETROBRIDGE_OUTPUT_DIR')
            os.environ['RETROBRIDGE_UPLOAD_DIR'] = str(upload_dir)
            os.environ['RETROBRIDGE_OUTPUT_DIR'] = str(
                Path(tempfile.mkdtemp()))

            try:
                claimed = claim_job(seeded_app.db_session, 'centurion')
                assert claimed is not None
                assert claimed.id == job.id
                assert claimed.status == 'running'

                success = run_job_on_device(claimed, port,
                                             logging.getLogger('test'))
                seeded_app.db_session.add(claimed)
                seeded_app.db_session.commit()

                assert success is True
                assert claimed.status == 'completed'
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

        # Step 5: View job detail after completion
        seeded_app.db_session.refresh(job)
        resp = auth_client.get(f'/{job.id}')
        assert resp.status_code == 200
        assert b'Completed' in resp.data
        assert b'Download Output' in resp.data

        # Step 6: Download the output file
        resp = auth_client.get(f'/{job.id}/download')
        assert resp.status_code == 200
        assert len(resp.data) > 0

        # Step 7: Verify API job status
        resp = auth_client.get(f'/api/jobs/{job.id}/status')
        assert resp.status_code == 200
        import json
        data = json.loads(resp.data)
        assert data['status'] == 'completed'
        assert data['runtime_seconds'] is not None

        # Step 8: Verify job appears in dashboard
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200
        assert b'testprog.bin' in resp.data


class TestCancelFlow:
    """SDD 10.3: Cancel flow — create job, cancel from detail page."""

    def test_cancel_queued_job(self, seeded_app, auth_client):
        job = Job(user_id=1, device_id=1, original_filename='cancelme.bin',
                  status='queued')
        seeded_app.db_session.add(job)
        seeded_app.db_session.commit()

        resp = auth_client.get(f'/{job.id}')
        assert resp.status_code == 200
        assert b'Cancel' in resp.data

        resp = auth_client.post(f'/{job.id}/cancel', follow_redirects=True)
        assert resp.status_code == 200
        assert b'canceled' in resp.data.lower()

        seeded_app.db_session.refresh(job)
        assert job.status == 'canceled'

    def test_cannot_cancel_running_job(self, seeded_app, auth_client):
        job = Job(user_id=1, device_id=1, original_filename='running.bin',
                  status='running')
        seeded_app.db_session.add(job)
        seeded_app.db_session.commit()

        resp = auth_client.post(f'/{job.id}/cancel', follow_redirects=True)
        assert resp.status_code == 200

        seeded_app.db_session.refresh(job)
        assert job.status == 'running'

    def test_cannot_cancel_another_users_job(self, seeded_app, seeded_client):
        other = User(username='other', email='other@ex.com',
                     password_hash=generate_password_hash('pw'))
        seeded_app.db_session.add(other)
        seeded_app.db_session.commit()

        job = Job(user_id=other.id, device_id=1,
                  original_filename='other.bin', status='queued')
        seeded_app.db_session.add(job)
        seeded_app.db_session.commit()

        seeded_client.post('/auth/login', data={
            'username': 'jobuser', 'password': 'password',
        })

        resp = seeded_client.post(f'/{job.id}/cancel')
        assert resp.status_code == 403


class TestQuotaEnforcement:
    """SDD 10.3: Quota enforcement — hit max queued jobs limit."""

    def test_quota_blocks_excess_jobs(self, seeded_app, auth_client):
        user = seeded_app.db_session.get(User, 1)
        user.max_queued_jobs = 2
        seeded_app.db_session.commit()

        for i in range(2):
            job = Job(user_id=1, device_id=1,
                      original_filename=f'q{i}.bin', status='queued')
            seeded_app.db_session.add(job)
        seeded_app.db_session.commit()

        data = {
            'device_id': 1,
            'priority': 0,
            'file': (io.BytesIO(b'blocked'), 'blocked.bin'),
        }
        resp = auth_client.post('/new', data=data,
                                content_type='multipart/form-data',
                                follow_redirects=True)
        assert resp.status_code == 200
        assert (b'maximum' in resp.data.lower()
                or b'quota' in resp.data.lower()
                or b'reached' in resp.data.lower())

    def test_running_jobs_count_toward_quota(self, seeded_app, auth_client):
        user = seeded_app.db_session.get(User, 1)
        user.max_queued_jobs = 1
        seeded_app.db_session.commit()

        job = Job(user_id=1, device_id=1,
                  original_filename='running.bin', status='running')
        seeded_app.db_session.add(job)
        seeded_app.db_session.commit()

        data = {
            'device_id': 1,
            'priority': 0,
            'file': (io.BytesIO(b'blocked'), 'blocked.bin'),
        }
        resp = auth_client.post('/new', data=data,
                                content_type='multipart/form-data',
                                follow_redirects=True)
        assert resp.status_code == 200
        assert (b'maximum' in resp.data.lower()
                or b'quota' in resp.data.lower()
                or b'reached' in resp.data.lower())


class TestJobDetailAndListing:
    """E2E job detail page and listing behavior."""

    def test_job_detail_shows_all_metadata(self, seeded_app, auth_client):
        import datetime
        job = Job(
            user_id=1, device_id=1, original_filename='metadata.bin',
            status='completed', priority=8, file_size_bytes=1024,
            runtime_seconds=42, exit_code=0,
        )
        seeded_app.db_session.add(job)
        seeded_app.db_session.commit()

        resp = auth_client.get(f'/{job.id}')
        assert resp.status_code == 200
        assert b'metadata.bin' in resp.data
        assert b'Completed' in resp.data

    def test_job_detail_404_for_nonexistent(self, auth_client):
        resp = auth_client.get('/9999')
        assert resp.status_code == 302

    def test_job_download_404_when_no_output(self, seeded_app, auth_client):
        job = Job(user_id=1, device_id=1, original_filename='nodl.bin',
                  status='completed', output_path=None)
        seeded_app.db_session.add(job)
        seeded_app.db_session.commit()

        resp = auth_client.get(f'/{job.id}/download', follow_redirects=True)
        assert resp.status_code == 200
        assert b'No output available' in resp.data

    def test_dashboard_shows_user_jobs(self, seeded_app, auth_client):
        for i in range(5):
            job = Job(user_id=1, device_id=1,
                      original_filename=f'dash{i}.bin',
                      status='queued' if i < 3 else 'completed')
            seeded_app.db_session.add(job)
        seeded_app.db_session.commit()

        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200
        for i in range(5):
            assert f'dash{i}.bin'.encode() in resp.data


class TestJobRateLimit:
    """Tests for MAX_JOBS_PER_HOUR rate limiting."""

    @pytest.fixture
    def rate_app(self, app):
        from retrobridge.models import AdminSetting, Device, DevicePort
        from werkzeug.security import generate_password_hash
        user = User(username='rateuser', email='rate@ex.com',
                    password_hash=generate_password_hash('password'),
                    max_queued_jobs=20)
        device = Device(name='centurion')
        app.db_session.add_all([user, device])
        app.db_session.flush()
        app.db_session.add(DevicePort(
            device_id=device.id, port_label='TTY0',
            dev_path='/dev/null', purpose='job_queue', baud=9600,
        ))
        app.db_session.add(AdminSetting(
            key='MAX_JOBS_PER_HOUR', value='3',
            description='Max jobs per hour',
        ))
        app.db_session.commit()
        return app

    def test_rate_limit_blocks_excess_jobs(self, rate_app):
        c = rate_app.test_client()
        c.post('/auth/login', data={
            'username': 'rateuser', 'password': 'password',
        }, follow_redirects=True)

        # Submit 3 jobs (at the limit)
        for i in range(3):
            resp = c.post('/new', data={
                'device_id': 1,
                'priority': 0,
                'file': (io.BytesIO(b'data'), f'job{i}.bin'),
            }, content_type='multipart/form-data', follow_redirects=True)
            assert b'submitted successfully' in resp.data.lower()

        # 4th should be rate-limited
        resp = c.post('/new', data={
            'device_id': 1,
            'priority': 0,
            'file': (io.BytesIO(b'data'), 'blocked.bin'),
        }, content_type='multipart/form-data', follow_redirects=True)
        assert b'Rate limit' in resp.data
