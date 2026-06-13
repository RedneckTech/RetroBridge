import time

from flask import jsonify, request

EXEMPT_BLUEPRINTS = ('health',)
EXEMPT_ENDPOINTS = ('static',)
EXEMPT_PATH_PREFIXES = ('/socket.io/',)


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

class _RateLimiterStore:
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


_store = _RateLimiterStore()


def _init_rate_limiter(app):
    if not app.config.get('RATE_LIMIT_ENABLED', True):
        return

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

        if _store.check(key, max_req, window):
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
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    return ip
