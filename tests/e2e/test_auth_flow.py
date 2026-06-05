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
              full_name='New User', password='securepass123'):
    return client.post('/auth/register', data={
        'username': username,
        'email': email,
        'full_name': full_name,
        'password': password,
        'confirm_password': password,
    }, follow_redirects=True)


def _login(client, username='newuser', password='securepass123'):
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
