"""Tests for backup/restore utilities."""
import gzip
import os
import sqlite3
import tempfile

from retrobridge.backup import restore_database


def test_restore_strips_gz_suffix_correctly():
    """.rstrip('.gz') would mangle paths like 'dbz.gz'; removesuffix is safe."""
    with tempfile.TemporaryDirectory() as tmp:
        db_uri = f'sqlite:///{tmp}/target.db'
        backup_path = os.path.join(tmp, 'dbz.gz')

        # Create a source DB and gzip it.
        source = os.path.join(tmp, 'dbz')
        conn = sqlite3.connect(source)
        conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY)')
        conn.execute('INSERT INTO test VALUES (42)')
        conn.commit()
        conn.close()
        with open(source, 'rb') as f_in, gzip.open(backup_path, 'wb') as f_out:
            f_out.write(f_in.read())

        restored = restore_database(backup_path, db_uri)

        assert os.path.exists(restored)
        conn = sqlite3.connect(restored)
        row = conn.execute('SELECT id FROM test').fetchone()
        assert row[0] == 42
        conn.close()
