"""Tests for the `flask seed` command's admin-credential safety."""
from werkzeug.security import check_password_hash

from retrobridge.models import User


def _invoke_seed(runner, *args):
    return runner.invoke(args=['seed', *args])


def test_seed_creates_default_admin_in_dev(app, runner):
    result = _invoke_seed(runner)
    assert result.exit_code == 0, result.output

    admin = app.db_session.query(User).filter_by(username='admin').first()
    assert admin is not None
    assert admin.is_admin is True
    assert check_password_hash(admin.password_hash, 'admin')


def test_seed_refuses_default_admin_in_production(app, runner, monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')
    result = _invoke_seed(runner)
    assert result.exit_code != 0
    assert 'admin/admin' in result.output

    assert app.db_session.query(User).filter_by(username='admin').first() is None


def test_seed_accepts_admin_password_in_production(app, runner, monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')
    result = _invoke_seed(runner, '--admin-password', 'S3cret-Pass!')
    assert result.exit_code == 0, result.output

    admin = app.db_session.query(User).filter_by(username='admin').first()
    assert admin is not None
    assert check_password_hash(admin.password_hash, 'S3cret-Pass!')
