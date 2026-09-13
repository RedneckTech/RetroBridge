"""Guards for the production async stack.

`eventlet` 0.36.x is incompatible with Python 3.13+ (its `monkey_patch()`
crashes with `AttributeError: module 'eventlet.green.thread' has no
attribute 'start_joinable_thread'`), which prevented the production server
from starting at all.  Production must run on the threading async mode with
gunicorn gthread workers instead.
"""

from pathlib import Path


def test_prodconfig_uses_threading_socketio_mode():
    from config import ProdConfig

    assert ProdConfig.SOCKETIO_ASYNC_MODE == "threading"


def test_eventlet_not_pinned_in_requirements():
    req = Path(__file__).resolve().parents[2] / "requirements.txt"
    assert "eventlet" not in req.read_text()


def test_run_prod_script_forces_production_env():
    script = Path(__file__).resolve().parents[2] / "run_prod.sh"
    text = script.read_text()
    # Unset FLASK_ENV silently fell back to DevConfig (DEBUG=True).
    assert "export FLASK_ENV=production" in text


def test_run_prod_script_defaults_to_single_worker():
    script = Path(__file__).resolve().parents[2] / "run_prod.sh"
    text = script.read_text()
    # SocketIO has no message queue, so events do not cross workers.
    assert "GUNICORN_WORKERS:-1" in text
    assert "GUNICORN_THREADS" in text


def test_run_prod_script_uses_project_venv_gunicorn():
    script = Path(__file__).resolve().parents[2] / "run_prod.sh"
    text = script.read_text()
    # The script must not depend on gunicorn being on PATH: use the venv's.
    assert "venv/bin/gunicorn" in text


def test_prod_csp_allows_inline_styles_and_gravatar():
    from config import ProdConfig

    csp = ProdConfig.SECURITY_HEADERS["Content-Security-Policy"]
    # Templates use inline style attributes and <style> blocks (Bootstrap
    # components); script-src stays strict (no 'unsafe-inline' there).
    assert "'unsafe-inline'" in csp
    # Avatars are served from Gravatar (base.html, models.py avatar URLs).
    assert "www.gravatar.com" in csp
    assert "script-src" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


def test_remember_cookie_attributes():
    from config import DevConfig, ProdConfig, TestConfig

    assert ProdConfig.REMEMBER_COOKIE_SECURE is True
    assert ProdConfig.REMEMBER_COOKIE_HTTPONLY is True
    assert ProdConfig.REMEMBER_COOKIE_SAMESITE == "Lax"
    # HTTP dev/test must not set Secure or "remember me" breaks.
    assert DevConfig.REMEMBER_COOKIE_SECURE is False
    assert TestConfig.REMEMBER_COOKIE_SECURE is False
