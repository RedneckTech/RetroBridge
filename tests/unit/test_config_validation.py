"""Unit tests for production config validation."""
import os
import stat

import pytest

from retrobridge.config_validation import validate_config


class FakeApp:
    """Minimal app stand-in for validate_config."""

    def __init__(self, config):
        self.config = config


class FakeConfig(dict):
    """Minimal dict-like config for validate_config."""

    def get(self, key, default=None):
        return super().get(key, default)


def _valid_app(overrides=None):
    cfg = FakeConfig(
        BACKUP_RETENTION_DAYS=30,
        BACKUP_RETENTION_COUNT=10,
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        BACKUP_DIR=None,
    )
    if overrides:
        cfg.update(overrides)
    return FakeApp(cfg)


def test_no_backup_dir_is_ok():
    app = _valid_app({'BACKUP_DIR': None})
    validate_config(app)  # should not raise


def test_missing_backup_dir_is_created(tmp_path):
    backup_dir = tmp_path / 'fresh_backups'
    assert not backup_dir.exists()

    app = _valid_app({'BACKUP_DIR': str(backup_dir)})
    validate_config(app)

    assert backup_dir.exists()
    assert os.access(str(backup_dir), os.W_OK)


def test_existing_writable_backup_dir_is_ok(tmp_path):
    backup_dir = tmp_path / 'existing_backups'
    backup_dir.mkdir()

    app = _valid_app({'BACKUP_DIR': str(backup_dir)})
    validate_config(app)  # should not raise


def test_unwritable_backup_dir_raises(tmp_path):
    backup_dir = tmp_path / 'readonly_backups'
    backup_dir.mkdir()
    # Remove write permission for the owner
    os.chmod(str(backup_dir), stat.S_IRUSR | stat.S_IXUSR)

    try:
        app = _valid_app({'BACKUP_DIR': str(backup_dir)})
        with pytest.raises(RuntimeError, match='BACKUP_DIR.*not writable'):
            validate_config(app)
    finally:
        # Restore write permission so pytest can clean up the tmpdir
        os.chmod(str(backup_dir), stat.S_IRWXU)


def test_non_positive_retention_days_raises():
    app = _valid_app({'BACKUP_RETENTION_DAYS': 0})
    with pytest.raises(RuntimeError, match='BACKUP_RETENTION_DAYS'):
        validate_config(app)


def test_non_positive_retention_count_raises():
    app = _valid_app({'BACKUP_RETENTION_COUNT': -1})
    with pytest.raises(RuntimeError, match='BACKUP_RETENTION_COUNT'):
        validate_config(app)


def test_small_max_content_length_warns_but_does_not_raise(caplog):
    app = _valid_app({'MAX_CONTENT_LENGTH': 1024})
    with caplog.at_level('WARNING'):
        validate_config(app)
    assert 'MAX_CONTENT_LENGTH' in caplog.text
