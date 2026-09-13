"""Tests for TCP/telnet socket EOF and write-failure surfacing (#13).

A dropped network bridge must raise SerialException so the terminal reader
and xmodem can tear the session down instead of hanging until idle timeout.
"""
import socket

import pytest
from serial import SerialException

from retrobridge.transport import _SocketWrapper


@pytest.fixture
def pair():
    a, b = socket.socketpair()
    yield a, b
    for s in (a, b):
        try:
            s.close()
        except OSError:
            pass


def test_in_waiting_returns_zero_when_open_with_no_data(pair):
    a, _ = pair
    w = _SocketWrapper(a)
    assert w.in_waiting == 0


def test_in_waiting_raises_after_peer_closes(pair):
    a, b = pair
    w = _SocketWrapper(a)
    b.close()
    with pytest.raises(SerialException):
        _ = w.in_waiting


def test_read_drains_buffered_data_then_raises_on_eof(pair):
    a, b = pair
    w = _SocketWrapper(a)
    b.sendall(b'hello')
    b.close()
    assert w.read(100) == b'hello'
    with pytest.raises(SerialException):
        w.read(1)


def test_write_raises_after_peer_closes(pair):
    a, b = pair
    w = _SocketWrapper(a)
    b.close()
    with pytest.raises(SerialException):
        w.write(b'data')


def test_write_succeeds_when_open(pair):
    a, b = pair
    w = _SocketWrapper(a)
    assert w.write(b'xyz') == 3
    b.settimeout(1.0)
    assert b.recv(3) == b'xyz'


def test_is_open_flips_false_after_eof(pair):
    a, b = pair
    w = _SocketWrapper(a)
    assert w.is_open is True
    b.close()
    with pytest.raises(SerialException):
        _ = w.in_waiting
    assert w.is_open is False
