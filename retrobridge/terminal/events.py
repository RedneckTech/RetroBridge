from flask import current_app
from flask_login import current_user
from flask_socketio import emit, disconnect

from retrobridge.models import Device, DevicePort, TerminalSession


def register_socketio_events(socketio):
    @socketio.on('connect', namespace='/terminal')
    def handle_connect():
        if not current_user.is_authenticated:
            return False

    @socketio.on('disconnect', namespace='/terminal')
    def handle_disconnect():
        pass

    @socketio.on('request_session', namespace='/terminal')
    def handle_request_session(data):
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

        # Find available interactive port
        interactive_ports = (
            current_app.db_session.query(DevicePort)
            .filter_by(device_id=device_id, purpose='interactive', is_enabled=True)
            .all()
        )

        available_port = None
        for port in interactive_ports:
            active = (
                current_app.db_session.query(TerminalSession)
                .filter_by(port_id=port.id, status='active')
                .first()
            )
            if not active:
                available_port = port
                break

        if not available_port:
            emit('session_denied', {'reason': 'All interactive ports are currently in use'})
            return

        # Create session record
        session = TerminalSession(
            user_id=current_user.id,
            device_id=device_id,
            port_id=available_port.id,
            status='active',
        )
        current_app.db_session.add(session)
        current_app.db_session.commit()

        emit('session_granted', {
            'session_id': session.id,
            'device_name': device.display_name or device.name,
            'port_label': available_port.port_label,
            'cols': 80,
            'rows': 24,
        })

    @socketio.on('terminal_input', namespace='/terminal')
    def handle_terminal_input(data):
        # Will write data to serial port once serial bridge is implemented
        pass

    @socketio.on('terminal_resize', namespace='/terminal')
    def handle_terminal_resize(data):
        pass

    @socketio.on('heartbeat', namespace='/terminal')
    def handle_heartbeat():
        emit('heartbeat_ack')
