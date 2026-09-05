"""Unit tests for the rate limiter and its shared SQLite store."""
import os
import tempfile
import time

import pytest

from retrobridge.security import (
    _MemoryRateLimiterStore,
    _SqliteRateLimiterStore,
    _client_ip,
    _is_trusted_proxy,
)


class TestMemoryRateLimiterStore:
    def test_allows_requests_under_limit(self):
        store = _MemoryRateLimiterStore()
        assert store.check('key', 3, 60) is False
        assert store.check('key', 3, 60) is False
        assert store.check('key', 3, 60) is False

    def test_blocks_at_limit(self):
        store = _MemoryRateLimiterStore()
        store.check('key', 2, 60)
        store.check('key', 2, 60)
        assert store.check('key', 2, 60) is True

    def test_sliding_window_expires(self):
        store = _MemoryRateLimiterStore()
        store.check('key', 1, 0.05)
        assert store.check('key', 1, 0.05) is True
        time.sleep(0.06)
        assert store.check('key', 1, 0.05) is False


class TestSqliteRateLimiterStore:
    @pytest.fixture
    def store(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        store = _SqliteRateLimiterStore(path)
        yield store
        os.unlink(path)

    def test_allows_requests_under_limit(self, store):
        assert store.check('key', 3, 60) is False
        assert store.check('key', 3, 60) is False
        assert store.check('key', 3, 60) is False

    def test_blocks_at_limit(self, store):
        store.check('key', 2, 60)
        store.check('key', 2, 60)
        assert store.check('key', 2, 60) is True

    def test_sliding_window_expires(self, store):
        store.check('key', 1, 0.05)
        assert store.check('key', 1, 0.05) is True
        time.sleep(0.06)
        assert store.check('key', 1, 0.05) is False

    def test_keys_are_isolated(self, store):
        store.check('a', 1, 60)
        assert store.check('a', 1, 60) is True
        assert store.check('b', 1, 60) is False


class TestClientIp:
    def test_uses_remote_addr_by_default(self, app):
        from flask import Request
        from werkzeug.test import EnvironBuilder
        builder = EnvironBuilder(environ_base={'REMOTE_ADDR': '192.168.1.5'})
        req = Request(builder.get_environ())
        assert _client_ip(req) == '192.168.1.5'

    def test_takes_rightmost_untrusted_with_trusted_proxy(self, app):
        from flask import Request
        from werkzeug.test import EnvironBuilder
        app.config['TRUSTED_PROXIES'] = ['10.0.0.0/8']
        builder = EnvironBuilder(
            environ_base={'REMOTE_ADDR': '10.0.0.1'},
            headers={'X-Forwarded-For': '1.2.3.4, 5.6.7.8, 10.0.0.2'},
        )
        req = Request(builder.get_environ())
        req.app = app
        assert _client_ip(req) == '5.6.7.8'

    def test_ignores_x_forwarded_for_without_trusted_proxy(self, app):
        from flask import Request
        from werkzeug.test import EnvironBuilder
        builder = EnvironBuilder(
            environ_base={'REMOTE_ADDR': '9.9.9.9'},
            headers={'X-Forwarded-For': '1.2.3.4'},
        )
        req = Request(builder.get_environ())
        req.app = app
        assert _client_ip(req) == '9.9.9.9'

    def test_uses_rightmost_untrusted_x_forwarded_for(self, app):
        from flask import Request
        from werkzeug.test import EnvironBuilder
        app.config['TRUSTED_PROXIES'] = ['10.0.0.0/8']
        builder = EnvironBuilder(
            environ_base={'REMOTE_ADDR': '10.0.0.1'},
            headers={'X-Forwarded-For': '1.2.3.4, 10.0.0.2, 5.6.7.8'},
        )
        req = Request(builder.get_environ())
        req.app = app
        assert _client_ip(req) == '5.6.7.8'


class TestIsTrustedProxy:
    def test_exact_match(self):
        assert _is_trusted_proxy('10.0.0.1', ['10.0.0.1']) is True

    def test_cidr_match(self):
        assert _is_trusted_proxy('10.0.5.1', ['10.0.0.0/8']) is True

    def test_untrusted(self):
        assert _is_trusted_proxy('1.2.3.4', ['10.0.0.0/8']) is False

    def test_empty_lists(self):
        assert _is_trusted_proxy('10.0.0.1', []) is False
        assert _is_trusted_proxy(None, ['10.0.0.1']) is False
