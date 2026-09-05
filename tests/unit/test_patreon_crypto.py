"""Tests for Patreon encryption key handling."""
import os
import stat
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from retrobridge.integrations import patreon_crypto


def test_uses_environment_variable(monkeypatch):
    key = Fernet.generate_key().decode('utf-8')
    monkeypatch.setenv('PATREON_ENCRYPTION_KEY', key)
    monkeypatch.delenv('FLASK_ENV', raising=False)

    # Force reload
    patreon_crypto._fernet = None
    fernet = patreon_crypto._get_fernet()
    assert fernet is not None

    encrypted = patreon_crypto.encrypt_token('secret-token')
    assert patreon_crypto.decrypt_token(encrypted) == 'secret-token'


def test_generated_key_file_has_restricted_permissions(tmp_path, monkeypatch):
    monkeypatch.delenv('PATREON_ENCRYPTION_KEY', raising=False)
    monkeypatch.delenv('FLASK_ENV', raising=False)

    key_file = str(tmp_path / 'patreon.key')
    with patch.object(patreon_crypto, '_fernet', None):
        key = patreon_crypto._load_key(key_file=key_file)
        patreon_crypto._get_fernet()

    assert os.path.exists(key_file)
    mode = stat.S_IMODE(os.stat(key_file).st_mode)
    assert mode == 0o600
    # The returned key should match the file contents.
    with open(key_file, 'rb') as f:
        assert f.read().strip() == key


def test_requires_key_in_production(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.delenv('PATREON_ENCRYPTION_KEY', raising=False)

    with patch.object(patreon_crypto, '_fernet', None):
        with pytest.raises(RuntimeError):
            patreon_crypto._load_key()


def test_round_trip():
    token = 'user-access-token'
    encrypted = patreon_crypto.encrypt_token(token)
    assert encrypted != token
    assert patreon_crypto.decrypt_token(encrypted) == token


def test_decrypt_none_returns_none():
    assert patreon_crypto.decrypt_token(None) is None


def test_encrypt_none_returns_none():
    assert patreon_crypto.encrypt_token(None) is None
