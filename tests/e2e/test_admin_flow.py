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
            'username': 'reguser',
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

    def test_admin_can_create_user(self, admin_app, admin_client):
        resp = admin_client.post('/admin/users/create', data={
            'username': 'newbie',
            'email': 'newbie@ex.com',
            'full_name': 'New User',
            'password': 'NewUser1!',
            'is_admin': False,
            'max_queued_jobs': 5,
            'max_terminal_sessions': 2,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'User created' in resp.data

        user = admin_app.db_session.query(User).filter_by(
            username='newbie').first()
        assert user is not None
        assert user.email == 'newbie@ex.com'
        assert user.max_queued_jobs == 5

    def test_admin_create_user_rejects_duplicate(self, admin_app,
                                                   admin_client):
        resp = admin_client.post('/admin/users/create', data={
            'username': 'reguser',
            'email': 'dup@ex.com',
            'password': 'DupUser1!',
            'full_name': '',
            'is_admin': False,
            'max_queued_jobs': 3,
            'max_terminal_sessions': 1,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Username already taken' in resp.data

    def test_admin_can_search_users(self, admin_app, admin_client):
        resp = admin_client.get('/admin/users?search=reg')
        assert resp.status_code == 200
        assert b'reguser' in resp.data
        # 'admin' may appear in navbar, so check the table body only
        tbody_start = resp.data.find(b'<tbody>')
        tbody_end = resp.data.find(b'</tbody>')
        tbody = resp.data[tbody_start:tbody_end] if tbody_start >= 0 else b''
        assert b'reguser' in tbody
        # admin user should be filtered out of results
        assert b'<strong>admin</strong>' not in tbody

    def test_user_list_shows_stats(self, admin_app, admin_client):
        job = Job(user_id=2, device_id=1, original_filename='a.bin',
                  status='completed')
        admin_app.db_session.add(job)
        admin_app.db_session.commit()

        resp = admin_client.get('/admin/users')
        assert resp.status_code == 200
        assert b'done' in resp.data

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
            'username': 'x',
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
            'transfer_protocol': 'xmodem',
            'max_concurrent_jobs': 1,
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

    def test_admin_can_toggle_device(self, admin_app, admin_client):
        device = admin_app.db_session.query(Device).first()
        initial = device.is_enabled

        resp = admin_client.post(
            f'/admin/devices/{device.id}/toggle',
            follow_redirects=True)
        assert resp.status_code == 200

        admin_app.db_session.refresh(device)
        assert device.is_enabled is not initial

    def test_admin_can_edit_device(self, admin_app, admin_client):
        device = admin_app.db_session.query(Device).first()

        resp = admin_client.post(f'/admin/devices/{device.id}/edit', data={
            'name': 'centurion_v2',
            'display_name': 'Centurion Mk II',
            'is_enabled': True,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Device updated' in resp.data

        admin_app.db_session.refresh(device)
        assert device.name == 'centurion_v2'
        assert device.display_name == 'Centurion Mk II'

    def test_admin_can_delete_device(self, admin_app, admin_client):
        new_dev = Device(name='tempdev', display_name='Temp')
        admin_app.db_session.add(new_dev)
        admin_app.db_session.commit()

        resp = admin_client.post(f'/admin/devices/{new_dev.id}/delete',
                                 follow_redirects=True)
        assert resp.status_code == 200
        assert b'Device deleted' in resp.data

        assert admin_app.db_session.get(Device, new_dev.id) is None

    def test_admin_can_edit_port(self, admin_app, admin_client):
        port = admin_app.db_session.query(DevicePort).first()

        resp = admin_client.post(
            f'/admin/devices/{port.device_id}/ports/{port.id}/edit',
            data={
                'port_label': 'TTY0_renamed',
                'dev_path': port.dev_path,
                'purpose': port.purpose,
                'baud': 38400,
                'data_bits': 8,
                'parity': 'E',
                'stop_bits': 2,
                'flow_control': 'rtscts',
                'newline_mode': 'cr',
                'transfer_protocol': 'xmodem1k',
                'max_concurrent_jobs': 2,
                'max_runtime_seconds': 900,
                'idle_timeout_seconds': 120,
            }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Port updated' in resp.data

        admin_app.db_session.refresh(port)
        assert port.port_label == 'TTY0_renamed'
        assert port.baud == 38400
        assert port.parity == 'E'
        assert port.stop_bits == 2
        assert port.flow_control == 'rtscts'

    def test_admin_can_toggle_port(self, admin_app, admin_client):
        port = admin_app.db_session.query(DevicePort).first()
        initial = port.is_enabled

        resp = admin_client.post(
            f'/admin/devices/{port.device_id}/ports/{port.id}/toggle',
            follow_redirects=True)
        assert resp.status_code == 200

        admin_app.db_session.refresh(port)
        assert port.is_enabled is not initial

    def test_admin_can_delete_port(self, admin_app, admin_client):
        port = admin_app.db_session.query(DevicePort)\
            .filter_by(port_label='TTY1').first()

        resp = admin_client.post(
            f'/admin/devices/{port.device_id}/ports/{port.id}/delete',
            follow_redirects=True)
        assert resp.status_code == 200
        assert b'Port deleted' in resp.data

        assert admin_app.db_session.get(DevicePort, port.id) is None

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
            'transfer_protocol': 'xmodem',
            'max_concurrent_jobs': 1,
            'max_runtime_seconds': 300,
            'idle_timeout_seconds': 5,
        })
        assert resp.status_code == 403

    def test_non_admin_cannot_toggle_device(self, regular_client):
        resp = regular_client.post('/admin/devices/1/toggle')
        assert resp.status_code == 403

    def test_non_admin_cannot_edit_device(self, regular_client):
        resp = regular_client.post('/admin/devices/1/edit', data={
            'name': 'hacked', 'display_name': '', 'is_enabled': True,
        })
        assert resp.status_code == 403

    def test_non_admin_cannot_delete_device(self, regular_client):
        resp = regular_client.post('/admin/devices/1/delete')
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

    def test_admin_can_search_jobs(self, admin_app, admin_client):
        admin_app.db_session.add_all([
            Job(user_id=1, device_id=1, original_filename='findme.bin',
                status='queued'),
            Job(user_id=2, device_id=1, original_filename='other.bin',
                status='queued'),
        ])
        admin_app.db_session.commit()

        resp = admin_client.get('/admin/jobs?search=find')
        assert resp.status_code == 200
        assert b'findme.bin' in resp.data
        assert b'other.bin' not in resp.data

    def test_admin_can_filter_by_device(self, admin_app, admin_client):
        dev2 = Device(name='pdp11', display_name='PDP-11')
        admin_app.db_session.add(dev2)
        admin_app.db_session.flush()
        admin_app.db_session.add_all([
            Job(user_id=1, device_id=1, original_filename='cent.bin',
                status='queued'),
            Job(user_id=1, device_id=dev2.id, original_filename='pdp.bin',
                status='queued'),
        ])
        admin_app.db_session.commit()

        resp = admin_client.get(f'/admin/jobs?device_id={dev2.id}')
        assert resp.status_code == 200
        assert b'pdp.bin' in resp.data
        assert b'cent.bin' not in resp.data

    def test_admin_can_bulk_cancel_jobs(self, admin_app, admin_client):
        j1 = Job(user_id=1, device_id=1, original_filename='bulk1.bin',
                 status='queued')
        j2 = Job(user_id=1, device_id=1, original_filename='bulk2.bin',
                 status='queued')
        admin_app.db_session.add_all([j1, j2])
        admin_app.db_session.commit()

        resp = admin_client.post('/admin/jobs/bulk-cancel', data={
            'job_ids': [str(j1.id), str(j2.id)],
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'2 job(s) canceled' in resp.data

        admin_app.db_session.refresh(j1)
        admin_app.db_session.refresh(j2)
        assert j1.status == 'canceled'
        assert j2.status == 'canceled'

    def test_jobs_page_shows_status_counts(self, admin_app, admin_client):
        for _ in range(3):
            admin_app.db_session.add(Job(
                user_id=1, device_id=1, original_filename='q.bin',
                status='queued'))
        admin_app.db_session.commit()

        resp = admin_client.get('/admin/jobs')
        assert resp.status_code == 200
        assert b'Queued' in resp.data

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
        assert b'Uploads' in resp.data
        assert b'Terminal' in resp.data

    def test_admin_can_save_settings(self, admin_app, admin_client):
        resp = admin_client.post('/admin/settings', data={
            'max_upload_size_mb': 32,
            'default_max_queued_jobs': 10,
            'default_max_terminal_sessions': 5,
            'max_jobs_per_hour': 50,
            'max_terminal_session_minutes': 120,
            'terminal_idle_timeout_minutes': 10,
            'worker_poll_seconds': 10,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Settings saved' in resp.data

        s = admin_app.db_session.get(AdminSetting, 'MAX_UPLOAD_SIZE_BYTES')
        assert s is not None
        assert s.value == '33554432'  # 32 MB in bytes

    def test_settings_persist_across_requests(self, admin_app, admin_client):
        # Save
        admin_client.post('/admin/settings', data={
            'max_upload_size_mb': 8,
            'default_max_queued_jobs': 3,
            'default_max_terminal_sessions': 1,
            'max_jobs_per_hour': 10,
            'max_terminal_session_minutes': 60,
            'terminal_idle_timeout_minutes': 5,
            'worker_poll_seconds': 5,
        })
        # Re-load and verify
        resp = admin_client.get('/admin/settings')
        assert b'value="8"' in resp.data

    def test_admin_can_toggle_registration(self, admin_app, admin_client):
        resp = admin_client.post('/admin/settings', data={
            'max_upload_size_mb': 16,
            'default_max_queued_jobs': 3,
            'default_max_terminal_sessions': 1,
            'max_jobs_per_hour': 10,
            'max_terminal_session_minutes': 60,
            'terminal_idle_timeout_minutes': 5,
            'worker_poll_seconds': 5,
            'registration_open': 'y',
        }, follow_redirects=True)
        assert resp.status_code == 200

        s = admin_app.db_session.get(AdminSetting, 'REGISTRATION_OPEN')
        assert s is not None
        assert s.value == '1'

    def test_admin_can_toggle_maintenance(self, admin_app, admin_client):
        resp = admin_client.post('/admin/settings', data={
            'max_upload_size_mb': 16,
            'default_max_queued_jobs': 3,
            'default_max_terminal_sessions': 1,
            'max_jobs_per_hour': 10,
            'max_terminal_session_minutes': 60,
            'terminal_idle_timeout_minutes': 5,
            'worker_poll_seconds': 5,
            'maintenance_mode': 'y',
        }, follow_redirects=True)
        assert resp.status_code == 200

        s = admin_app.db_session.get(AdminSetting, 'MAINTENANCE_MODE')
        assert s is not None
        assert s.value == '1'

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
