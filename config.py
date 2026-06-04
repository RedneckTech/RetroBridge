import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class BaseConfig:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REMEMBER_COOKIE_DURATION = timedelta(hours=24)
    WTF_CSRF_ENABLED = True
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB default
    SQLALCHEMY_ENGINE_POOLCLASS = 'NullPool'
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {
            'timeout': 10,
        },
    }

    UPLOAD_DIR = os.path.join(basedir, 'uploads')
    OUTPUT_DIR = os.path.join(basedir, 'outputs')
    SESSION_LOG_DIR = os.path.join(basedir, 'session_logs')
    LOG_DIR = os.path.join(basedir, 'logs')


class DevConfig(BaseConfig):
    DEBUG = True
    TESTING = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{os.path.join(basedir, "instance", "retrobridge_dev.db")}',
    )


class TestConfig(BaseConfig):
    DEBUG = False
    TESTING = True
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ENGINE_POOLCLASS = 'StaticPool'
    WTF_CSRF_ENABLED = False


class ProdConfig(BaseConfig):
    DEBUG = False
    TESTING = False
    SOCKETIO_ASYNC_MODE = 'eventlet'
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{os.path.join(basedir, "instance", "retrobridge.db")}',
    )
