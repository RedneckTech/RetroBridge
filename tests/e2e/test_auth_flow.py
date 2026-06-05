"""E2E tests — authentication flow: register, login, profile, logout."""

import tempfile

import pytest

from retrobridge.models import User


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


def _register(client, username='newuser', email='newuser@example.com',
              full_name='New User', password='SecurePass1'):
    return client.post('/auth/register', data={
        'username': username,
        'email': email,
        'full_name': full_name,
        'password': password,
        'confirm_password': password,
    }, follow_redirects=True)


def _login(client, username='newuser', password='SecurePass1'):
    return client.post('/auth/login', data={
        'username': username,
        'password': password,
    }, follow_redirects=True)


class TestRegistrationLoginLogout:
    """SDD 10.3: Full auth cycle — register, login, profile, logout."""

    def test_register_new_user(self, client, app):
        resp = _register(client)
        assert resp.status_code == 200
        assert b'Account created' in resp.data

        user = app.db_session.query(User).filter_by(username='newuser').first()
        assert user is not None
        assert user.email == 'newuser@example.com'
        assert user.full_name == 'New User'

    def test_register_rejects_duplicate_username(self, client, app):
        _register(client)
        client.get('/auth/logout', follow_redirects=True)

        resp = client.post('/auth/register', data={
            'username': 'newuser',
            'email': 'different@ex.com',
            'full_name': 'Dupe',
            'password': 'Pass1234',
            'confirm_password': 'Pass1234',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'already taken' in resp.data.lower()

    def test_register_rejects_duplicate_email(self, client, app):
        _register(client)
        client.get('/auth/logout', follow_redirects=True)

        resp = client.post('/auth/register', data={
            'username': 'different',
            'email': 'newuser@example.com',
            'full_name': 'Dupe',
            'password': 'Pass1234',
            'confirm_password': 'Pass1234',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'already registered' in resp.data.lower()

    def test_register_shows_password_hints(self, client):
        resp = client.get('/auth/register')
        assert b'uppercase' in resp.data.lower()
        assert b'digit' in resp.data.lower()

    def test_login_after_registration(self, client, app):
        _register(client)
        resp = _login(client)
        assert resp.status_code == 200
        assert b'Dashboard' in resp.data
        assert b'newuser' in resp.data

    def test_update_profile(self, client, app):
        _register(client)
        _login(client)

        resp = client.post('/auth/profile', data={
            'email': 'updated@example.com',
            'full_name': 'Updated Name',
            'bio': 'My new bio',
            'terminal_font_size': 16,
            'terminal_color_scheme': 'amber',
            'new_password': '',
            'confirm_password': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Profile updated' in resp.data

        user = app.db_session.query(User).filter_by(username='newuser').first()
        assert user.email == 'updated@example.com'
        assert user.bio == 'My new bio'

    def test_logout_and_relogin(self, client, app):
        _register(client)
        _login(client)

        resp = client.get('/auth/logout', follow_redirects=True)
        assert resp.status_code == 200
        assert b'logged out' in resp.data.lower()

        resp = client.get('/dashboard')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

        resp = _login(client)
        assert resp.status_code == 200
        assert b'Logged in successfully' in resp.data

    def test_unauthorized_access_redirects_to_login_then_back(self, client,
                                                               app):
        """SDD 10.3: Anonymous user attempts /new, redirects to login, then
        back."""
        _register(client)
        client.get('/auth/logout', follow_redirects=True)

        resp = client.get('/new')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']
        assert 'next=%2Fnew' in resp.headers['Location']

        _login(client)
        resp = client.get('/new')
        assert resp.status_code == 200

    def test_profile_page_shows_current_data(self, client, app):
        _register(client)
        _login(client)

        resp = client.get('/auth/profile')
        assert resp.status_code == 200
        assert b'newuser@example.com' in resp.data

    def test_profile_shows_quota_usage(self, client, app):
        _register(client)
        _login(client)

        resp = client.get('/auth/profile')
        assert resp.status_code == 200
        assert b'Job Queue' in resp.data
        assert b'Terminal Sessions' in resp.data

    def test_profile_shows_stats(self, client, app):
        _register(client)
        _login(client)

        from retrobridge.models import Device, DevicePort, Job, TerminalSession
        uid = app.db_session.query(User).filter_by(username='newuser').first().id
        d = Device(name='testdev')
        app.db_session.add(d)
        app.db_session.flush()
        p = DevicePort(device_id=d.id, port_label='TTY0',
                       dev_path='/dev/null', purpose='job_queue')
        app.db_session.add(p)
        app.db_session.flush()
        app.db_session.add_all([
            Job(user_id=uid, device_id=d.id, original_filename='a.bin',
                status='completed'),
            TerminalSession(user_id=uid, device_id=d.id, port_id=p.id,
                            status='disconnected', duration_seconds=30),
        ])
        app.db_session.commit()

        resp = client.get('/auth/profile')
        assert b'Done' in resp.data
        assert b'Sessions' in resp.data


class TestAccountDeletion:
    """Tests for self-service account deletion."""

    @pytest.fixture
    def app_with_seed(self, app):
        from retrobridge.models import Device, DevicePort
        from werkzeug.security import generate_password_hash
        user = User(username='deleteuser', email='del@ex.com',
                    password_hash=generate_password_hash('Password1'))
        device = Device(name='centurion')
        app.db_session.add_all([user, device])
        app.db_session.commit()
        return app

    def test_user_can_delete_own_account(self, app_with_seed):
        c = app_with_seed.test_client()
        c.post('/auth/login', data={
            'username': 'deleteuser', 'password': 'Password1',
        }, follow_redirects=True)

        resp = c.post('/auth/delete-account', follow_redirects=True)
        assert resp.status_code == 200
        assert b'account has been deleted' in resp.data.lower()

        user = app_with_seed.db_session.query(User).filter_by(
            username='deleteuser').first()
        assert user is None

    def test_delete_account_requires_login(self, client):
        resp = client.post('/auth/delete-account')
        assert resp.status_code == 302


class TestUnauthorizedAccess:
    """SDD 10.3: Unauthorized access scenarios."""

    def test_anonymous_cannot_access_dashboard(self, client):
        resp = client.get('/dashboard')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_anonymous_cannot_access_terminal(self, client):
        resp = client.get('/terminal/')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_anonymous_cannot_access_admin(self, client):
        resp = client.get('/admin/')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_non_admin_cannot_access_admin_dashboard(self, client, app):
        _register(client)
        _login(client)

        resp = client.get('/admin/')
        assert resp.status_code == 403

    def test_anonymous_cannot_call_api(self, client):
        resp = client.get('/api/jobs')
        assert resp.status_code == 302

        resp = client.get('/api/devices')
        assert resp.status_code == 302


class TestRegistrationToggle:
    """Tests for REGISTRATION_OPEN setting."""

    @pytest.fixture
    def seeded_app(self, app):
        from retrobridge.models import AdminSetting
        app.db_session.add(AdminSetting(
            key='REGISTRATION_OPEN', value='0',
            description='Registration toggle',
        ))
        app.db_session.commit()
        return app

    def test_registration_blocked_when_closed(self, seeded_app):
        c = seeded_app.test_client()
        resp = c.post('/auth/register', data={
            'username': 'blocked',
            'email': 'blocked@ex.com',
            'full_name': 'Blocked',
            'password': 'Blocked1!',
            'confirm_password': 'Blocked1!',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Registration is currently closed' in resp.data


class TestMaintenanceMode:
    """Tests for MAINTENANCE_MODE setting."""

    @pytest.fixture
    def maint_app(self, app):
        from retrobridge.models import AdminSetting, User
        from werkzeug.security import generate_password_hash
        app.db_session.add(AdminSetting(
            key='MAINTENANCE_MODE', value='1',
            description='Maintenance mode',
        ))
        app.db_session.add(User(
            username='admin', email='a@ex.com',
            password_hash=generate_password_hash('admin'),
            is_admin=True,
        ))
        app.db_session.commit()
        return app

    def test_maintenance_shows_503_for_anonymous(self, maint_app):
        c = maint_app.test_client()
        resp = c.get('/')
        assert resp.status_code == 503
        assert b'Maintenance' in resp.data

    def test_maintenance_allows_admin_access(self, maint_app):
        c = maint_app.test_client()
        c.post('/auth/login', data={
            'username': 'admin', 'password': 'admin',
        }, follow_redirects=True)
        resp = c.get('/admin/')
        assert resp.status_code == 200
