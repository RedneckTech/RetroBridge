"""Tests for job creation validation."""
from io import BytesIO

from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash

from retrobridge.jobs.utils import create_job
from retrobridge.models import Device, User


def _make_file():
    return FileStorage(
        stream=BytesIO(b'valid content'),
        filename='test.bin',
        content_type='application/octet-stream',
    )


def test_create_job_rejects_missing_device(app, db_session, tmp_path):
    with app.app_context():
        user = User(username='jobuser', email='j@example.com',
                    password_hash=generate_password_hash('Pass123'))
        db_session.add(user)
        db_session.commit()

        try:
            create_job(db_session, user.id, 9999, 'test.bin', _make_file(),
                       str(tmp_path))
        except ValueError as exc:
            assert 'does not exist' in str(exc)
        else:
            raise AssertionError('Expected ValueError')


def test_create_job_rejects_disabled_device(app, db_session, tmp_path):
    with app.app_context():
        user = User(username='jobuser2', email='j2@example.com',
                    password_hash=generate_password_hash('Pass123'))
        device = Device(name='disabled', is_enabled=False)
        db_session.add_all([user, device])
        db_session.commit()

        try:
            create_job(db_session, user.id, device.id, 'test.bin', _make_file(),
                       str(tmp_path))
        except ValueError as exc:
            assert 'disabled' in str(exc)
        else:
            raise AssertionError('Expected ValueError')


def test_create_job_accepts_enabled_device(app, db_session, tmp_path):
    with app.app_context():
        user = User(username='jobuser3', email='j3@example.com',
                    password_hash=generate_password_hash('Pass123'))
        device = Device(name='enabled')
        db_session.add_all([user, device])
        db_session.commit()

        job = create_job(db_session, user.id, device.id, 'test.bin', _make_file(),
                         str(tmp_path))
        assert job.id is not None
        assert job.device_id == device.id
