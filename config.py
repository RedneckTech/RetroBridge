import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


def get_database_uri():
    """Return the normalized database URI for all components.

    Reads DATABASE_URL from the environment.  SQLite relative paths
    are normalized to absolute paths anchored at the project root.

    In production, a missing DATABASE_URL raises RuntimeError.
    In development, falls back to the dev database.
    """
    env = os.environ.get('FLASK_ENV', 'development')
    db_url = os.environ.get('DATABASE_URL')

    if db_url:
        return _normalize_sqlite_path(db_url)

    if env == 'production':
        raise RuntimeError(
            'DATABASE_URL must be set in production. '
            'No implicit database path is allowed.'
        )

    return f'sqlite:///{os.path.join(basedir, "instance", "retrobridge_dev.db")}'


def _normalize_sqlite_path(uri):
    """If *uri* is a sqlite:/// scheme with a relative path, make it absolute."""
    if uri.startswith('sqlite:///'):
        path = uri[10:]
        if not os.path.isabs(path):
            return f'sqlite:///{os.path.join(basedir, path)}'
    return uri


class BaseConfig:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REMEMBER_COOKIE_DURATION = timedelta(hours=24)
    WTF_CSRF_ENABLED = True
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB default

    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SQLALCHEMY_ENGINE_POOLCLASS = 'NullPool'
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {
            'timeout': 10,
        },
    }

    # Extra origins (comma-separated) allowed to open the /terminal
    # WebSocket.  Same-origin browser connections are always allowed;
    # foreign Origins are rejected unless listed here.
    SOCKETIO_ALLOWED_ORIGINS = [
        o.strip()
        for o in os.environ.get('SOCKETIO_ALLOWED_ORIGINS', '').split(',')
        if o.strip()
    ]

    # Optional token required by GET /ready (health probes).  Empty = open.
    HEALTH_TOKEN = os.environ.get('HEALTH_TOKEN', '')

    UPLOAD_DIR = os.path.join(basedir, 'uploads')
    OUTPUT_DIR = os.path.join(basedir, 'outputs')
    SESSION_LOG_DIR = os.path.join(basedir, 'session_logs')
    LOG_DIR = os.path.join(basedir, 'logs')
    BACKUP_DIR = os.path.join(basedir, 'backups')
    BACKUP_RETENTION_DAYS = int(os.environ.get('BACKUP_RETENTION_DAYS', '30'))
    BACKUP_RETENTION_COUNT = int(os.environ.get('BACKUP_RETENTION_COUNT', '10'))

    SECURITY_HEADERS = {
        'X-Frame-Options': 'DENY',
        'X-Content-Type-Options': 'nosniff',
        'X-XSS-Protection': '0',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
    }
    RATE_LIMIT_ENABLED = False
    RATE_LIMITS = {
        'default': (0, 60),
    }

    # SSE (job events) tuning. Each open stream holds a gthread worker
    # thread for its lifetime; the poll interval keeps those idle cycles
    # cheap.  MAX_LIFETIME bounds how long a stream may stay open (0 =
    # unlimited) so a queued job cannot pin a thread forever.
    JOB_EVENTS_POLL_INTERVAL = float(os.environ.get('JOB_EVENTS_POLL_INTERVAL', '1.0'))
    JOB_EVENTS_MAX_LIFETIME = float(os.environ.get('JOB_EVENTS_MAX_LIFETIME', '3600')) or None


class DevConfig(BaseConfig):
    DEBUG = True
    TESTING = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_DATABASE_URI = get_database_uri()

    SECURITY_HEADERS = {
        'X-Frame-Options': 'DENY',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
    }
    RATE_LIMIT_ENABLED = False
    RATE_LIMIT_STORE = 'memory'
    TRUSTED_PROXIES = []


class TestConfig(BaseConfig):
    DEBUG = False
    TESTING = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_POOLCLASS = 'StaticPool'
    WTF_CSRF_ENABLED = False
    RATE_LIMIT_STORE = 'memory'
    TRUSTED_PROXIES = []


class ProdConfig(BaseConfig):
    DEBUG = False
    TESTING = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_DATABASE_URI = get_database_uri()
    SQLITE_PRAGMAS = {
        'journal_mode': 'WAL',
        'synchronous': 'NORMAL',
        'busy_timeout': 5000,
        'mmap_size': 268435456,
        'cache_size': -64000,
        'foreign_keys': 'ON',
        'temp_store': 'MEMORY',
    }

    SECURITY_HEADERS = {
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        'X-Frame-Options': 'DENY',
        'X-Content-Type-Options': 'nosniff',
        'X-XSS-Protection': '0',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
        'Content-Security-Policy': (
            "default-src 'self'; "
            "script-src 'self' cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
            "img-src 'self' data: https://www.gravatar.com; "
            "font-src 'self' cdn.jsdelivr.net; "
            "connect-src 'self' wss:; "
            "frame-ancestors 'none'"
        ),
    }
    RATE_LIMIT_ENABLED = True
    RATE_LIMIT_STORE = 'sqlite'
    TRUSTED_PROXIES = []
    RATE_LIMITS = {
        'health': (60, 60),
        'auth': (10, 60),
        'api': (120, 60),
        'admin': (60, 60),
        'terminal': (30, 60),
        'jobs': (30, 60),
        'default': (60, 60),
    }

    @classmethod
    def validate(cls):
        key = cls.SECRET_KEY
        if not key or key == 'change-me-in-production':
            raise RuntimeError(
                'SECRET_KEY must be set to a unique, unpredictable value '
                'via the SECRET_KEY environment variable in production.'
            )
