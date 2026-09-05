"""Smoke tests verifying CSP-compliant templates render without inline JS."""
import pytest
from werkzeug.security import generate_password_hash

from retrobridge.models import Device, DevicePort, User


@pytest.fixture
def logged_in_client(client, db_session):
    user = User(
        username='cspuser',
        email='csp@example.com',
        password_hash=generate_password_hash('Password123'),
        is_admin=True,
    )
    db_session.add(user)
    db_session.flush()

    device = Device(name='centurion', display_name='Centurion CPU-6')
    db_session.add(device)
    db_session.flush()

    port = DevicePort(
        device_id=device.id,
        port_label='TTY0',
        purpose='job_queue',
        dev_path='/tmp/tty0',
    )
    db_session.add(port)
    db_session.commit()

    resp = client.post('/auth/login', data={
        'username': 'cspuser',
        'password': 'Password123',
        'remember': False,
    }, follow_redirects=True)
    assert resp.status_code == 200
    return client


def _no_inline_js(html):
    # Allow <script src="..."> but not bare <script> blocks.
    assert '<script>' not in html, 'Bare inline <script> block found'
    assert 'onclick=' not in html, 'Inline onclick handler found'
    assert 'onchange=' not in html, 'Inline onchange handler found'
    assert 'oninput=' not in html, 'Inline oninput handler found'
    assert 'onsubmit=' not in html, 'Inline onsubmit handler found'


def test_new_job_page_uses_external_js(logged_in_client):
    resp = logged_in_client.get('/new')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<script src="/static/js/new-job.js"></script>' in html
    _no_inline_js(html)


def test_dashboard_page_uses_external_js(logged_in_client):
    resp = logged_in_client.get('/dashboard')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<script src="/static/js/dashboard.js"></script>' in html
    _no_inline_js(html)


def test_admin_jobs_page_uses_external_js(logged_in_client):
    resp = logged_in_client.get('/admin/jobs')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<script src="/static/js/admin-jobs.js"></script>' in html
    _no_inline_js(html)


def test_admin_sessions_page_uses_external_js(logged_in_client):
    resp = logged_in_client.get('/admin/sessions')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<script src="/static/js/admin-sessions.js"></script>' in html
    _no_inline_js(html)


def test_register_page_uses_external_js(client):
    resp = client.get('/auth/register')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<script src="/static/js/register.js"></script>' in html
    _no_inline_js(html)
