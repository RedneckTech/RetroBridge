"""
SQLite engine provisioning — WAL mode, performance pragmas, and connection
tuning shared by the Flask app and standalone worker.

Usage in app factory::

    from retrobridge.sqlite_provision import configure_sqlite_engine
    engine = create_engine(...)
    configure_sqlite_engine(engine, app.config)

Usage in worker::

    from retrobridge.sqlite_provision import configure_sqlite_engine
    engine = build_engine()
    configure_sqlite_engine(engine)
"""

import logging

from sqlalchemy import event

logger = logging.getLogger(__name__)

DEFAULT_PRAGMAS = {
    'journal_mode': 'WAL',
    'synchronous': 'NORMAL',
    'busy_timeout': 5000,
    'mmap_size': 268435456,
    'cache_size': -64000,
    'foreign_keys': 'ON',
    'temp_store': 'MEMORY',
}

PRAGMA_VALUES = {
    'journal_mode': ('DELETE', 'TRUNCATE', 'PERSIST', 'MEMORY', 'WAL', 'OFF'),
    'synchronous': ('OFF', 'NORMAL', 'FULL', 'EXTRA'),
    'temp_store': ('DEFAULT', 'FILE', 'MEMORY'),
}


def _validate_pragma(key, value):
    allowed = PRAGMA_VALUES.get(key)
    if allowed and str(value).upper() not in allowed:
        raise ValueError(
            f"Invalid SQLITE_PRAGMAS.{key}={value!r}. "
            f"Allowed: {', '.join(allowed)}"
        )


def configure_sqlite_engine(engine, config=None):
    """Register a ``PoolEvents.connect`` listener that runs SQLite pragmas
    on every new connection returned by the pool.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
        The engine to configure.
    config : dict or None
        Flask app config dictionary.  If present, the key
        ``SQLITE_PRAGMAS`` is read as a dict of pragma → value
        overrides.  Omitted or ``None`` entries fall back to
        ``DEFAULT_PRAGMAS``.
    """
    pragmas = dict(DEFAULT_PRAGMAS)

    user_pragmas = (config or {}).get('SQLITE_PRAGMAS', {}) or {}
    for key, value in user_pragmas.items():
        if value is not None:
            _validate_pragma(key, value)
            pragmas[key] = value

    @event.listens_for(engine, 'connect')
    def _set_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        for key, value in pragmas.items():
            try:
                cursor.execute(f'PRAGMA {key}={value}')
            except Exception:
                logger.debug(
                    'PRAGMA %s=%s not supported on this connection',
                    key, value,
                )
        cursor.close()
