"""Unit tests for worker command/newline override helpers."""
import pytest

from worker import _apply_newline, _resolve_cmds, _resolve_newline_mode


class FakeJob:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakePort:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_resolve_newline_mode_prefers_job_override():
    job = FakeJob(override_newline_mode='lf')
    port = FakePort(newline_mode='cr')
    assert _resolve_newline_mode(job, port) == 'lf'


def test_resolve_newline_mode_falls_back_to_port():
    job = FakeJob(override_newline_mode=None)
    port = FakePort(newline_mode='cr')
    assert _resolve_newline_mode(job, port) == 'cr'


def test_resolve_newline_mode_defaults_to_crlf():
    job = FakeJob(override_newline_mode=None)
    port = FakePort(newline_mode=None)
    assert _resolve_newline_mode(job, port) == 'crlf'


def test_resolve_cmds_uses_job_override():
    job = FakeJob(override_pre_transfer_cmds='["OVERRIDE"]',
                  override_post_transfer_cmds=None)
    port = FakePort(pre_transfer_cmds='["PORT"]')
    assert _resolve_cmds(job, port, 'pre') == ['OVERRIDE']


def test_resolve_cmds_falls_back_to_port():
    job = FakeJob(override_pre_transfer_cmds=None,
                  override_post_transfer_cmds=None)
    port = FakePort(pre_transfer_cmds='["PORT"]')
    assert _resolve_cmds(job, port, 'pre') == ['PORT']


def test_resolve_cmds_returns_empty_when_missing():
    job = FakeJob(override_pre_transfer_cmds=None)
    port = FakePort(pre_transfer_cmds=None)
    assert _resolve_cmds(job, port, 'pre') == []


def test_resolve_cmds_handles_plain_string():
    job = FakeJob(override_pre_transfer_cmds='PLAIN')
    port = FakePort(pre_transfer_cmds=None)
    assert _resolve_cmds(job, port, 'pre') == ['PLAIN']


def test_resolve_cmds_handles_post_override():
    job = FakeJob(override_post_transfer_cmds='["POST"]')
    port = FakePort(post_transfer_cmds='["PORT POST"]')
    assert _resolve_cmds(job, port, 'post') == ['POST']


def test_apply_newline_appends_configured_ending():
    assert _apply_newline('CMD', 'lf') == 'CMD\n'
    assert _apply_newline('CMD', 'cr') == 'CMD\r'
    assert _apply_newline('CMD', 'crlf') == 'CMD\r\n'


def test_apply_newline_preserves_existing_endings():
    assert _apply_newline('CMD\r', 'lf') == 'CMD\r'
    assert _apply_newline('CMD\n', 'cr') == 'CMD\n'
    assert _apply_newline('CMD\r\n', 'cr') == 'CMD\r\n'


def test_apply_newline_defaults_to_crlf_for_unknown_mode():
    assert _apply_newline('CMD', 'unknown') == 'CMD\r\n'
