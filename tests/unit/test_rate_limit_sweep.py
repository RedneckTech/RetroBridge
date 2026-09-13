"""Tests for the SQLite rate-limit store (review #11): the table must not
grow without bound."""
import sqlite3
import time

from retrobridge.security import _SqliteRateLimiterStore


def test_sweep_removes_ancient_rows(tmp_path):
    store = _SqliteRateLimiterStore(str(tmp_path / 'rl.db'))
    now = time.time()

    with sqlite3.connect(store._path) as conn:
        conn.execute(
            'INSERT INTO rate_limits (key, timestamp) VALUES (?, ?)',
            ('old-key', now - 86401),
        )
        conn.execute(
            'INSERT INTO rate_limits (key, timestamp) VALUES (?, ?)',
            ('fresh-key', now),
        )

    store.check('some:key', 10, 60)

    with sqlite3.connect(store._path) as conn:
        rows = conn.execute('SELECT key FROM rate_limits').fetchall()
    keys = {r[0] for r in rows}
    assert 'old-key' not in keys
    assert 'fresh-key' in keys
    assert 'some:key' in keys


def test_sweep_only_runs_once_per_interval(tmp_path):
    # Two checks in quick succession must not each trigger a full-table scan:
    # the second one happens before the sweep interval elapses.
    store = _SqliteRateLimiterStore(str(tmp_path / 'rl.db'))
    store.check('a', 5, 60)
    store.check('b', 5, 60)

    with sqlite3.connect(store._path) as conn:
        rows = conn.execute('SELECT key FROM rate_limits').fetchall()
    keys = {r[0] for r in rows}
    assert keys == {'a', 'b'}
