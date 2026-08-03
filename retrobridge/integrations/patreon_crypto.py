import logging
import os

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


def _load_key():
    key = os.environ.get('PATREON_ENCRYPTION_KEY', '').strip()
    if key:
        return key.encode('utf-8')

    basedir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..'))
    key_file = os.path.join(basedir, 'instance', 'patreon.key')

    if os.path.exists(key_file):
        with open(key_file, 'rb') as f:
            return f.read().strip()

    new_key = Fernet.generate_key()
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    with open(key_file, 'wb') as f:
        f.write(new_key)
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
