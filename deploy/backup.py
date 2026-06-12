#!/usr/bin/env python3
"""
Standalone SQLite backup script for RetroBridge.

Designed to be invoked from a cron job or systemd timer.
Reads configuration from environment variables (same ones
the Flask application uses), so it works without needing
a Flask app context.

Usage
-----
    # Backup with defaults (compressed, 30-day retention, max 10 files)
    python deploy/backup.py

    # Backup to a specific directory
    python deploy/backup.py --backup-dir /srv/retrobridge/backups

    # Dry run (show what would be done)
    python deploy/backup.py --dry-run

Typical cron entry (daily at 03:00):
    0 3 * * * /srv/retrobridge/venv/bin/python /srv/retrobridge/deploy/backup.py
"""

import argparse
import os
import sys

# Ensure the project root is on sys.path so we can import retrobridge.backup
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

from retrobridge.backup import backup_database, prune_backups, list_backups


def _default_db_uri():
    env = os.environ.get('FLASK_ENV', 'development')
    basedir = _project_root
    if env == 'production':
        return os.environ.get(
            'DATABASE_URL',
            f'sqlite:///{os.path.join(basedir, "instance", "retrobridge.db")}',
        )
    return os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{os.path.join(basedir, "instance", "retrobridge_dev.db")}',
    )


def main():
    parser = argparse.ArgumentParser(
        description='RetroBridge database backup script.',
    )
    parser.add_argument(
        '--db-uri',
        default=None,
        help='SQLite URI (default: from DATABASE_URL env or instance path)',
    )
    parser.add_argument(
        '--backup-dir',
        default=None,
        help='Backup destination directory (default: backups/ under project root)',
    )
    parser.add_argument(
        '--no-compress',
        action='store_true',
        help='Skip gzip compression',
    )
    parser.add_argument(
        '--retention-days',
        type=int,
        default=None,
        help='Max backup age in days (default: 30, 0 to disable)',
    )
    parser.add_argument(
        '--retention-count',
        type=int,
        default=None,
        help='Max backup files to keep (default: 10, 0 to disable)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without writing anything',
    )
    parser.add_argument(
        '--label',
        default='cron',
        help='Label embedded in the backup filename (default: "cron")',
    )
    args = parser.parse_args()

    db_uri = args.db_uri or _default_db_uri()
    backup_dir = args.backup_dir or os.path.join(_project_root, 'backups')
    retention_days = args.retention_days if args.retention_days is not None else 30
    retention_count = args.retention_count if args.retention_count is not None else 10

    if args.dry_run:
        print(f'[DRY RUN] Would backup: {db_uri}')
        print(f'[DRY RUN] Backup dir:  {backup_dir}')
        print(f'[DRY RUN] Compress:    {not args.no_compress}')
        print(f'[DRY RUN] Retention:   {retention_days} days, {retention_count} files max')
        existing = list_backups(backup_dir)
        if existing:
            print(f'[DRY RUN] Existing backups: {len(existing)}')
            for b in existing:
                print(f'  {b["filename"]}  ({b["size_bytes"]} bytes)')
        return 0

    os.makedirs(backup_dir, exist_ok=True)

    try:
        path = backup_database(
            db_uri,
            backup_dir,
            compress=not args.no_compress,
            label=args.label,
        )
        size = os.path.getsize(path)
        print(f'Backup created: {path} ({size} bytes)')
    except FileNotFoundError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1
    except Exception as e:
        print(f'ERROR: Backup failed: {e}', file=sys.stderr)
        return 1

    try:
        removed = prune_backups(backup_dir, retention_days, retention_count)
        for r in removed:
            print(f'Pruned old backup: {os.path.basename(r)}')
    except Exception as e:
        print(f'WARNING: Pruning failed: {e}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
