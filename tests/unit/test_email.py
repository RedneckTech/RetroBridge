"""Unit tests for email notifications."""
import pytest

from werkzeug.security import generate_password_hash

from retrobridge.integrations.email import (
    _load_settings_from_db,
    notify_job_completed,
    notify_password_changed,
)
from retrobridge.models import AdminSetting, Device, Job, User


def test_load_settings_from_db(db_session):
    db_session.add_all([
        AdminSetting(key='EMAIL_SMTP_HOST', value='smtp.example.com'),
        AdminSetting(key='EMAIL_SMTP_PORT', value='465'),
        AdminSetting(key='EMAIL_SMTP_USER', value='user'),
        AdminSetting(key='EMAIL_SMTP_PASSWORD', value='pass'),
        AdminSetting(key='EMAIL_USE_TLS', value='true'),
        AdminSetting(key='EMAIL_USE_SSL', value='false'),
        AdminSetting(key='EMAIL_FROM_ADDRESS', value='from@example.com'),
        AdminSetting(key='EMAIL_FROM_NAME', value='RB Test'),
    ])
    db_session.commit()

    settings = _load_settings_from_db(db_session)
    assert settings['smtp_host'] == 'smtp.example.com'
    assert settings['smtp_port'] == 465
    assert settings['smtp_user'] == 'user'
    assert settings['smtp_password'] == 'pass'
    assert settings['use_tls'] is True
    assert settings['use_ssl'] is False
    assert settings['from_address'] == 'from@example.com'
    assert settings['from_name'] == 'RB Test'


def test_no_email_when_host_missing(db_session, monkeypatch):
    """send_email should short-circuit when SMTP host is not configured."""
    from retrobridge.integrations import email

    calls = []
    monkeypatch.setattr(email._executor, 'submit', lambda *a, **kw: calls.append((a, kw)))

    email.send_email('to@example.com', 'subject', 'body', settings={'smtp_host': ''})
    assert calls == []


def test_notify_job_completed_uses_passed_settings(db_session, monkeypatch):
    device = Device(name='emaildev')
    db_session.add(device)
    db_session.flush()
    user = User(username='emailuser', email='u@example.com',
                password_hash=generate_password_hash('Pass123'))
    db_session.add(user)
    db_session.flush()
    job = Job(user_id=user.id, device_id=device.id, original_filename='x.mod',
              status='completed')
    db_session.add(job)
    db_session.commit()

    submitted = {}

    def fake_submit(func, *args, **kwargs):
        submitted['func'] = func
        submitted['args'] = args
        submitted['kwargs'] = kwargs

    from retrobridge.integrations import email
    monkeypatch.setattr(email._executor, 'submit', fake_submit)

    settings = {
        'smtp_host': 'smtp.example.com',
        'smtp_port': 587,
        'smtp_user': 'u',
        'smtp_password': 'p',
        'use_tls': True,
        'use_ssl': False,
        'from_address': 'from@example.com',
        'from_name': 'RB',
    }
    notify_job_completed(user, job, settings=settings)

    assert submitted
    assert submitted['args'][-1] == settings


def test_notify_password_changed(db_session, monkeypatch):
    user = User(username='pwuser', email='pw@example.com',
                password_hash=generate_password_hash('Pass123'))
    db_session.add(user)
    db_session.commit()

    submitted = {}

    def fake_submit(func, *args, **kwargs):
        submitted['args'] = args

    from retrobridge.integrations import email
    monkeypatch.setattr(email._executor, 'submit', fake_submit)

    notify_password_changed(user, settings={'smtp_host': 'smtp.example.com'})

    assert submitted['args'][0] == 'pw@example.com'
    assert submitted['args'][1] == 'RetroBridge \u2014 Password Changed'
