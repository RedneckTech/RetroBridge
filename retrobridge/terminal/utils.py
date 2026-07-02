"""
Terminal Session Utilities
===========================
Serial port bridging, session management, and timeout enforcement for
interactive terminal sessions.

Each active session has:
  - A TerminalSession DB record
  - A pyserial Serial object connected to the RS-232 port
  - A background thread that reads from serial and emits via SocketIO
  - Timeout timers for idle and max session duration
  - Optional per-session keystroke/output log file
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from serial import Serial, SerialException

from retrobridge.models import TerminalSession
from retrobridge.transport import open_transport, transport_uses_baud

logger = logging.getLogger(__name__)

_active_bridges = {}
_lock = threading.Lock()


def _session_log_path(session_id):
    from flask import current_app
    log_dir = current_app.config.get('SESSION_LOG_DIR', 'session_logs')
    session_dir = os.path.join(log_dir, f'session-{session_id}')
    os.makedirs(session_dir, exist_ok=True)
    return os.path.join(session_dir, 'terminal.log')


def _session_logging_enabled():
    try:
        from retrobridge.admin.settings_utils import get_bool
        return get_bool('TERMINAL_SESSION_LOG_ENABLED')
    except Exception:
        return False


def _log_line(log_file, line, direction):
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    try:
        log_file.write(f'[{ts}] [{direction}] {line}\n')
        log_file.flush()
    except Exception:
        pass


def get_serial_params(port):
    return {
        'port': port.dev_path,
        'baudrate': port.baud if port.baud else 9600,
        'bytesize': port.data_bits if port.data_bits else 8,
        'parity': (port.parity or 'N').upper(),
        'stopbits': port.stop_bits if port.stop_bits else 1,
        'timeout': 0.1,
        'rtscts': port.flow_control == 'rtscts',
        'xonxoff': port.flow_control == 'xonxoff',
    }


def allocate_port(port):
    with _lock:
        for sid, bridge in _active_bridges.items():
            if bridge['port_id'] == port.id and bridge['running']:
                return False
        return True


def release_port(port):
    pass


def create_session(db_session, user_id, device_id, port_id):
    session = TerminalSession(
        user_id=user_id,
        device_id=device_id,
        port_id=port_id,
        status='active',
    )
    db_session.add(session)
    db_session.commit()
    return session


def end_session(db_session, session_id, reason='user_disconnect'):
    now = datetime.now(timezone.utc)
    session = db_session.get(TerminalSession, session_id)
    if session:
        session.status = 'disconnected'
        session.disconnect_reason = reason
        session.disconnected_at = now
        if session.connected_at:
            connected = session.connected_at
            if connected.tzinfo is None:
                from datetime import timezone as tz
                connected = connected.replace(tzinfo=tz.utc)
            session.duration_seconds = int((now - connected).total_seconds())
        db_session.commit()


def _serial_reader(socketio, sid, ser, session_id):
    bridge = _active_bridges.get(sid)
    while bridge and bridge['running']:
        try:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting)
                if data:
                    decoded = data.decode('utf-8', errors='replace')
                    socketio.emit('terminal_output', {'data': decoded},
                                  namespace='/terminal', to=sid)
                    bridge['bytes_received'] += len(data)
                    bridge['last_activity'] = time.time()
                    if bridge.get('log_file'):
                        _log_line(bridge['log_file'], decoded, 'RX')
            else:
                time.sleep(0.05)
        except (SerialException, OSError) as e:
            logger.error(f'Serial read error for session {session_id}: {e}')
            bridge['running'] = False
            socketio.emit('session_closed', {'reason': f'Connection lost: {e}'},
                          namespace='/terminal', to=sid)
            break
        except Exception as e:
            logger.exception(f'Read thread error for session {session_id}: {e}')
            bridge['running'] = False
            break


def start_bridge(socketio, sid, session, port):
    with _lock:
        if sid in _active_bridges:
            return False

        try:
            ser = open_transport(port)
            # Disable local echo on the PTY slave to prevent feedback loops
            if (port.transport or 'serial') in ('serial', 'pty'):
                try:
                    import termios
                    fd = ser.fileno() if hasattr(ser, 'fileno') else ser.fd
                    attrs = termios.tcgetattr(fd)
                    attrs[3] = attrs[3] & ~termios.ECHO
                    termios.tcsetattr(fd, termios.TCSANOW, attrs)
                except Exception:
                    pass
        except SerialException as e:
            logger.error(f'Cannot open {port.transport or "serial"} port {port.dev_path}: {e}')
            return False

        bridge = {
            'serial': ser,
            'thread': None,
            'sid': sid,
            'session_id': session.id,
            'port_id': port.id,
            'device_id': port.device_id,
            'running': True,
            'bytes_sent': 0,
            'bytes_received': 0,
            'last_activity': time.time(),
            'start_time': time.time(),
            'max_runtime': port.max_runtime_seconds or 3600,
            'idle_timeout': port.idle_timeout_seconds or 300,
            'log_file': None,
        }

        if _session_logging_enabled():
            try:
                log_path = _session_log_path(session.id)
                bridge['log_file'] = open(log_path, 'a', encoding='utf-8', errors='replace')
                msg = f'Session #{session.id} started on {port.dev_path}'
                _log_line(bridge['log_file'], msg, 'SYS')
            except Exception as e:
                logger.warning(f'Could not open session log: {e}')

        thread = threading.Thread(
            target=_serial_reader,
            args=(socketio, sid, ser, session.id),
            daemon=True,
        )
        bridge['thread'] = thread
        _active_bridges[sid] = bridge
        thread.start()
        return True


def stop_bridge(socketio, sid, reason='user_disconnect', db_session=None):
    with _lock:
        bridge = _active_bridges.pop(sid, None)

    if not bridge:
        return

    bridge['running'] = False

    if bridge['thread'] and bridge['thread'].is_alive():
        bridge['thread'].join(timeout=2)

    ser = bridge.get('serial')
    if ser and ser.is_open:
        try:
            ser.close()
        except Exception:
            pass

    if bridge.get('log_file'):
        try:
            _log_line(bridge['log_file'], f'Session ended: {reason}', 'SYS')
            bridge['log_file'].close()
        except Exception:
            pass

    if db_session is None:
        from flask import current_app
        db_session = current_app.db_session

    end_session(db_session, bridge['session_id'], reason)

    socketio.emit('session_closed', {'reason': reason},
                  namespace='/terminal', to=sid)


def find_bridge_sid(session_id):
    with _lock:
        for sid, bridge in _active_bridges.items():
            if bridge.get('session_id') == session_id and bridge['running']:
                return sid
    return None


def force_disconnect_session(socketio, session_id, db_session=None):
    sid = find_bridge_sid(session_id)
    if sid:
        stop_bridge(socketio, sid, reason='admin_force',
                    db_session=db_session)
        return True

    if db_session is None:
        from flask import current_app
        db_session = current_app.db_session

    end_session(db_session, session_id, reason='admin_force')
    return False


def write_to_serial(sid, data):
    bridge = _active_bridges.get(sid)
    if not bridge or not bridge['running']:
        return False

    ser = bridge.get('serial')
    if not ser or not ser.is_open:
        return False

    try:
        encoded = data.encode('utf-8', errors='replace')
        ser.write(encoded)
        bridge['bytes_sent'] += len(encoded)
        bridge['last_activity'] = time.time()
        if bridge.get('log_file'):
            _log_line(bridge['log_file'], data, 'TX')
        return True
    except SerialException:
        return False


def check_timeouts(socketio, db_session=None):
    now = time.time()
    with _lock:
        expired = []
        for sid, bridge in list(_active_bridges.items()):
            if not bridge['running']:
                continue

            elapsed = now - bridge['start_time']
            idle = now - bridge['last_activity']

            if elapsed > bridge['max_runtime']:
                expired.append((sid, 'timeout'))
            elif idle > bridge['idle_timeout']:
                expired.append((sid, 'idle_timeout'))

    for sid, reason in expired:
        logger.info(f'Terminating session {sid}: {reason}')
        stop_bridge(socketio, sid, reason, db_session=db_session)


def _timeout_monitor(socketio, interval=10):
    while True:
        time.sleep(interval)
        try:
            app = getattr(socketio, '_flask_app', None)
            if app:
                with app.app_context():
                    check_timeouts(socketio)
            else:
                check_timeouts(socketio)
        except Exception:
            pass


def start_timeout_monitor(socketio):
    thread = threading.Thread(
        target=_timeout_monitor,
        args=(socketio,),
        daemon=True,
        name='terminal-timeout-monitor',
    )
    thread.start()
    return thread
