import ipaddress
import logging
import os
import sqlite3
import time

from flask import jsonify, request

EXEMPT_BLUEPRINTS = ('health',)
EXEMPT_ENDPOINTS = ('static',)
EXEMPT_PATH_PREFIXES = ('/socket.io/',)

logger = logging.getLogger(__name__)


def _is_trusted_proxy(addr, trusted):
    """Return True if *addr* matches one of the trusted proxy IPs/CIDRs."""
    if not addr or not trusted:
        return False
    try:
        client_ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    for spec in trusted:
        try:
            if '/' in spec:
                if client_ip in ipaddress.ip_network(spec, strict=False):
                    return True
            elif client_ip == ipaddress.ip_address(spec):
                return True
        except ValueError:
            continue
    return False


def init_security(app):
    """Register security headers and rate-limiting middleware."""
    _init_headers(app)
    _init_rate_limiter(app)


# ── Security Headers (after_request) ────────────────────────────────────────

def _init_headers(app):
    headers = app.config.get('SECURITY_HEADERS', {})

    @app.after_request
    def _add_security_headers(response):
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response


# ── Rate Limiter (before_request) ───────────────────────────────────────────

class _MemoryRateLimiterStore:
    """In-memory sliding-window timestamp store per (ip, endpoint) key."""

    def __init__(self):
        self._store = {}

    def check(self, key, max_req, window):
        now = time.time()
        timestamps = self._store.get(key, [])
        cutoff = now - window

        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)

        if len(timestamps) >= max_req:
            return True

        if not timestamps:
            self._store[key] = timestamps
        timestamps.append(now)
        return False


class _SqliteRateLimiterStore:
    """SQLite-backed sliding-window timestamp store shared across workers."""

    def __init__(self, path, busy_timeout=5000):
        self._path = path
        self._busy_timeout = busy_timeout
        self._ensure_table()

    def _connect(self):
        conn = sqlite3.connect(self._path, timeout=self._busy_timeout / 1000.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute(f'PRAGMA busy_timeout={self._busy_timeout}')
        return conn

    def _ensure_table(self):
        os.makedirs(os.path.dirname(self._path) or '.', exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                'CREATE TABLE IF NOT EXISTS rate_limits '
                '(key TEXT NOT NULL, timestamp REAL NOT NULL)'
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS ix_rate_limits_key_ts '
                'ON rate_limits (key, timestamp)'
            )

    def check(self, key, max_req, window):
        now = time.time()
        cutoff = now - window

        with self._connect() as conn:
            # Use an immediate transaction so concurrent workers serialize.
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.execute(
                    'DELETE FROM rate_limits WHERE key = ? AND timestamp < ?',
                    (key, cutoff)
                )
                cur = conn.execute(
                    'SELECT COUNT(*) FROM rate_limits WHERE key = ?',
                    (key,)
                )
                count = cur.fetchone()[0]

                if count >= max_req:
                    conn.commit()
                    return True

                conn.execute(
                    'INSERT INTO rate_limits (key, timestamp) VALUES (?, ?)',
                    (key, now)
                )
                conn.commit()
                return False
            except Exception:
                conn.rollback()
                raise


_store = None


def _get_store(app):
    global _store
    if _store is not None:
        return _store

    store_type = app.config.get('RATE_LIMIT_STORE', 'memory').lower()
    if store_type == 'sqlite':
        path = app.config.get('RATE_LIMIT_DB_PATH')
        if not path:
            instance = getattr(app, 'instance_path', None) or os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 'instance'
            )
            path = os.path.join(instance, 'rate_limits.db')
        _store = _SqliteRateLimiterStore(path)
        logger.info('Using SQLite-backed rate limit store at %s', path)
    else:
        _store = _MemoryRateLimiterStore()
        if app.config.get('ENV') == 'production':
            logger.warning(
                'Rate limiting is using an in-memory store. With multiple '
                'gunicorn workers limits are per-process. Set '
                'RATE_LIMIT_STORE=sqlite or deploy a single worker for '
                'consistent enforcement.'
            )
    return _store


def _init_rate_limiter(app):
    if not app.config.get('RATE_LIMIT_ENABLED', True):
        return

    store = _get_store(app)

    @app.before_request
    def _check_rate_limit():
        if _is_exempt(request):
            return

        limits = app.config.get('RATE_LIMITS', {})
        max_req, window = _resolve_limits(limits, request)
        if max_req <= 0:
            return

        ip = _client_ip(request)
        key = f'{ip}:{request.endpoint or request.path}'

        if store.check(key, max_req, window):
            resp = jsonify({'error': 'rate limit exceeded'})
            resp.status_code = 429
            resp.headers['Retry-After'] = str(int(window))
            return resp


def _is_exempt(request):
    if request.endpoint in EXEMPT_ENDPOINTS:
        return True
    if request.blueprint in EXEMPT_BLUEPRINTS:
        return True
    for prefix in EXEMPT_PATH_PREFIXES:
        if request.path.startswith(prefix):
            return True
    return False


def _resolve_limits(limits, request):
    endpoint = request.endpoint or request.path
    if endpoint in limits:
        return limits[endpoint]
    if request.blueprint and request.blueprint in limits:
        return limits[request.blueprint]
    return limits.get('default', (0, 60))


def _client_ip(request):
    """Determine the client IP, accounting for trusted reverse proxies.

    If the immediate remote address is a trusted proxy and an
    X-Forwarded-For header is present, walk the header from right to left
    and return the first untrusted address. This prevents clients from
    spoofing their IP by adding arbitrary entries to the header.
    """
    remote_addr = request.remote_addr
    trusted = []
    app = getattr(request, 'app', None)
    if app is not None:
        trusted = app.config.get('TRUSTED_PROXIES', [])

    if not _is_trusted_proxy(remote_addr, trusted):
        return remote_addr

    forwarded = request.headers.get('X-Forwarded-For')
    if not forwarded:
        return remote_addr

    # X-Forwarded-For is a comma-separated list with the most recent proxy
    # appended at the end. The rightmost untrusted address is the client.
    for ip in reversed(forwarded.split(',')):
        ip = ip.strip()
        if ip and not _is_trusted_proxy(ip, trusted):
            return ip

    # All entries are trusted proxies; fall back to the direct remote address.
    return remote_addr
