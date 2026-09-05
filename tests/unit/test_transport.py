"""Unit tests for transport module."""
import socket
import threading
import time

import pytest

from retrobridge.transport import (
    open_transport, transport_uses_baud, _parse_host_port, _SocketWrapper,
)


class MockPort:
    def __init__(self, transport='serial', dev_path='/dev/null',
                 baud=9600, data_bits=8, parity='N', stop_bits=1,
                 flow_control='none'):
        self.transport = transport
        self.dev_path = dev_path
        self.baud = baud
        self.data_bits = data_bits
        self.parity = parity
        self.stop_bits = stop_bits
        self.flow_control = flow_control


class TestTransportUsesBaud:
    def test_serial_uses_baud(self):
        port = MockPort(transport='serial')
        assert transport_uses_baud(port) is True

    def test_pty_uses_baud(self):
        port = MockPort(transport='pty')
        assert transport_uses_baud(port) is True

    def test_rfc2217_uses_baud(self):
        port = MockPort(transport='rfc2217')
        assert transport_uses_baud(port) is True

    def test_tcp_does_not_use_baud(self):
        port = MockPort(transport='tcp')
        assert transport_uses_baud(port) is False

    def test_telnet_does_not_use_baud(self):
        port = MockPort(transport='telnet')
        assert transport_uses_baud(port) is False

    def test_none_transport_defaults_to_serial(self):
        port = MockPort(transport=None)
        assert transport_uses_baud(port) is True


class TestParseHostPort:
    def test_colon_format(self):
        host, port = _parse_host_port('127.0.0.1:8023')
        assert host == '127.0.0.1'
        assert port == 8023

    def test_space_format(self):
        host, port = _parse_host_port('127.0.0.1 8023')
        assert host == '127.0.0.1'
        assert port == 8023

    def test_hostname(self):
        host, port = _parse_host_port('emu.local:10023')
        assert host == 'emu.local'
        assert port == 10023

    def test_no_port_raises(self):
        with pytest.raises(Exception):
            _parse_host_port('127.0.0.1')

    def test_invalid_port_raises(self):
        with pytest.raises(Exception):
            _parse_host_port('127.0.0.1:abc')


class TestTcpTransport:
    def test_tcp_connect_and_read(self):
        data = b'HELLO FROM TCP\r\n'
        ready = threading.Event()
        result = []

        def echo_server():
            srv = socket.create_server(('127.0.0.1', 0))
            addr = srv.getsockname()
            result.append(addr[1])
            ready.set()
            conn, _ = srv.accept()
            conn.sendall(data)
            conn.close()
            srv.close()

        t = threading.Thread(target=echo_server, daemon=True)
        t.start()
        ready.wait(timeout=3)

        port_obj = MockPort(transport='tcp',
                            dev_path=f'127.0.0.1:{result[0]}')
        ser = open_transport(port_obj)
        try:
            time.sleep(0.2)
            received = b''
            deadline = time.time() + 3
            while time.time() < deadline:
                chunk = ser.read(1024)
                if chunk:
                    received += chunk
                if received:
                    break
                time.sleep(0.1)
            assert data in received
        finally:
            ser.close()
            t.join(timeout=2)

    def test_tcp_bad_host_raises(self):
        port = MockPort(transport='tcp', dev_path='127.0.0.1:19999')
        with pytest.raises(Exception):
            open_transport(port)

    def test_tcp_invalid_port_raises(self):
        port = MockPort(transport='tcp', dev_path='127.0.0.1:abc')
        with pytest.raises(Exception):
            open_transport(port)


class TestSocketWrapper:
    def test_read_write(self):
        data = b'TEST DATA'
        ready = threading.Event()
        result = []

        def echo_server():
            srv = socket.create_server(('127.0.0.1', 0))
            addr = srv.getsockname()
            result.append(addr[1])
            result.append(srv)
            ready.set()
            conn, _ = srv.accept()
            buf = conn.recv(1024)
            conn.sendall(buf)
            conn.close()
            srv.close()

        t = threading.Thread(target=echo_server, daemon=True)
        t.start()
        ready.wait(timeout=3)

        sock = socket.create_connection(('127.0.0.1', result[0]), timeout=3)
        wrapper = _SocketWrapper(sock)
        try:
            wrapper.write(data)
            time.sleep(0.3)
            received = wrapper.read(1024)
            assert received == data
            assert wrapper.is_open is True
        finally:
            wrapper.close()
            t.join(timeout=2)

    def test_close_sets_is_open_false(self):
        ready = threading.Event()
        result = []

        def server():
            srv = socket.create_server(('127.0.0.1', 0))
            result.append(srv.getsockname()[1])
            result.append(srv)
            ready.set()
            conn, _ = srv.accept()
            conn.close()
            srv.close()

        t = threading.Thread(target=server, daemon=True)
        t.start()
        ready.wait(timeout=3)

        sock = socket.create_connection(('127.0.0.1', result[0]), timeout=3)
        wrapper = _SocketWrapper(sock)
        wrapper.close()
        assert wrapper.is_open is False

        t.join(timeout=2)

    def test_fileno(self):
        ready = threading.Event()
        result = []

        def server():
            srv = socket.create_server(('127.0.0.1', 0))
            result.append(srv.getsockname()[1])
            ready.set()
            conn, _ = srv.accept()
            conn.close()
            srv.close()

        t = threading.Thread(target=server, daemon=True)
        t.start()
        ready.wait(timeout=3)

        sock = socket.create_connection(('127.0.0.1', result[0]), timeout=3)
        wrapper = _SocketWrapper(sock)
        try:
            assert wrapper.fileno() > 0
            assert wrapper.fd > 0
        finally:
            wrapper.close()
            t.join(timeout=2)

    def test_in_waiting_returns_int(self):
        wrapper = _SocketWrapper.__new__(_SocketWrapper)
        wrapper._sock = None
        assert wrapper.in_waiting == 0

    def test_in_waiting_drains_socket_into_buffer(self):
        ready = threading.Event()
        result = []
        payload = b'hello world'

        def server():
            srv = socket.create_server(('127.0.0.1', 0))
            result.append(srv.getsockname()[1])
            result.append(srv)
            ready.set()
            conn, _ = srv.accept()
            conn.sendall(payload)
            conn.close()
            srv.close()

        t = threading.Thread(target=server, daemon=True)
        t.start()
        ready.wait(timeout=3)

        sock = socket.create_connection(('127.0.0.1', result[0]), timeout=3)
        wrapper = _SocketWrapper(sock)
        try:
            # Give the server a moment to send.
            time.sleep(0.2)
            assert wrapper.in_waiting == len(payload)
            assert wrapper.read(len(payload)) == payload
        finally:
            wrapper.close()
            t.join(timeout=2)


class TestTelnetNegotiate:
    def test_preserves_non_iac_data(self):
        ready = threading.Event()
        result = []
        payload = b'login: '
        will_echo = bytes([255, 251, 1])  # IAC WILL ECHO

        def server():
            srv = socket.create_server(('127.0.0.1', 0))
            result.append(srv.getsockname()[1])
            result.append(srv)
            ready.set()
            conn, _ = srv.accept()
            conn.sendall(will_echo + payload)
            # Drain any response (IAC DONT ECHO).
            try:
                conn.recv(1024)
            except OSError:
                pass
            conn.close()
            srv.close()

        t = threading.Thread(target=server, daemon=True)
        t.start()
        ready.wait(timeout=3)

        sock = socket.create_connection(('127.0.0.1', result[0]), timeout=3)
        try:
            from retrobridge.transport import _telnet_negotiate
            data = _telnet_negotiate(sock, timeout=1)
            assert data == payload
        finally:
            sock.close()
            t.join(timeout=2)


class TestUnknownTransport:
    def test_unknown_transport_raises(self):
        port = MockPort(transport='bluetooth')
        with pytest.raises(ValueError, match='Unknown transport'):
            open_transport(port)


class TestOpenSerial:
    def test_serial_uses_device_path(self, monkeypatch):
        from serial import Serial
        import retrobridge.transport as tmod
        calls = []

        def fake_serial(**kwargs):
            calls.append(kwargs)
            m = __import__('unittest.mock', fromlist=['MagicMock'])
            ser = m.MagicMock()
            ser.is_open = True
            ser.baudrate = kwargs.get('baudrate', 9600)
            return ser

        monkeypatch.setattr(tmod, 'Serial', fake_serial)
        port = MockPort(transport='serial', dev_path='/dev/ttyUSB0',
                        baud=9600, parity='N', flow_control='none')
        ser = open_transport(port)
        assert ser.is_open
        assert ser.baudrate == 9600
        assert len(calls) == 1
        assert calls[0]['port'] == '/dev/ttyUSB0'
        ser.close()
