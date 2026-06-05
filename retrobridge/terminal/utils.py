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
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone

from serial import Serial, SerialException

from retrobridge.models import TerminalSession

logger = logging.getLogger(__name__)

_active_bridges = {}
_lock = threading.Lock()


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
            params = get_serial_params(port)
            ser = Serial(**params)
            # Disable local echo on the PTY slave to prevent feedback loops
            try:
                import termios
                fd = ser.fileno()
                attrs = termios.tcgetattr(fd)
                attrs[3] = attrs[3] & ~termios.ECHO   # lflags: disable ECHO
                termios.tcsetattr(fd, termios.TCSANOW, attrs)
            except Exception:
                pass
        except SerialException as e:
            logger.error(f'Cannot open serial port {port.dev_path}: {e}')
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
        }

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

    if db_session is None:
        from flask import current_app
        db_session = current_app.db_session

    end_session(db_session, bridge['session_id'], reason)

    socketio.emit('session_closed', {'reason': reason},
                  namespace='/terminal', to=sid)


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
