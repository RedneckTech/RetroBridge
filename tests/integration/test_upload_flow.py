"""Integration tests — file upload flow via HTTP."""
import io
import os
import tempfile

import pytest
from werkzeug.security import generate_password_hash

from retrobridge.models import Device, DevicePort, Job, User


@pytest.fixture
def app():
    from retrobridge import create_app
    app = create_app('config.TestConfig')
    app.config['UPLOAD_DIR'] = tempfile.mkdtemp()
    app.config['OUTPUT_DIR'] = tempfile.mkdtemp()

    from retrobridge.models import Base
    Base.metadata.create_all(bind=app.db_engine)

    # Seed a user and device
    user = User(username='testuser', email='test@example.com',
                password_hash=generate_password_hash('password'),
                max_queued_jobs=3)
    device = Device(name='centurion', display_name='Centurion CPU-6')
    app.db_session.add(user)
    app.db_session.add(device)
    app.db_session.flush()

    port = DevicePort(
        device_id=device.id, port_label='TTY0',
        dev_path='/dev/null', purpose='job_queue',
    )
    app.db_session.add(port)
    app.db_session.commit()

    yield app

    app.db_session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client):
    client.post('/auth/login', data={
        'username': 'testuser',
        'password': 'password',
    }, follow_redirects=True)
    return client


class TestUploadFlow:
    def test_login_and_upload(self, client, app):
        """Log in, upload a file, verify job created."""
        # Login
        resp = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'password',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Log In' not in resp.data

        # Upload a file
        data = {
            'device_id': 1,
            'priority': 5,
            'file': (io.BytesIO(b'HELLO WORLD' * 10), 'test.bin'),
        }
        resp = client.post('/new', data=data,
                           content_type='multipart/form-data',
                           follow_redirects=True)
        assert resp.status_code == 200

        # Verify job created
        job = app.db_session.query(Job).first()
        assert job is not None
        assert job.original_filename == 'test.bin'
        assert job.status == 'queued'
        assert job.priority == 5
        assert job.user_id == 1

    def test_upload_unauthenticated(self, client):
        """Unauthenticated upload redirects to login."""
        data = {
            'device_id': 1,
            'file': (io.BytesIO(b'data'), 'test.bin'),
        }
        resp = client.post('/new', data=data,
                           content_type='multipart/form-data')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_quota_enforcement(self, auth_client, app):
        """Upload is rejected when user hits max queued jobs limit."""
        user = app.db_session.get(User, 1)
        user.max_queued_jobs = 1
        device = app.db_session.get(Device, 1)
        app.db_session.commit()

        # Create one queued job
        job = Job(user_id=1, device_id=1, original_filename='first.bin',
                  status='queued')
        app.db_session.add(job)
        app.db_session.commit()

        # Try to upload another
        data = {
            'device_id': 1,
            'priority': 0,
            'file': (io.BytesIO(b'second'), 'second.bin'),
        }
        resp = auth_client.post('/new', data=data,
                                content_type='multipart/form-data',
                                follow_redirects=True)
        assert resp.status_code == 200
        assert b'maximum' in resp.data.lower() or b'quota' in resp.data.lower() or b'reached' in resp.data.lower()

    def test_job_detail_shows_metadata(self, auth_client, app):
        """Job detail page shows job metadata."""
        job = Job(user_id=1, device_id=1, original_filename='detail.bin',
                  status='queued', priority=3)
        app.db_session.add(job)
        app.db_session.commit()

        resp = auth_client.get(f'/{job.id}')
        assert resp.status_code == 200
        assert b'detail.bin' in resp.data
        assert b'Queued' in resp.data

    def test_job_detail_denied_for_wrong_user(self, client, app):
        """User cannot view another user's job."""
        # Create another user
        other = User(username='other', email='other@example.com',
                     password_hash=generate_password_hash('pw'))
        app.db_session.add(other)
        app.db_session.commit()

        job = Job(user_id=other.id, device_id=1,
                  original_filename='private.bin', status='queued')
        app.db_session.add(job)
        app.db_session.commit()

        # Login as testuser
        client.post('/auth/login', data={
            'username': 'testuser', 'password': 'password',
        })

        resp = client.get(f'/{job.id}')
        assert resp.status_code == 403

    def test_cancel_queued_job(self, auth_client, app):
        """User can cancel their own queued job."""
        job = Job(user_id=1, device_id=1, original_filename='cancelme.bin',
                  status='queued')
        app.db_session.add(job)
        app.db_session.commit()

        resp = auth_client.post(f'/{job.id}/cancel',
                                follow_redirects=True)
        assert resp.status_code == 200

        app.db_session.refresh(job)
        assert job.status == 'canceled'

    def test_cannot_cancel_running_job(self, auth_client, app):
        """User cannot cancel a running job."""
        job = Job(user_id=1, device_id=1, original_filename='running.bin',
                  status='running')
        app.db_session.add(job)
        app.db_session.commit()

        resp = auth_client.post(f'/{job.id}/cancel',
                                follow_redirects=True)
        assert resp.status_code == 200

        app.db_session.refresh(job)
        assert job.status == 'running'
