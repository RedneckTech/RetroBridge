"""Tests for the job events SSE endpoint."""
import json
import time
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from retrobridge.models import Device, DevicePort, Job, User


def _setup_job(db_session):
    user = User(username='sseuser', email='sse@example.com',
                password_hash=generate_password_hash('Password123'))
    device = Device(name='ssedev')
    db_session.add_all([user, device])
    db_session.flush()
    port = DevicePort(device_id=device.id, port_label='T0', dev_path='/dev/tty0',
                      purpose='job_queue')
    db_session.add(port)
    db_session.flush()
    job = Job(user_id=user.id, device_id=device.id, port_id=port.id,
              original_filename='x.mod', status='queued')
    db_session.add(job)
    db_session.commit()
    return user, job


def _login(client, username, password):
    resp = client.post('/auth/login', data={'username': username, 'password': password},
                       follow_redirects=True)
    assert resp.status_code == 200


def test_sse_stream_returns_initial_heartbeat(client, db_session):
    user, job = _setup_job(db_session)
    _login(client, user.username, 'Password123')

    # Patch sleep so the generator yields quickly without blocking.
    with patch('retrobridge.api.routes.time.sleep'):
        resp = client.get(f'/api/jobs/{job.id}/events')

    assert resp.status_code == 200
    assert resp.mimetype == 'text/event-stream'
    assert resp.headers.get('X-Accel-Buffering') == 'no'


def test_sse_uses_configurable_poll_interval(app, client, db_session):
    user, job = _setup_job(db_session)
    app.config['JOB_EVENTS_POLL_INTERVAL'] = 0.05
    _login(client, user.username, 'Password123')

    # End the job immediately so the stream terminates.
    job.status = 'completed'
    db_session.commit()

    resp = client.get(f'/api/jobs/{job.id}/events')
    data = resp.get_data(as_text=True)
    assert 'event: done' in data
    assert json.loads(data.split('data: ')[1])['status'] == 'completed'


def test_sse_respects_max_lifetime(app, client, db_session):
    user, job = _setup_job(db_session)
    app.config['JOB_EVENTS_POLL_INTERVAL'] = 0.01
    app.config['JOB_EVENTS_MAX_LIFETIME'] = 0.02
    _login(client, user.username, 'Password123')

    start = time.time()
    resp = client.get(f'/api/jobs/{job.id}/events')
    elapsed = time.time() - start
    data = resp.get_data(as_text=True)

    assert elapsed < 1.0
    assert 'event: done' in data
    assert 'timeout' in data


def test_sse_forbids_other_users_job(client, db_session):
    user, job = _setup_job(db_session)
    other = User(username='other', email='o@example.com',
                 password_hash=generate_password_hash('Password123'))
    db_session.add(other)
    db_session.commit()

    _login(client, 'other', 'Password123')
    resp = client.get(f'/api/jobs/{job.id}/events')
    assert resp.status_code == 403
