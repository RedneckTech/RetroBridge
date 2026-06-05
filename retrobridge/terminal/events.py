from flask import current_app, request
from flask_login import current_user
from flask_socketio import emit, disconnect

from retrobridge.models import Device, DevicePort, TerminalSession
from retrobridge.terminal import utils


def _get_sid():
    return getattr(request, 'sid', None)


def register_socketio_events(socketio):
    @socketio.on('connect', namespace='/terminal')
    def handle_connect():
        if not current_user.is_authenticated:
            return False

    @socketio.on('disconnect', namespace='/terminal')
    def handle_disconnect(reason=None):
        sid = _get_sid()
        if sid:
            utils.stop_bridge(socketio, sid, reason='user_disconnect')

    @socketio.on('request_session', namespace='/terminal')
    def handle_request_session(data):
        sid = _get_sid()

        if not current_user.is_authenticated:
            emit('session_denied', {'reason': 'Not authenticated'})
            return

        device_id = data.get('device_id')
        device = current_app.db_session.get(Device, device_id)
        if not device or not device.is_enabled:
            emit('session_denied', {'reason': 'Device not available'})
            return

        # Check user session quota
        active_count = (
            current_app.db_session.query(TerminalSession)
            .filter_by(user_id=current_user.id, status='active')
            .count()
        )
        if active_count >= current_user.max_terminal_sessions:
            emit('session_denied', {'reason': 'Maximum terminal sessions reached'})
            return

        # Check if this sid already has an active bridge
        if utils._active_bridges.get(sid, {}).get('running'):
            emit('session_denied', {'reason': 'Session already active on this connection'})
            return

        # Find available interactive port
        interactive_ports = (
            current_app.db_session.query(DevicePort)
            .filter_by(device_id=device_id, purpose='interactive', is_enabled=True)
            .all()
        )

        available_port = None
        for port in interactive_ports:
            if utils.allocate_port(port):
                available_port = port
                break

        if not available_port:
            emit('session_denied', {'reason': 'All interactive ports are currently in use'})
            return

        # Create session record
        session = utils.create_session(
            current_app.db_session,
            current_user.id,
            device_id,
            available_port.id,
        )

        # Start the serial bridge
        success = utils.start_bridge(socketio, sid, session, available_port)
        if not success:
            utils.end_session(current_app.db_session, session.id, reason='error')
            emit('session_denied', {
                'reason': f'Could not open serial port: {available_port.dev_path}'
            })
            return

        emit('session_granted', {
            'session_id': session.id,
            'device_name': device.display_name or device.name,
            'port_label': available_port.port_label,
            'cols': 80,
            'rows': 24,
        })

    @socketio.on('terminal_input', namespace='/terminal')
    def handle_terminal_input(data):
        sid = _get_sid()
        if sid:
            utils.write_to_serial(sid, data.get('data', ''))

    @socketio.on('terminal_resize', namespace='/terminal')
    def handle_terminal_resize(data):
        pass

    @socketio.on('heartbeat', namespace='/terminal')
    def handle_heartbeat(data=None):
        sid = _get_sid()
        if sid:
            bridge = utils._active_bridges.get(sid)
            if bridge and bridge['running']:
                bridge['last_activity'] = time.time()
        emit('heartbeat_ack')

    # Start the timeout monitor
    utils.start_timeout_monitor(socketio)


import time  # noqa: E402
