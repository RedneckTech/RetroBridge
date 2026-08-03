"""
Patreon Integration
====================
OAuth account linking, membership tier lookup, and token refresh
for Patreon supporter integration.

Configured via AdminSetting keys:
  PATREON_CLIENT_ID, PATREON_CLIENT_SECRET, PATREON_CAMPAIGN_ID,
  PATREON_TIER_*_JOBS, PATREON_TIER_*_SESSIONS
"""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

PATREON_AUTHORIZE_URL = 'https://www.patreon.com/oauth2/authorize'
PATREON_TOKEN_URL = 'https://www.patreon.com/api/oauth2/token'
PATREON_IDENTITY_URL = 'https://www.patreon.com/api/oauth2/v2/identity'
PATREON_MEMBERS_URL = 'https://www.patreon.com/api/oauth2/v2/campaigns/{campaign_id}/members'


def _get_setting(key, default=''):
    from retrobridge.admin.settings_utils import _get_raw
    return _get_raw(key) or default


def get_client_id():
    return _get_setting('PATREON_CLIENT_ID')


def get_client_secret():
    return _get_setting('PATREON_CLIENT_SECRET')


def get_campaign_id():
    return _get_setting('PATREON_CAMPAIGN_ID')


def is_enabled():
    return bool(get_client_id())


def get_authorize_url(redirect_uri, state=''):
    """Build the Patreon OAuth2 authorization URL."""
    params = {
        'client_id': get_client_id(),
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'identity identity.memberships',
        'state': state,
    }
    return f'{PATREON_AUTHORIZE_URL}?{urlencode(params)}'


def exchange_code(code, redirect_uri):
    """Exchange an authorization code for access + refresh tokens.

    Returns dict with keys: access_token, refresh_token, expires_in
    or None on failure.
    """
    try:
        resp = requests.post(PATREON_TOKEN_URL, data={
            'code': code,
            'client_id': get_client_id(),
            'client_secret': get_client_secret(),
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri,
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {
            'access_token': data['access_token'],
            'refresh_token': data.get('refresh_token', ''),
            'expires_in': data.get('expires_in', 3600),
        }
    except Exception:
        logger.exception('Patreon token exchange failed')
        return None


def refresh_access_token(refresh_token):
    """Refresh an expired access token using the stored refresh token.

    Returns dict with keys: access_token, refresh_token, expires_in
    or None on failure.
    """
    try:
        resp = requests.post(PATREON_TOKEN_URL, data={
            'refresh_token': refresh_token,
            'client_id': get_client_id(),
            'client_secret': get_client_secret(),
            'grant_type': 'refresh_token',
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {
            'access_token': data['access_token'],
            'refresh_token': data.get('refresh_token', refresh_token),
            'expires_in': data.get('expires_in', 3600),
        }
    except Exception:
        logger.exception('Patreon token refresh failed')
        return None


def get_valid_token(user, db_session):
    """Return a valid access token for the user, refreshing if needed.

    If the token is expired or about to expire (< 5 min remaining),
    attempt a refresh. Returns the access token string or None.
    Mutations are committed to the database.
    """
    if not user.patreon_access_token:
        return None

    if user.patreon_expires_at:
        now = datetime.now(timezone.utc)
        expires = user.patreon_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if (expires - now) > timedelta(minutes=5):
            return user.patreon_access_token

    if not user.patreon_refresh_token:
        return None

    refreshed = refresh_access_token(user.patreon_refresh_token)
    if not refreshed:
        return None

    user.patreon_access_token = refreshed['access_token']
    user.patreon_refresh_token = refreshed['refresh_token']
    user.patreon_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=refreshed['expires_in'],
    )
    db_session.commit()
    return refreshed['access_token']


def fetch_patreon_identity(access_token):
    """Fetch the Patreon user's identity (ID, full name, email).

    Returns dict with keys: id, full_name, email or None on failure.
    """
    try:
        resp = requests.get(PATREON_IDENTITY_URL, headers={
            'Authorization': f'Bearer {access_token}',
        }, params={
            'fields[user]': 'full_name,email',
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        attrs = data['data']['attributes']
        return {
            'id': data['data']['id'],
            'full_name': attrs.get('full_name', ''),
            'email': attrs.get('email', ''),
        }
    except Exception:
        logger.exception('Patreon identity fetch failed')
        return None


def fetch_membership_tier(access_token):
    """Fetch the user's current membership tier for the configured campaign.

    Returns the tier name string (e.g., 'Bronze', 'Silver', 'Gold')
    or None if not a member / lookup fails.
    """
    campaign_id = get_campaign_id()
    if not campaign_id:
        return None

    try:
        resp = requests.get(
            PATREON_MEMBERS_URL.format(campaign_id=campaign_id),
            headers={'Authorization': f'Bearer {access_token}'},
            params={
                'fields[member]': 'patron_status,pledge_relationship_start',
                'page[count]': '10',
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        for member in data.get('data', []):
            attrs = member.get('attributes', {})
            patron_status = attrs.get('patron_status', '')
            if patron_status in ('active_patron', 'active_patron_late'):
                tier_id = member.get('relationships', {}).get(
                    'tier', {},
                ).get('data', {}).get('id', '')
                if tier_id:
                    tier_name = _resolve_tier_name(tier_id, data, access_token)
                    if tier_name:
                        return tier_name

        return None
    except Exception:
        logger.exception('Patreon membership fetch failed')
        return None


def _resolve_tier_name(tier_id, api_data, access_token=None):
    """Map a Patreon tier ID to a tier name using included tier objects.
    Falls back to a direct API call if not found in the included data."""
    for included in api_data.get('included', []):
        if included.get('id') == tier_id and included.get('type') == 'tier':
            title = included.get('attributes', {}).get('title', '').strip()
            if title:
                return title
    if access_token:
        return resolve_tier_name_from_api(tier_id, access_token)
    return None


def resolve_tier_name_from_api(tier_id, access_token):
    """Fetch tier name directly from Patreon API if not in membership response."""
    try:
        url = f'https://www.patreon.com/api/oauth2/v2/tiers/{tier_id}'
        resp = requests.get(url, headers={
            'Authorization': f'Bearer {access_token}',
        }, params={'fields[tier]': 'title'}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get('data', {}).get('attributes', {}).get('title', '')
    except Exception:
        return None


def get_tier_limits(tier_name):
    """Return (max_queued_jobs, max_terminal_sessions) for a Patreon tier.

    Tier limits are read from AdminSetting keys:
      PATREON_TIER_BRONZE_JOBS, PATREON_TIER_BRONZE_SESSIONS, etc.

    Returns (jobs_limit, sessions_limit) as integers.
    """
    tier_key = (tier_name or '').lower().strip()
    if not tier_key or tier_key == 'none':
        return None, None

    jobs_key = f'patreon_tier_{tier_key}_jobs'
    sessions_key = f'patreon_tier_{tier_key}_sessions'

    try:
        jobs = int(_get_setting(jobs_key, '0'))
        sessions = int(_get_setting(sessions_key, '0'))
    except (ValueError, TypeError):
        return None, None

    if jobs <= 0 or sessions <= 0:
        return None, None

    return jobs, sessions


def sync_user_tier(user, db_session):
    """Refresh the user's Patreon tier from the API.

    Calls get_valid_token to refresh if needed, then fetches
    the current membership tier. Updates user.patreon_tier.
    Commits changes to the database. Returns the new tier name or None.
    """
    token = get_valid_token(user, db_session)
    if not token:
        user.patreon_tier = None
        db_session.commit()
        return None

    tier = fetch_membership_tier(token)
    user.patreon_tier = tier
    db_session.commit()
    return tier


def unlink_user(user):
    """Remove all Patreon data from a user account."""
    user.patreon_id = None
    user.patreon_tier = None
    user.patreon_access_token = None
    user.patreon_refresh_token = None
    user.patreon_expires_at = None
