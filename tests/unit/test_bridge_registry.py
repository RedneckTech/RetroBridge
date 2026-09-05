"""Tests for cross-worker bridge registry."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from retrobridge.models import Device, DevicePort, TerminalSession, User
from retrobridge.terminal import utils


def _setup_session(db_session):
    user = User(username='bridgetest', email='b@example.com', password_hash='h')
    device = Device(name='bridge_dev')
    db_session.add_all([user, device])
    db_session.flush()
    port = DevicePort(device_id=device.id, port_label='T0', dev_path='/dev/tty0',
                      purpose='interactive')
    db_session.add(port)
    db_session.flush()
    session = TerminalSession(user_id=user.id, device_id=device.id, port_id=port.id,
                              status='active')
    db_session.add(session)
    db_session.commit()
    return session, port


def test_update_and_clear_bridge_registry(db_session):
    session, _ = _setup_session(db_session)

    utils._update_bridge_registry(db_session, session.id, status='active')
    db_session.refresh(session)

    assert session.bridge_worker_id == utils._terminal_worker_id()
    assert session.bridge_status == 'active'
    assert session.bridge_heartbeat_at is not None

    utils._clear_bridge_registry(db_session, session.id)
    db_session.refresh(session)

    assert session.bridge_worker_id is None
    assert session.bridge_status is None


def test_is_bridge_active_remotely(db_session):
    session, _ = _setup_session(db_session)

    assert utils.is_bridge_active_remotely(db_session, session.id) is False

    session.bridge_worker_id = 'other-host:1234'
    session.bridge_heartbeat_at = datetime.now(timezone.utc)
    session.bridge_status = 'active'
    db_session.commit()

    assert utils.is_bridge_active_remotely(db_session, session.id) is True


def test_is_bridge_active_remotely_stale_heartbeat(db_session):
    session, _ = _setup_session(db_session)

    session.bridge_worker_id = 'other-host:1234'
    session.bridge_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=999)
    session.bridge_status = 'active'
    db_session.commit()

    assert utils.is_bridge_active_remotely(db_session, session.id) is False


def test_end_session_clears_registry(db_session):
    session, _ = _setup_session(db_session)
    session.bridge_worker_id = utils._terminal_worker_id()
    session.bridge_status = 'active'
    db_session.commit()

    utils.end_session(db_session, session.id, reason='test')
    db_session.refresh(session)

    assert session.status == 'disconnected'
    assert session.bridge_worker_id is None
    assert session.bridge_status is None


def test_force_disconnect_without_local_bridge_marks_disconnected(db_session):
    session, _ = _setup_session(db_session)
    socketio = MagicMock()

    result = utils.force_disconnect_session(socketio, session.id, db_session=db_session)

    assert result is True
    db_session.refresh(session)
    assert session.status == 'disconnected'
    assert session.disconnect_reason == 'admin_force'
