"""Tests for PTY simulation module."""
import os
import select
import time

import pytest

from retrobridge.simulation import create_terminal_simulation, create_job_simulation


def _read_all(fd, timeout=2.0):
    """Read all available data from fd with a total timeout."""
    data = b''
    deadline = time.time() + timeout
    while time.time() < deadline:
        rfds, _, _ = select.select([fd], [], [], 0.3)
        if rfds:
            try:
                chunk = os.read(fd, 4096)
                if chunk:
                    data += chunk
                else:
                    break
            except OSError:
                break
    return data.decode(errors='replace')


class TestTerminalSimulation:
    def test_creates_pty_and_thread(self):
        sim = create_terminal_simulation('centurion')
        try:
            assert sim['slave_name'].startswith('/dev/pts/')
            assert sim['master_fd'] > 0
            # Open slave so the simulation thread doesn't block on full buffer
            slave = open(sim['slave_name'], 'r+b', buffering=0)
            time.sleep(1)
            assert sim['thread'].is_alive()
            slave.close()
        finally:
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)

    def test_login_sequence(self):
        sim = create_terminal_simulation('centurion')
        try:
            slave = open(sim['slave_name'], 'r+b', buffering=0)
            try:
                output = _read_all(slave.fileno(), timeout=3)
                assert 'CENTURION' in output or 'USERNAME' in output
            finally:
                slave.close()
        finally:
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)

    def test_pdp11_simulation(self):
        sim = create_terminal_simulation('pdp11')
        try:
            slave = open(sim['slave_name'], 'r+b', buffering=0)
            try:
                output = _read_all(slave.fileno(), timeout=3)
                assert 'PDP-11' in output or 'RSX' in output or 'USERNAME' in output
            finally:
                slave.close()
        finally:
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)

    def test_unknown_device_falls_back_to_centurion(self):
        sim = create_terminal_simulation('nonexistent')
        try:
            slave = open(sim['slave_name'], 'r+b', buffering=0)
            try:
                output = _read_all(slave.fileno(), timeout=3)
                assert len(output) > 0
            finally:
                slave.close()
        finally:
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)


class TestJobSimulation:
    def test_creates_pty_and_thread(self):
        sim = create_job_simulation('centurion')
        try:
            assert sim['slave_name'].startswith('/dev/pts/')
            assert sim['master_fd'] > 0
            assert sim['thread'].is_alive()
        finally:
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)

    def test_boot_sequence(self):
        sim = create_job_simulation('centurion')
        try:
            slave = open(sim['slave_name'], 'r+b', buffering=0)
            try:
                output = _read_all(slave.fileno(), timeout=3)
                assert 'CENTURION' in output or 'BOOT' in output or 'READY' in output
            finally:
                slave.close()
        finally:
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)

    def test_stop_event_kills_thread(self):
        sim = create_job_simulation('centurion')
        assert sim['thread'].is_alive()
        sim['stop_event'].set()
        sim['thread'].join(timeout=3)
        assert not sim['thread'].is_alive()
