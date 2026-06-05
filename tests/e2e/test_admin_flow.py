"""E2E tests — admin management flows."""

import tempfile

import pytest
from werkzeug.security import generate_password_hash

from retrobridge.models import (
    AdminSetting, Device, DevicePort, Job, TerminalSession, User,
)


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
def admin_app(app):
    """Seed app with admin, regular user, device, and ports."""
    admin = User(username='admin', email='admin@example.com',
                 password_hash=generate_password_hash('admin'),
                 is_admin=True)
    user = User(username='reguser', email='reguser@example.com',
                password_hash=generate_password_hash('password'),
                is_admin=False, max_queued_jobs=3,
                max_terminal_sessions=1)
    app.db_session.add_all([admin, user])
    app.db_session.flush()

    device = Device(name='centurion', display_name='Centurion CPU-6')
    app.db_session.add(device)
    app.db_session.flush()

    job_port = DevicePort(
        device_id=device.id, port_label='TTY0',
        dev_path='/dev/null', purpose='job_queue',
        baud=9600,
    )
    interactive_port = DevicePort(
        device_id=device.id, port_label='TTY1',
        dev_path='/dev/null', purpose='interactive',
        baud=9600,
    )
    app.db_session.add_all([job_port, interactive_port])

    app.db_session.commit()

    yield app


@pytest.fixture
def admin_client(admin_app):
    c = admin_app.test_client()
    c.post('/auth/login', data={
        'username': 'admin', 'password': 'admin',
    }, follow_redirects=True)
    return c


@pytest.fixture
def regular_client(admin_app):
    """Return a client logged in as regular user."""
    c = admin_app.test_client()
    c.post('/auth/login', data={
        'username': 'reguser', 'password': 'password',
    }, follow_redirects=True)
    return c


class TestAdminUserManagement:
    """SDD 10.3: Admin user management — view users, toggle admin, edit
    quotas."""

    def test_admin_can_view_users_list(self, admin_client):
        resp = admin_client.get('/admin/users')
        assert resp.status_code == 200
        assert b'admin' in resp.data
        assert b'reguser' in resp.data

    def test_admin_can_edit_user_quotas(self, admin_app, admin_client):
        reguser = admin_app.db_session.query(User).filter_by(
            username='reguser').first()

        resp = admin_client.post(f'/admin/users/{reguser.id}', data={
            'email': 'reguser@example.com',
            'full_name': 'Regular User',
            'is_admin': True,
            'max_queued_jobs': 10,
            'max_terminal_sessions': 5,
        }, follow_redirects=True)
        assert resp.status_code == 200

        admin_app.db_session.refresh(reguser)
        assert reguser.is_admin is True
        assert reguser.max_queued_jobs == 10
        assert reguser.max_terminal_sessions == 5

    def test_admin_cannot_delete_self(self, admin_app, admin_client):
        admin_user = admin_app.db_session.query(User).filter_by(
            username='admin').first()
        resp = admin_client.post(f'/admin/users/{admin_user.id}/delete',
                                 follow_redirects=True)
        assert resp.status_code == 200
        assert b'Cannot delete your own' in resp.data

        admin_app.db_session.refresh(admin_user)
        assert admin_user is not None

    def test_admin_can_delete_user(self, admin_app, admin_client):
        victim = User(username='victim', email='victim@ex.com',
                      password_hash=generate_password_hash('pw'))
        admin_app.db_session.add(victim)
        admin_app.db_session.commit()

        resp = admin_client.post(f'/admin/users/{victim.id}/delete',
                                 follow_redirects=True)
        assert resp.status_code == 200
        assert b'User deleted' in resp.data

        deleted = admin_app.db_session.get(User, victim.id)
        assert deleted is None

    def test_non_admin_cannot_view_users(self, regular_client):
        resp = regular_client.get('/admin/users')
        assert resp.status_code == 403

    def test_non_admin_cannot_edit_users(self, regular_client):
        resp = regular_client.post('/admin/users/1', data={
            'email': 'admin@example.com',
            'full_name': '',
            'is_admin': True,
            'max_queued_jobs': 99,
            'max_terminal_sessions': 99,
        })
        assert resp.status_code == 403


class TestAdminPortManagement:
    """SDD 10.3: Admin port management — add/configure/disable ports."""

    def test_admin_can_view_devices_and_ports(self, admin_client):
        resp = admin_client.get('/admin/devices')
        assert resp.status_code == 200
        assert b'Centurion' in resp.data
        assert b'TTY0' in resp.data
        assert b'TTY1' in resp.data

    def test_admin_can_add_device(self, admin_app, admin_client):
        resp = admin_client.post('/admin/devices', data={
            'name': 'pdp11',
            'display_name': 'PDP-11/44',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Device added' in resp.data

        device = admin_app.db_session.query(Device).filter_by(
            name='pdp11').first()
        assert device is not None
        assert device.display_name == 'PDP-11/44'

    def test_admin_can_add_port(self, admin_app, admin_client):
        resp = admin_client.post('/admin/devices/1/ports', data={
            'port_label': 'TTY2',
            'dev_path': '/dev/ttyUSB2',
            'purpose': 'interactive',
            'baud': 19200,
            'data_bits': 8,
            'parity': 'N',
            'stop_bits': 1,
            'flow_control': 'none',
            'newline_mode': 'crlf',
            'max_runtime_seconds': 600,
            'idle_timeout_seconds': 60,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Port added' in resp.data

        port = admin_app.db_session.query(DevicePort).filter_by(
            port_label='TTY2').first()
        assert port is not None
        assert port.dev_path == '/dev/ttyUSB2'
        assert port.purpose == 'interactive'
        assert port.baud == 19200

    def test_non_admin_cannot_add_device(self, regular_client):
        resp = regular_client.post('/admin/devices', data={
            'name': 'hack',
            'display_name': 'Hacked Device',
        })
        assert resp.status_code == 403

    def test_non_admin_cannot_add_port(self, regular_client):
        resp = regular_client.post('/admin/devices/1/ports', data={
            'port_label': 'bad',
            'dev_path': '/dev/null',
            'purpose': 'interactive',
            'baud': 9600,
            'data_bits': 8,
            'parity': 'N',
            'stop_bits': 1,
            'flow_control': 'none',
            'newline_mode': 'crlf',
            'max_runtime_seconds': 300,
            'idle_timeout_seconds': 5,
        })
        assert resp.status_code == 403


class TestAdminJobs:
    """SDD 10.3: Admin job management."""

    def test_admin_can_view_all_jobs(self, admin_app, admin_client):
        job1 = Job(user_id=1, device_id=1, original_filename='admin_job.bin',
                   status='queued')
        job2 = Job(user_id=2, device_id=1,
                   original_filename='user_job.bin', status='queued')
        admin_app.db_session.add_all([job1, job2])
        admin_app.db_session.commit()

        resp = admin_client.get('/admin/jobs')
        assert resp.status_code == 200
        assert b'admin_job.bin' in resp.data
        assert b'user_job.bin' in resp.data

    def test_admin_can_filter_jobs_by_status(self, admin_app, admin_client):
        job1 = Job(user_id=1, device_id=1, original_filename='running.bin',
                   status='running')
        job2 = Job(user_id=1, device_id=1, original_filename='done.bin',
                   status='completed')
        admin_app.db_session.add_all([job1, job2])
        admin_app.db_session.commit()

        resp = admin_client.get('/admin/jobs?status=running')
        assert resp.status_code == 200
        assert b'running.bin' in resp.data
        assert b'done.bin' not in resp.data

    def test_admin_can_force_cancel_job(self, admin_app, admin_client):
        job = Job(user_id=2, device_id=1, original_filename='forcekill.bin',
                  status='running')
        admin_app.db_session.add(job)
        admin_app.db_session.commit()

        resp = admin_client.post(f'/api/admin/jobs/{job.id}/cancel')
        assert resp.status_code == 200

        admin_app.db_session.refresh(job)
        assert job.status == 'canceled'


class TestAdminSessions:
    """SDD 10.3: Admin session management and force-disconnect."""

    def test_admin_can_view_sessions(self, admin_client):
        resp = admin_client.get('/admin/sessions')
        assert resp.status_code == 200

    def test_admin_can_disconnect_active_session(self, admin_app,
                                                   admin_client):
        session = TerminalSession(
            user_id=2, device_id=1, port_id=2,
            status='active',
        )
        admin_app.db_session.add(session)
        admin_app.db_session.commit()

        resp = admin_client.post(f'/api/sessions/{session.id}/disconnect')
        assert resp.status_code == 200
        import json
        data = json.loads(resp.data)
        assert data['success'] is True

        admin_app.db_session.refresh(session)
        assert session.status == 'disconnected'
        assert session.disconnect_reason == 'admin_force'

    def test_disconnect_nonexistent_session(self, admin_client):
        resp = admin_client.post('/api/sessions/9999/disconnect')
        assert resp.status_code == 404

    def test_non_admin_cannot_disconnect_session(self, regular_client):
        resp = regular_client.post('/api/sessions/1/disconnect')
        assert resp.status_code == 403


class TestAdminSettings:
    """SDD 10.3: Admin settings management."""

    def test_admin_can_view_settings(self, admin_client):
        resp = admin_client.get('/admin/settings')
        assert resp.status_code == 200

    def test_admin_can_save_settings(self, admin_app, admin_client):
        # Seed a setting first, then update it
        setting = AdminSetting(key='MAX_UPLOAD_SIZE_BYTES', value='8388608',
                               description='Max upload size')
        admin_app.db_session.add(setting)
        admin_app.db_session.commit()

        resp = admin_client.post('/admin/settings', data={
            'MAX_UPLOAD_SIZE_BYTES': '16777216',
            'DEFAULT_MAX_QUEUED_JOBS': '10',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Settings saved' in resp.data

        s = admin_app.db_session.get(AdminSetting, 'MAX_UPLOAD_SIZE_BYTES')
        assert s is not None
        assert s.value == '16777216'

    def test_non_admin_cannot_access_settings(self, regular_client):
        resp = regular_client.get('/admin/settings')
        assert resp.status_code == 403


class TestAdminDashboard:
    """E2E admin dashboard with system stats."""

    def test_admin_dashboard_shows_stats(self, admin_app, admin_client):
        job = Job(user_id=1, device_id=1, original_filename='stats.bin',
                  status='running')
        session = TerminalSession(user_id=2, device_id=1, port_id=2,
                                  status='active')
        admin_app.db_session.add_all([job, session])
        admin_app.db_session.commit()

        resp = admin_client.get('/admin/')
        assert resp.status_code == 200

    def test_non_admin_cannot_access_dashboard(self, regular_client):
        resp = regular_client.get('/admin/')
        assert resp.status_code == 403
