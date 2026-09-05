"""Tests for device stats privacy."""
from werkzeug.security import generate_password_hash

from retrobridge.jobs.utils import get_device_stats
from retrobridge.models import Device, DevicePort, User


def _setup(db_session):
    user = User(username='statsuser', email='s@example.com',
                password_hash=generate_password_hash('Pass123'))
    device = Device(name='statsdev')
    db_session.add_all([user, device])
    db_session.flush()
    port = DevicePort(
        device_id=device.id, port_label='T0', dev_path='/dev/tty0',
        purpose='job_queue', pre_transfer_cmds='["secret"]',
        post_transfer_cmds='["also secret"]',
    )
    db_session.add(port)
    db_session.commit()
    return device, port


def test_get_device_stats_hides_commands_for_non_admin(db_session):
    _setup(db_session)
    stats = get_device_stats(db_session, is_admin=False)
    assert len(stats) == 1
    port_info = stats[0]['ports'][0]
    assert 'pre_cmds' not in port_info
    assert 'post_cmds' not in port_info


def test_get_device_stats_includes_commands_for_admin(db_session):
    _setup(db_session)
    stats = get_device_stats(db_session, is_admin=True)
    assert len(stats) == 1
    port_info = stats[0]['ports'][0]
    assert port_info['pre_cmds'] == '["secret"]'
    assert port_info['post_cmds'] == '["also secret"]'
