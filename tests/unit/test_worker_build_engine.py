"""Tests for the worker's engine setup (review #25): production SQLite
pragmas must apply even when FLASK_ENV is unset."""
import worker
from retrobridge import sqlite_provision


def test_build_engine_applies_pragmas_regardless_of_env(tmp_path, monkeypatch):
    captured = {}

    def fake_configure(engine, pragma_config):
        captured['config'] = pragma_config

    monkeypatch.setattr(sqlite_provision, 'configure_sqlite_engine',
                        fake_configure)
    monkeypatch.setattr(worker.config, 'get_database_uri',
                        lambda: f'sqlite:///{tmp_path}/worker.db')
    monkeypatch.delenv('FLASK_ENV', raising=False)

    engine = worker.build_engine()
    try:
        assert captured.get('config') is not None
        pragmas = captured['config']['SQLITE_PRAGMAS']
        assert pragmas['journal_mode'] == 'WAL'
        assert pragmas['busy_timeout'] == 5000
    finally:
        engine.dispose()
