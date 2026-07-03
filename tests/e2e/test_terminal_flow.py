"""E2E tests — terminal session flow via WebSocket (SocketIO)."""

import tempfile
import time

import pytest
from flask_socketio import SocketIOTestClient
from werkzeug.security import generate_password_hash

from retrobridge.models import Device, DevicePort, TerminalSession, User
from retrobridge.terminal import utils as terminal_utils


@pytest.fixture
def app():
    from retrobridge import create_app
    from retrobridge import socketio as base_socketio
    app = create_app('config.TestConfig')
    app.config['UPLOAD_DIR'] = tempfile.mkdtemp()
    app.config['OUTPUT_DIR'] = tempfile.mkdtemp()
    app.config['SESSION_LOG_DIR'] = tempfile.mkdtemp()

    from retrobridge.models import Base
    Base.metadata.create_all(bind=app.db_engine)

    yield app

    app.db_session.remove()
    terminal_utils._active_bridges.clear()
    terminal_utils._suspended_bridges.clear()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded_app(app):
    """Seed app with user, device, and interactive port."""
    user = User(username='termuser', email='termuser@example.com',
                password_hash=generate_password_hash('password'),
                max_terminal_sessions=1)
    device = Device(name='centurion', display_name='Centurion CPU-6')
    app.db_session.add_all([user, device])
    app.db_session.flush()

    port = DevicePort(
        device_id=device.id, port_label='TTY1',
        dev_path='/dev/null', purpose='interactive',
        baud=9600, idle_timeout_seconds=300,
        max_runtime_seconds=3600,
    )
    app.db_session.add(port)
    app.db_session.commit()

    yield app


@pytest.fixture
def seeded_client(seeded_app):
    return seeded_app.test_client()


def _login(seeded_client):
    seeded_client.post('/auth/login', data={
        'username': 'termuser', 'password': 'password',
    }, follow_redirects=True)


class TestTerminalSession:
    """SDD 10.3: Full terminal session path — connect, interact, disconnect."""

    def test_terminal_index_shows_devices(self, seeded_client):
        _login(seeded_client)
        resp = seeded_client.get('/terminal/')
        assert resp.status_code == 200
        assert b'Centurion' in resp.data

    def test_terminal_session_page_loads(self, seeded_client):
        _login(seeded_client)
        resp = seeded_client.get('/terminal/1')
        assert resp.status_code == 200

    def test_terminal_requires_login(self, client):
        resp = client.get('/terminal/')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_terminal_page_404_for_nonexistent_device(self, seeded_client):
        _login(seeded_client)
        resp = seeded_client.get('/terminal/999')
        assert resp.status_code == 302

    def test_socketio_connect_requires_auth(self, seeded_app, seeded_client):
        from retrobridge import socketio
        socket_client = SocketIOTestClient(seeded_app, socketio,
                                           namespace='/terminal')
        assert socket_client.is_connected(namespace='/terminal') is False

    def test_request_session_creates_record(self, seeded_app, seeded_client):
        from retrobridge.simulation import create_terminal_simulation
        sim = create_terminal_simulation('centurion')
        try:
            port = seeded_app.db_session.get(DevicePort, 1)
            port.dev_path = sim['slave_name']
            seeded_app.db_session.commit()

            from retrobridge import socketio
            _login(seeded_client)

            socket_client = SocketIOTestClient(seeded_app, socketio,
                                               namespace='/terminal',
                                               flask_test_client=seeded_client)
            assert socket_client.is_connected(namespace='/terminal') is True

            socket_client.emit('request_session',
                               {'device_id': 1},
                               namespace='/terminal')
            time.sleep(0.5)

            received = socket_client.get_received(namespace='/terminal')
            session_granted = [r for r in received
                               if r['name'] == 'session_granted']

            assert len(session_granted) >= 1
            data = session_granted[0]['args'][0]
            assert data.get('session_id') is not None
            assert data.get('device_name') is not None

            session_id = data['session_id']

            session = seeded_app.db_session.get(TerminalSession, session_id)
            assert session is not None
            assert session.status == 'active'
            assert session.user_id == 1

            socket_client.emit('terminal_input',
                               {'data': 'DIR\r\n'},
                               namespace='/terminal')
            time.sleep(0.5)

            socket_client.disconnect(namespace='/terminal')

            seeded_app.db_session.refresh(session)
            assert session.status == 'active'

            # Verify bridge is suspended (not destroyed)
            assert len(terminal_utils._active_bridges) == 0
            assert session_id in terminal_utils._suspended_bridges
        finally:
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)


class TestTerminalSessionDenial:
    """SDD 10.3: Terminal session denial when ports exhausted."""

    def test_session_denied_when_all_ports_in_use(self, seeded_app,
                                                   seeded_client):
        from retrobridge.simulation import create_terminal_simulation
        sim = create_terminal_simulation('centurion')
        try:
            port = seeded_app.db_session.get(DevicePort, 1)
            port.dev_path = sim['slave_name']
            seeded_app.db_session.commit()

            from retrobridge import socketio
            _login(seeded_client)

            sock1 = SocketIOTestClient(seeded_app, socketio,
                                       namespace='/terminal',
                                       flask_test_client=seeded_client)
            sock1.emit('request_session', {'device_id': 1},
                       namespace='/terminal')
            time.sleep(0.5)

            received1 = sock1.get_received(namespace='/terminal')
            assert any(r['name'] == 'session_granted' for r in received1)

            sock2 = SocketIOTestClient(seeded_app, socketio,
                                       namespace='/terminal',
                                       flask_test_client=seeded_client)
            sock2.emit('request_session', {'device_id': 1},
                       namespace='/terminal')
            time.sleep(0.5)

            received2 = sock2.get_received(namespace='/terminal')
            denied = [r for r in received2 if r['name'] == 'session_denied']
            assert len(denied) >= 1

            sock1.disconnect(namespace='/terminal')
            sock2.disconnect(namespace='/terminal')
        finally:
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)


class TestTerminalAPIIntegration:
    """E2E terminal session API endpoints."""

    def test_api_devices_list_includes_terminal_info(self, seeded_client):
        _login(seeded_client)
        resp = seeded_client.get('/api/devices')
        assert resp.status_code == 200
        import json
        data = json.loads(resp.data)
        assert len(data['devices']) == 1
        assert data['devices'][0]['name'] == 'centurion'
        assert 'interactive_ports_total' in data['devices'][0]
        assert 'interactive_ports_available' in data['devices'][0]

    def test_api_device_ports_shows_interactive_ports(self, seeded_client):
        _login(seeded_client)
        resp = seeded_client.get('/api/devices/1/ports')
        assert resp.status_code == 200
        import json
        data = json.loads(resp.data)
        assert len(data['ports']) == 1
        assert data['ports'][0]['purpose'] == 'interactive'

    def test_api_sessions_active_requires_admin(self, seeded_client):
        _login(seeded_client)
        resp = seeded_client.get('/api/sessions/active')
        assert resp.status_code == 403
