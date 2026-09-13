"""Tests for login-redirect safety (review #17) and the public
username-availability endpoint (review #15)."""
from retrobridge.auth.routes import _is_safe_redirect_url


def _ctx(app):
    return app.test_request_context('/auth/login')


def test_relative_path_is_safe(app):
    with _ctx(app):
        assert _is_safe_redirect_url('/dashboard') is True


def test_empty_target_is_not_safe(app):
    with _ctx(app):
        assert _is_safe_redirect_url('') is False
        assert _is_safe_redirect_url(None) is False


def test_protocol_relative_target_is_not_safe(app):
    with _ctx(app):
        assert _is_safe_redirect_url('//evil.com') is False


def test_external_url_is_not_safe(app):
    with _ctx(app):
        assert _is_safe_redirect_url('https://evil.com/x') is False


def test_backslash_variants_are_not_safe(app):
    # Browsers normalize a leading backslash in Location to '//' — an
    # attacker can smuggle an external redirect past a naive check.
    with _ctx(app):
        assert _is_safe_redirect_url('\\evil.com') is False
        assert _is_safe_redirect_url('\\\\evil.com') is False


def test_check_username_available_when_registration_open(app, client):
    from retrobridge.models import AdminSetting
    app.db_session.add(AdminSetting(key='REGISTRATION_OPEN', value='1',
                                    description='test'))
    app.db_session.commit()

    resp = client.get('/api/check-username?username=freshuser')
    assert resp.status_code == 200
    assert resp.get_json()['available'] is True


def test_check_username_unavailable_when_registration_closed(app, client):
    from retrobridge.models import AdminSetting
    app.db_session.add(AdminSetting(key='REGISTRATION_OPEN', value='0',
                                    description='test'))
    app.db_session.commit()

    resp = client.get('/api/check-username?username=freshuser')
    assert resp.status_code == 200
    assert resp.get_json()['available'] is False


def test_check_username_short_username(app, client):
    resp = client.get('/api/check-username?username=x')
    assert resp.get_json()['available'] is False
