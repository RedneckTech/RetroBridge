"""Tests for admin device/port form validation."""
from werkzeug.datastructures import MultiDict
from werkzeug.security import generate_password_hash

from retrobridge.admin.forms import DevicePortForm
from retrobridge.models import User


def _login_admin(client, db_session):
    user = User(username='admin', email='a@example.com',
                password_hash=generate_password_hash('Admin123'), is_admin=True)
    db_session.add(user)
    db_session.commit()
    client.post('/auth/login', data={'username': 'admin', 'password': 'Admin123'},
                follow_redirects=True)


def _make_form_data(extra=None):
    data = MultiDict([
        ('port_label', 'T0'),
        ('transport', 'serial'),
        ('dev_path', '/dev/tty0'),
        ('purpose', 'job_queue'),
        ('baud', '9600'),
        ('data_bits', '8'),
        ('parity', 'N'),
        ('stop_bits', '1'),
        ('flow_control', 'none'),
        ('newline_mode', 'crlf'),
        ('transfer_protocol', 'xmodem'),
        ('max_concurrent_jobs', '1'),
        ('max_runtime_seconds', '300'),
        ('idle_timeout_seconds', '5'),
    ])
    if extra:
        for key, value in extra.items():
            data.setlist(key, [value])
    return data


def test_port_form_rejects_invalid_json(app):
    with app.app_context():
        form = DevicePortForm(formdata=_make_form_data(
            {'pre_transfer_cmds': 'not json'},
        ))
        assert form.validate() is False
        assert 'pre_transfer_cmds' in form.errors


def test_port_form_rejects_non_array_json(app):
    with app.app_context():
        form = DevicePortForm(formdata=_make_form_data(
            {'post_transfer_cmds': '{"key": "value"}'},
        ))
        assert form.validate() is False
        assert 'post_transfer_cmds' in form.errors


def test_port_form_accepts_valid_json_array(app):
    with app.app_context():
        form = DevicePortForm(formdata=_make_form_data(
            {'pre_transfer_cmds': '["echo hello"]', 'post_transfer_cmds': '[]'},
        ))
        assert form.validate() is True


def test_port_form_restricts_transfer_protocol_choices(app):
    with app.app_context():
        form = DevicePortForm(formdata=_make_form_data(
            {'transfer_protocol': 'kermit'},
        ))
        assert form.validate() is False
        assert 'transfer_protocol' in form.errors
