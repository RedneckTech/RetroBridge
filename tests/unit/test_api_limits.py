"""Unit tests for API pagination and output limits."""
from unittest.mock import MagicMock, patch

from werkzeug.security import generate_password_hash

from retrobridge.models import Device, DevicePort, Job, User


def _login_admin(client, db_session):
    user = User(
        username='admincap',
        email='admincap@example.com',
        password_hash=generate_password_hash('Password123'),
        is_admin=True,
    )
    db_session.add(user)
    db_session.commit()
    resp = client.post('/auth/login', data={
        'username': 'admincap',
        'password': 'Password123',
    }, follow_redirects=True)
    assert resp.status_code == 200
    return user


def test_list_jobs_caps_per_page(client, db_session):
    _login_admin(client, db_session)
    device = Device(name='capdev')
    db_session.add(device)
    db_session.flush()
    for i in range(105):
        db_session.add(Job(
            user_id=1, device_id=device.id,
            original_filename=f'job{i}.bin', status='queued',
        ))
    db_session.commit()

    resp = client.get('/api/jobs?per_page=200')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data['jobs']) <= 100


def test_list_jobs_rejects_invalid_page(client, db_session):
    _login_admin(client, db_session)
    resp = client.get('/api/jobs?page=0&per_page=0')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['current_page'] == 1
    assert data['pages'] == 0 or data['pages'] == 1


def test_job_output_caps_tail(client, db_session, tmp_path):
    user = _login_admin(client, db_session)
    device = Device(name='capdev')
    db_session.add(device)
    db_session.flush()
    job = Job(
        user_id=user.id, device_id=device.id,
        original_filename='tail.bin', status='completed',
    )
    db_session.add(job)
    db_session.commit()

    output_dir = tmp_path / 'outputs' / f'job-{job.id}'
    output_dir.mkdir(parents=True)
    output_path = output_dir / 'session.log'
    output_path.write_text('\n'.join(f'line {i}' for i in range(15000)))
    job.output_path = str(output_path)
    db_session.commit()

    resp = client.get(f'/api/jobs/{job.id}/output?tail=20000')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data['lines']) <= 10000
