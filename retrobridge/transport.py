"""Serial transport abstraction — opens connections for device ports.

Supports five transport types:
  - ``serial``  — local RS-232 device (``/dev/ttyUSB0``)
  - ``pty``     — pseudo-terminal (``/tmp/sim_pty``)
  - ``tcp``     — raw TCP socket (``host:port``)
  - ``telnet``  — telnet with minimal negotiation (``host:port``)
  - ``rfc2217`` — RFC 2217 remote serial port (``host:port``)

Usage::

    from retrobridge.transport import open_transport
    ser = open_transport(port)   # port is a DevicePort instance
"""

import logging
import select
import socket
import time

from serial import Serial, SerialException, serial_for_url

logger = logging.getLogger(__name__)

BAUD_TRANSPORTS = {'serial', 'pty', 'rfc2217'}


def open_transport(port):
    """Open a connection for *port* and return a serial-like object.

    The returned object supports the standard ``pyserial.Serial``
    interface (``read``, ``write``, ``in_waiting``, ``is_open``,
    ``close``, ``fd``).

    Parameters
    ----------
    port : DevicePort
        The port configuration to connect to.

    Returns
    -------
    Serial-like object
        An open connection ready for I/O.

    Raises
    ------
    SerialException
        If the connection cannot be opened.
    ValueError
        If the transport type is unknown.
    """
    transport = (port.transport or 'serial').lower()
    address = port.dev_path.strip() if port.dev_path else ''

    if transport in ('serial', 'pty'):
        return _open_serial(port)

    if transport == 'tcp':
        return _open_tcp(address)

    if transport == 'telnet':
        return _open_telnet(address)

    if transport == 'rfc2217':
        return _open_rfc2217(address)

    raise ValueError(f'Unknown transport type: {transport}')


def transport_uses_baud(port):
    return (port.transport or 'serial').lower() in BAUD_TRANSPORTS


# ── serial / pty ─────────────────────────────────────────────────────────────

def _serial_params(port):
    parity_map = {'N': 'N', 'E': 'E', 'O': 'O', 'M': 'M', 'S': 'S'}
    return {
        'port': port.dev_path,
        'baudrate': port.baud if port.baud else 9600,
        'bytesize': port.data_bits if port.data_bits else 8,
        'parity': parity_map.get(port.parity or 'N', 'N'),
        'stopbits': port.stop_bits if port.stop_bits else 1,
        'timeout': 0.1,
        'rtscts': port.flow_control == 'rtscts',
        'xonxoff': port.flow_control == 'xonxoff',
    }


def _serial_params_light(port):
    params = _serial_params(port)
    return {
        'port': params['port'],
        'baudrate': params['baudrate'],
        'bytesize': params['bytesize'],
        'parity': params['parity'],
        'stopbits': params['stopbits'],
        'timeout': 0.5,
        'rtscts': params['rtscts'],
        'xonxoff': params['xonxoff'],
    }


def _open_serial(port):
    return Serial(**_serial_params_light(port))


# ── TCP ──────────────────────────────────────────────────────────────────────

def _parse_host_port(address):
    addr = address.strip()
    if not addr:
        raise SerialException('No address provided for TCP transport')
    if ':' in addr:
        host, port_str = addr.rsplit(':', 1)
    else:
        parts = addr.split()
        if len(parts) >= 2:
            host, port_str = parts[0], parts[1]
        else:
            raise SerialException(
                f'Invalid address for TCP: {addr!r}. '
                'Use host:port format.'
            )
    try:
        port_num = int(port_str)
    except ValueError:
        raise SerialException(f'Invalid port number: {port_str!r}')
    return host.strip(), port_num


def _open_tcp(address):
    host, port = _parse_host_port(address)
    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.setblocking(False)
    except OSError as e:
        raise SerialException(f'TCP connect to {host}:{port} failed: {e}')
    return _SocketWrapper(sock, f'tcp://{host}:{port}')


# ── RFC 2217 ─────────────────────────────────────────────────────────────────

def _open_rfc2217(address):
    host, port = _parse_host_port(address)
    url = f'rfc2217://{host}:{port}'
    return serial_for_url(url, do_not_open=False)


# ── Telnet ───────────────────────────────────────────────────────────────────

IAC  = 255
WILL = 251
WONT = 252
DO   = 253
DONT = 254
SB   = 250
SE   = 240


def _telnet_negotiate(sock, timeout=2):
    """Read and reject telnet option negotiations."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r, _, _ = select.select([sock], [], [], 0.5)
        if not r:
            break
        try:
            data = sock.recv(4096)
        except (BlockingIOError, OSError):
            break
        if not data:
            break
        i = 0
        while i < len(data):
            b = data[i]
            if b == IAC:
                if i + 1 >= len(data):
                    break
                cmd = data[i + 1]
                if cmd in (WILL, WONT, DO, DONT):
                    opt = data[i + 2] if i + 2 < len(data) else 0
                    if cmd == WILL:
                        sock.sendall(bytes([IAC, DONT, opt]))
                    elif cmd == DO:
                        sock.sendall(bytes([IAC, WONT, opt]))
                    i += 3
                elif cmd == SB:
                    i += 2
                    while i < len(data):
                        if data[i] == IAC and i + 1 < len(data) and data[i + 1] == SE:
                            i += 2
                            break
                        i += 1
                else:
                    i += 2
            else:
                break


def _open_telnet(address):
    host, port = _parse_host_port(address)
    try:
        sock = socket.create_connection((host, port), timeout=5)
    except OSError as e:
        raise SerialException(f'Telnet connect to {host}:{port} failed: {e}')

    try:
        _telnet_negotiate(sock)
    except OSError:
        pass

    sock.setblocking(False)
    return _SocketWrapper(sock, f'telnet://{host}:{port}')


# ── Socket wrapper ───────────────────────────────────────────────────────────

class _SocketWrapper:
    """Minimal pyserial-like interface over a raw TCP socket."""

    def __init__(self, sock, name='<socket>'):
        self._sock = sock
        self._name = name
        self._open = True
        self._buf = b''
        self.fd = sock.fileno()
        self.is_open = True

    @property
    def in_waiting(self):
        try:
            r, _, _ = select.select([self._sock], [], [], 0)
            return 1 if r else 0
        except (OSError, ValueError, TypeError, AttributeError):
            return 0

    def read(self, size=1):
        try:
            if self._buf:
                data = self._buf[:size] if len(self._buf) >= size else self._buf
                self._buf = self._buf[len(data):]
                if len(data) >= size:
                    return data
                size -= len(data)
            else:
                data = b''
            r, _, _ = select.select([self._sock], [], [], 0.1)
            if r:
                chunk = self._sock.recv(size)
                if chunk:
                    data += chunk
            return data
        except (BlockingIOError, OSError):
            return b''

    def write(self, data):
        try:
            self._sock.sendall(data)
            return len(data)
        except OSError:
            return 0

    def close(self):
        if not self._open:
            return
        self._open = False
        self.is_open = False
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def fileno(self):
        return self._sock.fileno()

    def __repr__(self):
        return f'_SocketWrapper({self._name})'
