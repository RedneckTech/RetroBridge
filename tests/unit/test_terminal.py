"""Unit tests for terminal serial bridge utilities."""
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock

import pytest

from retrobridge.models import User, Device, DevicePort, TerminalSession
from retrobridge.terminal import utils


class TestAllocatePort:
    def test_port_free_when_no_bridges(self):
        port = MagicMock()
        port.id = 1
        assert utils.allocate_port(port) is True

    def test_port_busy_when_bridge_active(self):
        port = MagicMock()
        port.id = 1
        utils._active_bridges['test_sid'] = {
            'port_id': 1, 'running': True,
        }
        result = utils.allocate_port(port)
        del utils._active_bridges['test_sid']
        assert result is False

    def test_port_free_when_bridge_stopped(self):
        port = MagicMock()
        port.id = 1
        utils._active_bridges['test_sid'] = {
            'port_id': 1, 'running': False,
        }
        result = utils.allocate_port(port)
        del utils._active_bridges['test_sid']
        assert result is True

    def test_different_port_free(self):
        port = MagicMock()
        port.id = 2
        utils._active_bridges['test_sid'] = {
            'port_id': 1, 'running': True,
        }
        result = utils.allocate_port(port)
        del utils._active_bridges['test_sid']
        assert result is True


class TestSerialParams:
    def test_default_params(self):
        port = MagicMock()
        port.dev_path = '/dev/ttyUSB0'
        port.baud = 9600
        port.data_bits = 8
        port.parity = 'N'
        port.stop_bits = 1
        port.flow_control = 'none'

        params = utils.get_serial_params(port)
        assert params['baudrate'] == 9600
        assert params['bytesize'] == 8
        assert params['parity'] == 'N'
        assert params['rtscts'] is False
        assert params['xonxoff'] is False

    def test_rtscts_flow(self):
        port = MagicMock()
        port.dev_path = '/dev/ttyS0'
        port.baud = 19200
        port.data_bits = 8
        port.parity = None
        port.stop_bits = 1
        port.flow_control = 'rtscts'

        params = utils.get_serial_params(port)
        assert params['rtscts'] is True
        assert params['xonxoff'] is False

    def test_xonxoff_flow(self):
        port = MagicMock()
        port.dev_path = '/dev/ttyS0'
        port.baud = 9600
        port.data_bits = 8
        port.parity = 'E'
        port.stop_bits = 1
        port.flow_control = 'xonxoff'

        params = utils.get_serial_params(port)
        assert params['rtscts'] is False
        assert params['xonxoff'] is True


class TestCreateSession:
    def test_creates_active_session(self, db_session):
        user = User(username='testuser', email='test@example.com',
                    password_hash='hash')
        device = Device(name='centurion')
        port = DevicePort(
            device_id=0, port_label='TTY1', dev_path='/dev/tty1',
            purpose='interactive',
        )
        db_session.add(device)
        db_session.flush()
        port.device_id = device.id
        db_session.add_all([user, port])
        db_session.commit()

        session = utils.create_session(db_session, user.id, device.id, port.id)
        assert session.id is not None
        assert session.status == 'active'
        assert session.connected_at is not None
        assert session.bytes_sent == 0
        assert session.bytes_received == 0


class TestEndSession:
    def test_marks_disconnected_with_reason(self, db_session):
        user = User(username='testuser', email='test@example.com',
                    password_hash='hash')
        device = Device(name='centurion')
        port = DevicePort(
            device_id=0, port_label='TTY1', dev_path='/dev/tty1',
            purpose='interactive',
        )
        db_session.add(device)
        db_session.flush()
        port.device_id = device.id
        db_session.add_all([user, port])
        db_session.commit()

        session = TerminalSession(
            user_id=user.id, device_id=device.id, port_id=port.id,
            status='active',
        )
        db_session.add(session)
        db_session.commit()

        utils.end_session(db_session, session.id, reason='idle_timeout')

        db_session.refresh(session)
        assert session.status == 'disconnected'
        assert session.disconnect_reason == 'idle_timeout'
        assert session.disconnected_at is not None
        assert session.duration_seconds is not None


class TestWriteToSerial:
    def setup_method(self):
        utils._active_bridges.clear()

    def test_returns_false_when_no_bridge(self):
        assert utils.write_to_serial('nonexistent', 'hello') is False

    def test_writes_to_serial_and_updates_counters(self):
        ser = MagicMock()
        ser.is_open = True

        utils._active_bridges['test_sid'] = {
            'serial': ser, 'running': True,
            'bytes_sent': 0, 'bytes_received': 0,
            'last_activity': time.time(),
        }

        result = utils.write_to_serial('test_sid', 'hello')
        assert result is True
        ser.write.assert_called_once()
        assert utils._active_bridges['test_sid']['bytes_sent'] == 5

    def test_returns_false_when_bridge_not_running(self):
        ser = MagicMock()
        utils._active_bridges['test_sid'] = {
            'serial': ser, 'running': False,
            'bytes_sent': 0,
            'last_activity': time.time(),
        }

        assert utils.write_to_serial('test_sid', 'hello') is False
        ser.write.assert_not_called()

    def test_returns_false_when_serial_closed(self):
        ser = MagicMock()
        ser.is_open = False
        utils._active_bridges['test_sid'] = {
            'serial': ser, 'running': True,
            'bytes_sent': 0,
            'last_activity': time.time(),
        }

        assert utils.write_to_serial('test_sid', 'hello') is False


class TestCheckTimeouts:
    def setup_method(self):
        utils._active_bridges.clear()

    def test_no_timeout_when_active(self):
        socketio = MagicMock()
        utils._active_bridges['sid1'] = {
            'running': True,
            'start_time': time.time(),
            'last_activity': time.time(),
            'max_runtime': 3600,
            'idle_timeout': 300,
            'session_id': 1,
            'port_id': 1,
        }
        utils.check_timeouts(socketio)
        assert 'sid1' in utils._active_bridges

    def test_idle_timeout_triggers_cleanup(self):
        socketio = MagicMock()
        mock_db = MagicMock()
        utils._active_bridges['sid1'] = {
            'running': True,
            'start_time': time.time(),
            'last_activity': time.time() - 9999,
            'max_runtime': 3600,
            'idle_timeout': 5,
            'serial': MagicMock(),
            'thread': MagicMock(),
            'session_id': 1,
            'port_id': 1,
        }
        utils.check_timeouts(socketio, db_session=mock_db)
        # The bridge should be stopped by now
        assert 'sid1' not in utils._active_bridges

    def test_max_runtime_triggers_cleanup(self):
        socketio = MagicMock()
        mock_db = MagicMock()
        utils._active_bridges['sid1'] = {
            'running': True,
            'start_time': time.time() - 9999,
            'last_activity': time.time(),
            'max_runtime': 1,
            'idle_timeout': 9999,
            'serial': MagicMock(),
            'thread': MagicMock(),
            'session_id': 1,
            'port_id': 1,
        }
        utils.check_timeouts(socketio, db_session=mock_db)
        assert 'sid1' not in utils._active_bridges


class TestRecoverStaleLeases:
    def setup_method(self):
        utils._active_bridges.clear()
        utils._suspended_bridges.clear()

    def test_skips_sessions_with_local_active_bridge(self, db_session):
        user = User(username='testuser', email='test@example.com',
                    password_hash='hash')
        device = Device(name='centurion')
        port = DevicePort(
            device_id=0, port_label='TTY1', dev_path='/dev/tty1',
            purpose='interactive',
        )
        db_session.add(device)
        db_session.flush()
        port.device_id = device.id
        db_session.add_all([user, port])
        db_session.commit()

        session = TerminalSession(
            user_id=user.id, device_id=device.id, port_id=port.id,
            status='active',
        )
        db_session.add(session)
        db_session.commit()

        from retrobridge.models import PortLease
        lease = PortLease(
            port_id=port.id,
            session_id=session.id,
            claimed_by='test-worker',
            claimed_at=datetime.now(timezone.utc),
            lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            heartbeat_at=datetime.now(timezone.utc),
        )
        db_session.add(lease)
        db_session.commit()

        utils._active_bridges['sid'] = {
            'session_id': session.id,
            'running': True,
        }

        utils.recover_stale_leases(db_session)

        db_session.refresh(session)
        assert session.status == 'active'
        assert db_session.get(PortLease, lease.id) is None

    def test_disconnects_expired_lease_without_local_bridge(self, db_session):
        user = User(username='testuser', email='test@example.com',
                    password_hash='hash')
        device = Device(name='centurion')
        port = DevicePort(
            device_id=0, port_label='TTY1', dev_path='/dev/tty1',
            purpose='interactive',
        )
        db_session.add(device)
        db_session.flush()
        port.device_id = device.id
        db_session.add_all([user, port])
        db_session.commit()

        session = TerminalSession(
            user_id=user.id, device_id=device.id, port_id=port.id,
            status='active',
        )
        db_session.add(session)
        db_session.commit()

        from retrobridge.models import PortLease
        lease = PortLease(
            port_id=port.id,
            session_id=session.id,
            claimed_by='test-worker',
            claimed_at=datetime.now(timezone.utc),
            lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            heartbeat_at=datetime.now(timezone.utc),
        )
        db_session.add(lease)
        db_session.commit()

        utils.recover_stale_leases(db_session)

        db_session.refresh(session)
        assert session.status == 'disconnected'
        assert session.disconnect_reason == 'lease_expired'
        assert db_session.get(PortLease, lease.id) is None


class TestResumeBridge:
    def setup_method(self):
        utils._active_bridges.clear()
        utils._suspended_bridges.clear()

    def test_resets_last_activity(self):
        socketio = MagicMock()
        session_id = 1
        now = time.time()
        utils._suspended_bridges[session_id] = {
            'session_id': session_id,
            'running': True,
            'sid': None,
            'suspended_at': now - 100,
            'start_time': now - 200,
            'last_activity': now - 150,
            'output_buffer': '',
            'serial': MagicMock(is_open=False),
        }

        bridge = utils.resume_bridge(socketio, 'new_sid', session_id)
        assert bridge is not None
        assert bridge['last_activity'] >= now
        assert 'suspended_at' not in bridge
        assert bridge['start_time'] > now - 200


class TestForceDisconnectSession:
    def setup_method(self):
        utils._active_bridges.clear()
        utils._suspended_bridges.clear()

    def test_disconnects_suspended_bridge(self):
        socketio = MagicMock()
        session_id = 1
        ser = MagicMock()
        ser.is_open = True
        utils._suspended_bridges[session_id] = {
            'session_id': session_id,
            'running': True,
            'serial': ser,
            'log_file': None,
        }

        db = MagicMock()
        result = utils.force_disconnect_session(socketio, session_id, db_session=db)
        assert result is True
        assert session_id not in utils._suspended_bridges
        ser.close.assert_called_once()
