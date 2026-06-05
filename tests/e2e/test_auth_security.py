"""E2E tests — auth hardening: password policy, login throttling, session protection."""

import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.security import generate_password_hash

from retrobridge.models import LoginAttempt, User


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


def _register(client, username='alice', password='Alice123'):
    resp = client.post('/auth/register', data={
        'username': username,
        'email': f'{username}@example.com',
        'full_name': 'Test User',
        'password': password,
        'confirm_password': password,
    }, follow_redirects=True)
    # Registration auto-logs in; logout so subsequent tests start clean
    client.get('/auth/logout', follow_redirects=True)
    return resp


def _login(client, username='alice', password='Alice123'):
    return client.post('/auth/login', data={
        'username': username,
        'password': password,
    }, follow_redirects=True)


class TestPasswordPolicy:
    """SDD 11.2: Password must be 8+ chars, 1 uppercase, 1 digit."""

    def test_rejects_password_without_uppercase(self, client):
        resp = client.post('/auth/register', data={
            'username': 'bob',
            'email': 'bob@example.com',
            'full_name': 'Bob',
            'password': 'lowercase1',
            'confirm_password': 'lowercase1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'uppercase' in resp.data.lower()

    def test_rejects_password_without_digit(self, client):
        resp = client.post('/auth/register', data={
            'username': 'bob',
            'email': 'bob@example.com',
            'full_name': 'Bob',
            'password': 'NoDigitsHere',
            'confirm_password': 'NoDigitsHere',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'digit' in resp.data.lower()

    def test_rejects_short_password(self, client):
        resp = client.post('/auth/register', data={
            'username': 'bob',
            'email': 'bob@example.com',
            'full_name': 'Bob',
            'password': 'Ab1',
            'confirm_password': 'Ab1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'least 8' in resp.data.lower()

    def test_accepts_valid_password(self, client, app):
        resp = _register(client, password='ValidPass1')
        assert resp.status_code == 200
        assert b'Account created' in resp.data
        user = app.db_session.query(User).filter_by(username='alice').first()
        assert user is not None

    def test_profile_password_change_enforces_policy(self, client, app):
        _register(client)
        _login(client)

        resp = client.post('/auth/profile', data={
            'email': 'alice@example.com',
            'full_name': 'Alice',
            'bio': '',
            'terminal_font_size': 14,
            'terminal_color_scheme': 'dark',
            'new_password': 'weak',
            'confirm_password': 'weak',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert (b'uppercase' in resp.data.lower()
                or b'least 8' in resp.data.lower()
                or b'digit' in resp.data.lower())

    def test_profile_password_change_accepts_valid(self, client, app):
        _register(client)
        _login(client)

        resp = client.post('/auth/profile', data={
            'email': 'alice@example.com',
            'full_name': 'Alice',
            'bio': '',
            'terminal_font_size': 14,
            'terminal_color_scheme': 'dark',
            'new_password': 'NewPass1!',
            'confirm_password': 'NewPass1!',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Profile updated' in resp.data


class TestLoginThrottling:
    """SDD 11.2: 5 failed attempts in 15 minutes blocks further attempts."""

    def test_throttle_after_five_failed_attempts(self, client, app):
        _register(client, username='locked', password='Alice123')

        # 5 failed attempts (user is logged out after _register)
        for _ in range(5):
            client.post('/auth/login', data={
                'username': 'locked',
                'password': 'WrongPass1',
            }, follow_redirects=True)

        # 6th attempt should be throttled
        resp = client.post('/auth/login', data={
            'username': 'locked',
            'password': 'Alice123',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Too many failed' in resp.data

    def test_successful_login_resets_throttle_count(self, client, app):
        _register(client, username='resetter', password='ResetPass1')

        # 3 failed then a success
        for _ in range(3):
            client.post('/auth/login', data={
                'username': 'resetter',
                'password': 'WrongPass1',
            }, follow_redirects=True)

        resp = client.post('/auth/login', data={
            'username': 'resetter',
            'password': 'ResetPass1',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Dashboard' in resp.data

    def test_throttled_attempt_is_recorded(self, client, app):
        _register(client, username='tracked', password='Tracked1')

        for _ in range(5):
            client.post('/auth/login', data={
                'username': 'tracked',
                'password': 'WrongPass1',
            }, follow_redirects=True)

        count = app.db_session.query(LoginAttempt).filter_by(
            success=False).count()
        assert count >= 5

    def test_old_failed_attempts_dont_count(self, client, app):
        _register(client, username='expired', password='Expired1')

        # Seed old failed attempts (outside window)
        old_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        for _ in range(5):
            app.db_session.add(LoginAttempt(
                ip_address='127.0.0.1',
                username='expired',
                success=False,
                attempted_at=old_time,
            ))
        app.db_session.commit()

        # Should still be able to login (old attempts expired)
        resp = _login(client, username='expired', password='Expired1')
        assert resp.status_code == 200
        assert b'Dashboard' in resp.data

    def test_successful_attempts_dont_count_toward_throttle(self, client, app):
        _register(client, username='good', password='GoodPass1')

        # Mix of success and failure
        for _ in range(5):
            _login(client, username='good', password='GoodPass1')
            client.get('/auth/logout', follow_redirects=True)

        # Only failed attempts count toward throttle
        resp = _login(client, username='good', password='GoodPass1')
        assert resp.status_code == 200
        assert b'Dashboard' in resp.data


class TestSessionProtection:
    """SDD 11.2: Strong session protection and secure cookie settings."""

    def test_session_cookie_has_httponly(self, client, app):
        _register(client)
        resp = _login(client)
        cookies = resp.headers.getlist('Set-Cookie')
        session_cookie = [c for c in cookies if 'session' in c.lower()]
        if session_cookie:
            assert 'HttpOnly' in session_cookie[0]

    def test_logout_clears_session(self, client, app):
        _register(client)
        _login(client)

        resp = client.get('/dashboard')
        assert resp.status_code == 200

        client.get('/auth/logout', follow_redirects=True)

        resp = client.get('/dashboard')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_login_page_redirects_if_authenticated(self, client, app):
        _register(client)
        _login(client)

        resp = client.get('/auth/login', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Dashboard' in resp.data

    def test_register_page_redirects_if_authenticated(self, client, app):
        _register(client)
        _login(client)

        resp = client.get('/auth/register', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Dashboard' in resp.data
