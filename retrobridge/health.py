"""
Health-check endpoints for load balancers, orchestrators (k8s, Nomad),
and systemd health-check directives.

GET /health  — Lightweight liveness probe (always returns 200 if the
               process is alive and the Flask app is serving requests).
GET /ready   — Readiness probe: verifies database connectivity,
               required directories exist, and disk usage is within
               acceptable bounds.  Returns 200 when ready, 503 otherwise.
"""

import hmac
import os
import shutil
from datetime import datetime, timezone

from flask import Blueprint, jsonify
from sqlalchemy import text

health_bp = Blueprint('health', __name__)


def _db_connectivity(app):
    try:
        app.db_session.execute(text('SELECT 1'))
        return True
    except Exception:
        return False


def _dir_exists(path):
    return os.path.isdir(path) if path else False


def _disk_usage(path):
    try:
        usage = shutil.disk_usage(path)
        return usage.free / usage.total * 100
    except Exception:
        return None


def _token_ok():
    from flask import current_app, request

    token = current_app.config.get('HEALTH_TOKEN')
    if not token:
        return True
    provided = (request.headers.get('X-Health-Token')
                or request.args.get('token')
                or '')
    return hmac.compare_digest(token, provided)


@health_bp.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'service': 'retrobridge',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })


@health_bp.route('/ready')
def ready():
    from flask import current_app

    if not _token_ok():
        return jsonify({'error': 'Forbidden'}), 403

    checks = {}
    all_ok = True

    db_ok = _db_connectivity(current_app)
    checks['database'] = {'ok': db_ok}
    if not db_ok:
        all_ok = False

    dirs = {
        'instance': current_app.instance_path,
        'uploads': current_app.config.get('UPLOAD_DIR'),
        'outputs': current_app.config.get('OUTPUT_DIR'),
        'session_logs': current_app.config.get('SESSION_LOG_DIR'),
        'logs': current_app.config.get('LOG_DIR'),
        'backups': current_app.config.get('BACKUP_DIR'),
    }
    dir_checks = {}
    for name, path in dirs.items():
        exists = _dir_exists(path)
        dir_checks[name] = {'ok': exists}
        if not exists:
            all_ok = False
    checks['directories'] = dir_checks

    disk_check = {}
    root_path = current_app.config.get('UPLOAD_DIR') or current_app.instance_path
    free_pct = _disk_usage(root_path)
    if free_pct is not None:
        low_space = free_pct < 5
        if low_space:
            all_ok = False
        disk_check = {
            'ok': not low_space,
            'free_percent': round(free_pct, 1),
        }
    else:
        disk_check = {'ok': True, 'note': 'disk check unavailable'}
    checks['disk'] = disk_check

    maintenance = False
    try:
        from retrobridge.admin.settings_utils import get_bool
        maintenance = get_bool('MAINTENANCE_MODE')
    except Exception:
        pass
    checks['maintenance_mode'] = {'enabled': maintenance}

    status_code = 200 if all_ok else 503

    resp = {
        'status': 'ready' if all_ok else 'degraded',
        'service': 'retrobridge',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'checks': checks,
    }

    return jsonify(resp), status_code
