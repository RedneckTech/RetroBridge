import os

from flask import Flask
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect

from retrobridge.models import Base

login_manager = LoginManager()
socketio = SocketIO()
csrf = CSRFProtect()


def create_app(config=None):
    app = Flask(__name__)

    if config is None:
        env = os.environ.get('FLASK_ENV', 'development')
        if env == 'production':
            app.config.from_object('config.ProdConfig')
        elif env == 'testing':
            app.config.from_object('config.TestConfig')
        else:
            app.config.from_object('config.DevConfig')
    else:
        app.config.from_object(config)

    from retrobridge.models import Base as _Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.pool import NullPool, StaticPool

    poolclass_name = app.config.get('SQLALCHEMY_ENGINE_POOLCLASS', 'NullPool')
    poolclass = {'NullPool': NullPool, 'StaticPool': StaticPool}.get(poolclass_name, NullPool)

    engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'],
                           connect_args=app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {}).get('connect_args', {}),
                           poolclass=poolclass)
    session_factory = sessionmaker(bind=engine)
    app.db_session = scoped_session(session_factory)
    app.db_engine = engine

    Base.metadata.bind = engine

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    socketio.init_app(app, async_mode=app.config.get('SOCKETIO_ASYNC_MODE', 'eventlet'))
    socketio._flask_app = app
    csrf.init_app(app)

    @app.route('/')
    def landing():
        from flask import render_template
        return render_template('landing.html')

    from retrobridge.auth.routes import auth_bp
    from retrobridge.jobs.routes import jobs_bp
    from retrobridge.api.routes import api_bp
    from retrobridge.terminal.routes import terminal_bp
    from retrobridge.admin.routes import admin_bp
    from retrobridge.terminal.events import register_socketio_events

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(jobs_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(terminal_bp, url_prefix='/terminal')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    register_socketio_events(socketio)

    from retrobridge.auth.utils import load_user
    login_manager.user_loader(load_user)

    from cli import register_cli_commands
    register_cli_commands(app)

    register_error_handlers(app)

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        app.db_session.remove()

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config.get('UPLOAD_DIR', 'uploads'), exist_ok=True)
    os.makedirs(app.config.get('OUTPUT_DIR', 'outputs'), exist_ok=True)
    os.makedirs(app.config.get('SESSION_LOG_DIR', 'session_logs'), exist_ok=True)
    os.makedirs(app.config.get('LOG_DIR', 'logs'), exist_ok=True)

    return app


def register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        from flask import render_template
        return render_template('errors/500.html'), 500
