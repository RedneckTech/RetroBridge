"""Tests for safe integer handling in admin routes."""
from werkzeug.security import generate_password_hash

from retrobridge.models import User


def _login_admin(client, db_session):
    user = User(username='admin', email='a@example.com',
                password_hash=generate_password_hash('Admin123'), is_admin=True)
    db_session.add(user)
    db_session.commit()
    client.post('/auth/login', data={'username': 'admin', 'password': 'Admin123'},
                follow_redirects=True)


def test_jobs_filter_ignores_invalid_device_id(client, db_session):
    _login_admin(client, db_session)
    resp = client.get('/admin/jobs?device_id=not-a-number')
    assert resp.status_code == 200


def test_bulk_cancel_skips_invalid_job_ids(client, db_session):
    _login_admin(client, db_session)
    resp = client.post('/admin/jobs/bulk-cancel', data={
        'job_ids': ['1', 'not-a-number', '2'],
    }, follow_redirects=True)
    assert resp.status_code == 200


def test_bulk_disconnect_skips_invalid_session_ids(client, db_session):
    _login_admin(client, db_session)
    resp = client.post('/admin/sessions/bulk-disconnect', data={
        'session_ids': ['1', 'bad', '3'],
    }, follow_redirects=True)
    assert resp.status_code == 200
