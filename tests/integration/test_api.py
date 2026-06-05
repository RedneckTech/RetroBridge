"""Integration tests — REST API endpoints."""
import io
import json
import tempfile

import pytest
from werkzeug.security import generate_password_hash

from retrobridge.models import Device, DevicePort, Job, TerminalSession, User


@pytest.fixture
def app():
    from retrobridge import create_app
    app = create_app('config.TestConfig')
    app.config['UPLOAD_DIR'] = tempfile.mkdtemp()
    app.config['OUTPUT_DIR'] = tempfile.mkdtemp()

    from retrobridge.models import Base
    Base.metadata.create_all(bind=app.db_engine)

    user = User(username='testuser', email='test@example.com',
                password_hash=generate_password_hash('password'),
                max_queued_jobs=5)
    admin = User(username='admin', email='admin@example.com',
                 password_hash=generate_password_hash('admin'),
                 is_admin=True)
    device = Device(name='centurion', display_name='Centurion CPU-6')
    app.db_session.add_all([user, admin, device])
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
        'username': 'testuser', 'password': 'password',
    })
    return client


@pytest.fixture
def admin_client(client):
    client.post('/auth/login', data={
        'username': 'admin', 'password': 'admin',
    })
    return client


class TestAPIJobs:
    def test_list_jobs_requires_auth(self, client):
        resp = client.get('/api/jobs')
        assert resp.status_code == 302

    def test_list_jobs_returns_json(self, auth_client, app):
        job = Job(user_id=1, device_id=1, original_filename='test.bin',
                  status='queued')
        app.db_session.add(job)
        app.db_session.commit()

        resp = auth_client.get('/api/jobs')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['total'] == 1
        assert len(data['jobs']) == 1
        assert data['jobs'][0]['original_filename'] == 'test.bin'
        assert data['jobs'][0]['status'] == 'queued'

    def test_list_jobs_paginated(self, auth_client, app):
        for i in range(25):
            job = Job(user_id=1, device_id=1,
                      original_filename=f'test{i}.bin', status='queued')
            app.db_session.add(job)
        app.db_session.commit()

        resp = auth_client.get('/api/jobs?page=1&per_page=10')
        data = json.loads(resp.data)
        assert data['total'] == 25
        assert len(data['jobs']) == 10
        assert data['pages'] == 3

    def test_job_status_requires_ownership(self, client, app):
        job = Job(user_id=1, device_id=1, original_filename='test.bin',
                  status='queued')
        app.db_session.add(job)
        app.db_session.commit()

        resp = client.get(f'/api/jobs/{job.id}/status')
        assert resp.status_code == 302

    def test_job_status_returns_data(self, auth_client, app):
        job = Job(user_id=1, device_id=1, original_filename='test.bin',
                  status='running')
        app.db_session.add(job)
        app.db_session.commit()

        resp = auth_client.get(f'/api/jobs/{job.id}/status')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['id'] == job.id
        assert data['status'] == 'running'

    def test_cancel_queued_job_via_api(self, auth_client, app):
        job = Job(user_id=1, device_id=1, original_filename='cancel.bin',
                  status='queued')
        app.db_session.add(job)
        app.db_session.commit()

        resp = auth_client.post(f'/api/jobs/{job.id}/cancel')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

        app.db_session.refresh(job)
        assert job.status == 'canceled'

    def test_admin_can_view_all_jobs(self, admin_client, app):
        other_user = User(username='other', email='o@ex.com',
                          password_hash=generate_password_hash('pw'))
        app.db_session.add(other_user)
        app.db_session.commit()

        job1 = Job(user_id=1, device_id=1, original_filename='a.bin',
                   status='queued')
        job2 = Job(user_id=other_user.id, device_id=1,
                   original_filename='b.bin', status='queued')
        app.db_session.add_all([job1, job2])
        app.db_session.commit()

        resp = admin_client.get('/api/jobs')
        data = json.loads(resp.data)
        assert data['total'] == 2


class TestAPIDevices:
    def test_list_devices(self, auth_client):
        resp = auth_client.get('/api/devices')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data['devices']) == 1
        assert data['devices'][0]['name'] == 'centurion'

    def test_device_ports(self, auth_client):
        resp = auth_client.get('/api/devices/1/ports')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data['ports']) == 1
        assert data['ports'][0]['purpose'] == 'job_queue'


class TestAPISessions:
    def test_active_sessions_requires_admin(self, auth_client):
        resp = auth_client.get('/api/sessions/active')
        assert resp.status_code == 403

    def test_active_sessions_list(self, admin_client, app):
        resp = admin_client.get('/api/sessions/active')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['sessions'] == []

    def test_disconnect_session_requires_admin(self, auth_client):
        resp = auth_client.post('/api/sessions/1/disconnect')
        assert resp.status_code == 403


class TestAPIAdmin:
    def test_admin_cancel_job(self, admin_client, app):
        job = Job(user_id=1, device_id=1, original_filename='killme.bin',
                  status='running')
        app.db_session.add(job)
        app.db_session.commit()

        resp = admin_client.post(f'/api/admin/jobs/{job.id}/cancel')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

        app.db_session.refresh(job)
        assert job.status == 'canceled'

    def test_admin_delete_user(self, admin_client, app):
        other = User(username='victim', email='v@ex.com',
                     password_hash=generate_password_hash('pw'))
        app.db_session.add(other)
        app.db_session.commit()

        resp = admin_client.delete(f'/api/admin/users/{other.id}')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

    def test_admin_cannot_delete_self(self, admin_client):
        resp = admin_client.delete('/api/admin/users/2')
        assert resp.status_code == 400

    def test_admin_cancel_job_requires_admin(self, auth_client):
        resp = auth_client.post('/api/admin/jobs/1/cancel')
        assert resp.status_code == 403
