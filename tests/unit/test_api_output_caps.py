"""Tests for API output caps and SSE lifetime defaults (review #14)."""
import inspect
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from retrobridge.models import Device, Job, User


@pytest.fixture
def output_app(app, tmp_path):
    app.config['OUTPUT_DIR'] = str(tmp_path)
    user = User(username='outuser', email='o@example.com',
                password_hash=generate_password_hash('pw'))
    device = Device(name='centurion')
    app.db_session.add_all([user, device])
    app.db_session.commit()
    return app


def _login(client):
    client.post('/auth/login', data={'username': 'outuser', 'password': 'pw'},
                follow_redirects=True)


def _make_job_with_output(output_app, n_lines):
    job = Job(user_id=1, device_id=1, original_filename='x.bin',
              status='completed')
    output_app.db_session.add(job)
    output_app.db_session.flush()
    out = Path(output_app.config['OUTPUT_DIR']) / f'job-{job.id}.log'
    out.write_text(''.join(f'line{i}\n' for i in range(n_lines)))
    job.output_path = str(out)
    output_app.db_session.commit()
    return job


def _get_output(output_app, job_id, query=''):
    client = output_app.test_client()
    _login(client)
    resp = client.get(f'/api/jobs/{job_id}/output{query}')
    assert resp.status_code == 200
    return resp.get_json()['lines']


def test_output_endpoint_caps_unbounded_request(output_app):
    job = _make_job_with_output(output_app, 12_000)
    lines = _get_output(output_app, job.id)
    assert len(lines) == 10_000
    assert lines[-1] == 'line11999'


def test_output_endpoint_respects_small_tail(output_app):
    job = _make_job_with_output(output_app, 100)
    lines = _get_output(output_app, job.id, query='?tail=3')
    assert lines == ['line97', 'line98', 'line99']


def test_output_endpoint_caps_requested_tail(output_app):
    job = _make_job_with_output(output_app, 12_000)
    lines = _get_output(output_app, job.id, query='?tail=15000')
    assert len(lines) == 10_000


def test_output_endpoint_clamps_negative_tail(output_app):
    job = _make_job_with_output(output_app, 12_000)
    lines = _get_output(output_app, job.id, query='?tail=-1')
    assert len(lines) == 10_000


def test_job_events_max_lifetime_has_nonzero_default():
    from config import BaseConfig
    # A queued job must not pin an SSE stream (and its thread) forever.
    assert BaseConfig.JOB_EVENTS_MAX_LIFETIME and \
        BaseConfig.JOB_EVENTS_MAX_LIFETIME > 0


def test_api_routes_no_longer_reference_eventlet():
    from retrobridge.api import routes
    src = inspect.getsource(routes)
    assert 'eventlet' not in src
