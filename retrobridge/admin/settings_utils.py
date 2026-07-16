"""Typed accessors for admin settings stored in the AdminSetting table."""

from functools import lru_cache

from flask import current_app

from retrobridge.models import AdminSetting

SETTING_DEFAULTS = {
    'MAX_UPLOAD_SIZE_BYTES': ('16777216', int),
    'DEFAULT_MAX_QUEUED_JOBS': ('3', int),
    'DEFAULT_MAX_TERMINAL_SESSIONS': ('1', int),
    'MAX_JOBS_PER_HOUR': ('10', int),
    'MAX_TERMINAL_SESSION_SECONDS': ('3600', int),
    'TERMINAL_IDLE_TIMEOUT_SECONDS': ('300', int),
    'WORKER_POLL_SECONDS': ('5', int),
    'REGISTRATION_OPEN': ('1', bool),
    'MAINTENANCE_MODE': ('0', bool),
    'TERMINAL_SESSION_LOG_ENABLED': ('0', bool),
    'PATREON_CLIENT_ID': ('', str),
    'PATREON_CLIENT_SECRET': ('', str),
    'PATREON_CAMPAIGN_ID': ('', str),
    'PATREON_TIER_BRONZE_JOBS': ('10', int),
    'PATREON_TIER_BRONZE_SESSIONS': ('3', int),
    'PATREON_TIER_SILVER_JOBS': ('50', int),
    'PATREON_TIER_SILVER_SESSIONS': ('10', int),
    'PATREON_TIER_GOLD_JOBS': ('999', int),
    'PATREON_TIER_GOLD_SESSIONS': ('20', int),
}


def _get_raw(key):
    setting = current_app.db_session.get(AdminSetting, key)
    if setting:
        return setting.value
    default = SETTING_DEFAULTS.get(key)
    return default[0] if default else None


def get_int(key):
    val = _get_raw(key)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def get_bool(key):
    val = _get_raw(key)
    return str(val).lower() in ('1', 'true', 'yes', 'on')
