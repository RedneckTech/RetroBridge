"""
SQLite backup and restore utilities.

Uses the sqlite3.backup() API for safe online backups of WAL-mode
databases, supporting both compressed (.gz) and raw backup files
with time-stamped naming and configurable retention pruning.
"""

import gzip
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


BACKUP_FILENAME_PATTERN = re.compile(r'retrobridge_.*\.db(\.gz)?$')


def _db_path(uri):
    if uri.startswith('sqlite:///'):
        path = uri[len('sqlite:///'):]
        return os.path.abspath(path)
    if uri.startswith('sqlite://'):
        path = uri[len('sqlite://'):]
        return os.path.abspath(path)
    return os.path.abspath(uri)


def backup_database(db_uri, backup_dir, compress=True, label=None):
    """Create an online backup of the SQLite database.

    Uses the sqlite3.backup() API which is safe to run against a
    live WAL-mode database — readers and writers are not blocked.

    Parameters
    ----------
    db_uri : str
        SQLAlchemy database URI (``sqlite:///path``).
    backup_dir : str
        Directory where the backup file will be written.
    compress : bool
        When True the raw backup is gzip-compressed and the
        uncompressed file is removed (default True).
    label : str or None
        Optional short label embedded in the filename.

    Returns
    -------
    str
        Absolute path to the created backup file.

    Raises
    ------
    FileNotFoundError
        If the source database file does not exist.
    """
    db_path = _db_path(db_uri)
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    stem = f"retrobridge_{label + '_' if label else ''}{ts}"
    raw_path = os.path.join(backup_dir, f"{stem}.db")

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(raw_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    result = raw_path
    if compress:
        gz_path = raw_path + '.gz'
        with open(raw_path, 'rb') as f_in:
            with gzip.open(gz_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(raw_path)
        result = gz_path

    return result


def restore_database(backup_path, db_uri):
    """Restore a SQLite database from a backup file.

    The target database is overwritten.  Compressed (``.gz``) files
    are transparently decompressed to a temporary file during restore.

    Parameters
    ----------
    backup_path : str
        Path to the backup file (``.db`` or ``.db.gz``).
    db_uri : str
        Target SQLAlchemy database URI.

    Returns
    -------
    str
        Absolute path to the restored database file.

    Raises
    ------
    FileNotFoundError
        If the backup file does not exist.
    """
    if not os.path.isfile(backup_path):
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    db_path = _db_path(db_uri)
    os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)

    source_path = backup_path
    temp_path = None

    if backup_path.endswith('.gz'):
        temp_path = backup_path.rstrip('.gz') + '.restore_temp'
        with gzip.open(backup_path, 'rb') as f_in:
            with open(temp_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        source_path = temp_path

    try:
        src = sqlite3.connect(source_path)
        dst = sqlite3.connect(db_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    return db_path


def list_backups(backup_dir):
    """Return sorted list of backup files with metadata.

    Results are ordered newest-first.
    """
    if not os.path.isdir(backup_dir):
        return []

    entries = []
    for name in sorted(os.listdir(backup_dir), reverse=True):
        if not BACKUP_FILENAME_PATTERN.match(name):
            continue
        path = os.path.join(backup_dir, name)
        stat = os.stat(path)
        entries.append({
            'filename': name,
            'path': path,
            'size_bytes': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        })

    entries.sort(key=lambda e: e['modified'], reverse=True)
    return entries


def prune_backups(backup_dir, retention_days=30, retention_count=10):
    """Remove old backups outside the retention policy.

    Two rules are applied in order:
    1. Any backup older than *retention_days* is removed.
    2. If more than *retention_count* backups remain, the oldest
       beyond that count are removed.

    Parameters
    ----------
    backup_dir : str
        Directory containing backup files.
    retention_days : int
        Maximum age in days (0 disables age-based pruning).
    retention_count : int
        Maximum number of backups to keep (0 disables count-based
        pruning).

    Returns
    -------
    list[str]
        Paths of removed backup files.
    """
    removed = []

    if not os.path.isdir(backup_dir):
        return removed

    now = time.time()

    backups = []
    for name in os.listdir(backup_dir):
        if not BACKUP_FILENAME_PATTERN.match(name):
            continue
        path = os.path.join(backup_dir, name)
        backups.append((os.path.getmtime(path), path))

    backups.sort(key=lambda x: x[0], reverse=True)

    if retention_days > 0:
        cutoff = now - (retention_days * 86400)
        kept = []
        for mtime, path in backups:
            if mtime < cutoff:
                os.remove(path)
                removed.append(path)
            else:
                kept.append((mtime, path))
        backups = kept

    if retention_count > 0 and len(backups) > retention_count:
        for _, path in backups[retention_count:]:
            os.remove(path)
            removed.append(path)

    return removed
