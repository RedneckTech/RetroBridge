import logging
import os

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


def _default_key_file():
    basedir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..'))
    return os.path.join(basedir, 'instance', 'patreon.key')


def _load_key(key_file=None):
    key = os.environ.get('PATREON_ENCRYPTION_KEY', '').strip()
    if key:
        return key.encode('utf-8')

    if os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError(
            'PATREON_ENCRYPTION_KEY must be set in production. '
            'Auto-generated keys are not safe across multiple instances '
            'or rolling deployments.'
        )

    key_file = key_file or _default_key_file()

    if os.path.exists(key_file):
        with open(key_file, 'rb') as f:
            return f.read().strip()

    new_key = Fernet.generate_key()
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    # Open with restricted permissions; os.open avoids the race between
    # create and chmod.
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(new_key)
    except Exception:
        os.close(fd)
        raise
    logger.warning(
        'Generated new Patreon encryption key at %s. '
        'Keep this file safe — losing it means losing access '
        'to all stored Patreon tokens.',
        key_file,
    )
    return new_key


_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_key())
    return _fernet


def encrypt_token(value):
    if not value:
        return None
    return _get_fernet().encrypt(value.encode('utf-8')).decode('utf-8')


def decrypt_token(value):
    if not value:
        return None
    try:
        return _get_fernet().decrypt(value.encode('utf-8')).decode('utf-8')
    except Exception:
        logger.warning('Failed to decrypt Patreon token — '
                       'encryption key may have changed')
        return None
