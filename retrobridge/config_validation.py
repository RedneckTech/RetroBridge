"""Production config validation — runs once at startup in production mode.

Checks are divided into:

- **Static** checks performed without I/O (type, range, sanity).
- **Dynamic** checks that touch the filesystem or database (production-only).
"""

import logging
import os
import os.path

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

WARN_AT_MINS = {
    'MAX_CONTENT_LENGTH': 1 * 1024 * 1024,
}


def validate_config(app):
    """Run all static config checks.  Dies on fatal misconfiguration."""

    errors = []
    warnings = []

    cfg = app.config

    _check_retention('BACKUP_RETENTION_DAYS', cfg, errors)
    _check_retention('BACKUP_RETENTION_COUNT', cfg, errors)

    max_bytes = cfg.get('MAX_CONTENT_LENGTH', 0)
    min_bytes = WARN_AT_MINS['MAX_CONTENT_LENGTH']
    if max_bytes and max_bytes < min_bytes:
        warnings.append(
            f'MAX_CONTENT_LENGTH={max_bytes} is less than {min_bytes} '
            '(1 MiB). Large uploads will be rejected.'
        )

    backup_dir = cfg.get('BACKUP_DIR', '')
    if backup_dir and not os.access(backup_dir, os.W_OK):
        errors.append(f'BACKUP_DIR {backup_dir!r} is not writable.')

    if errors:
        for msg in errors:
            logger.error('Config error: %s', msg)
        raise RuntimeError(
            f'{len(errors)} configuration error(s) detected — aborting startup.\n'
            + '\n'.join(errors)
        )

    for msg in warnings:
        logger.warning('Config warning: %s', msg)


def validate_db(app):
    """Verify the database is reachable (production-only liveness check)."""
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not uri:
        raise RuntimeError('SQLALCHEMY_DATABASE_URI is not configured.')

    engine = create_engine(uri)
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
    except Exception as exc:
        raise RuntimeError(
            f'Cannot connect to database at {uri!r}: {exc}'
        ) from exc
    finally:
        engine.dispose()


def _check_retention(key, cfg, errors):
    val = cfg.get(key)
    if val is not None and (not isinstance(val, int) or val <= 0):
        errors.append(f'{key}={val!r} must be a positive integer.')
