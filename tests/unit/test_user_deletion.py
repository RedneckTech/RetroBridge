"""Unit tests for user deletion cascade and file cleanup."""
import os
from pathlib import Path

from werkzeug.security import generate_password_hash

from retrobridge.models import Device, DevicePort, Job, TerminalSession, User


def _login_admin(client, db_session):
    admin = User(
        username='adminuser',
        email='admin@example.com',
        password_hash=generate_password_hash('Password123'),
        is_admin=True,
    )
    db_session.add(admin)
    db_session.commit()
    resp = client.post('/auth/login', data={
        'username': 'adminuser',
        'password': 'Password123',
    }, follow_redirects=True)
    assert resp.status_code == 200
    return admin


def test_delete_user_cascades_jobs_and_sessions(client, db_session, tmp_path):
    _login_admin(client, db_session)

    device = Device(name='deldev')
    db_session.add(device)
    db_session.flush()
    port = DevicePort(device_id=device.id, port_label='TTY0',
                      dev_path='/tmp/tty0', purpose='job_queue')
    db_session.add(port)
    db_session.flush()

    user = User(username='deleteme', email='del@example.com',
                password_hash=generate_password_hash('Pass123'))
    db_session.add(user)
    db_session.flush()

    job = Job(user_id=user.id, device_id=device.id, port_id=port.id,
              original_filename='del.bin', stored_filename='job-999/del.bin')
    session = TerminalSession(user_id=user.id, device_id=device.id, port_id=port.id)
    db_session.add_all([job, session])
    db_session.commit()

    resp = client.delete(f'/api/admin/users/{user.id}')
    assert resp.status_code == 200

    assert db_session.get(User, user.id) is None
    assert db_session.get(Job, job.id) is None
    assert db_session.get(TerminalSession, session.id) is None


def test_delete_user_removes_files(client, app, db_session, tmp_path):
    _login_admin(client, db_session)

    device = Device(name='deldev2')
    db_session.add(device)
    db_session.flush()
    port = DevicePort(device_id=device.id, port_label='TTY0',
                      dev_path='/tmp/tty0', purpose='job_queue')
    db_session.add(port)
    db_session.flush()

    user = User(username='deleteme2', email='del2@example.com',
                password_hash=generate_password_hash('Pass123'))
    db_session.add(user)
    db_session.flush()

    upload_dir = tmp_path / 'uploads'
    output_dir = tmp_path / 'outputs'
    session_dir = tmp_path / 'session_logs'
    app.config['UPLOAD_DIR'] = str(upload_dir)
    app.config['OUTPUT_DIR'] = str(output_dir)
    app.config['SESSION_LOG_DIR'] = str(session_dir)

    job = Job(user_id=user.id, device_id=device.id, port_id=port.id,
              original_filename='del.bin', stored_filename='job-999/del.bin',
              output_path=str(output_dir / 'job-999' / 'session.log'))
    session = TerminalSession(user_id=user.id, device_id=device.id, port_id=port.id)
    db_session.add_all([job, session])
    db_session.commit()

    up = upload_dir / 'job-999'
    up.mkdir(parents=True)
    (up / 'del.bin').write_text('data')
    out = output_dir / 'job-999'
    out.mkdir(parents=True)
    (out / 'session.log').write_text('log')
    sess = session_dir / f'session-{session.id}'
    sess.mkdir(parents=True)
    (sess / 'terminal.log').write_text('term')

    resp = client.delete(f'/api/admin/users/{user.id}')
    assert resp.status_code == 200

    assert not up.exists()
    assert not out.exists()
    assert not sess.exists()
