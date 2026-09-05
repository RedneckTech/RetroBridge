"""Unit tests for Patreon integration helpers."""
from retrobridge.integrations.patreon import get_tier_limits


class TestGetTierLimits:
    def test_returns_none_for_empty_tier(self, app):
        assert get_tier_limits(None) == (None, None)
        assert get_tier_limits('') == (None, None)
        assert get_tier_limits('none') == (None, None)

    def test_builds_uppercase_setting_keys(self, app, db_session):
        from retrobridge.models import AdminSetting
        db_session.add(AdminSetting(
            key='PATREON_TIER_BRONZE_JOBS', value='10',
            description='Bronze jobs'))
        db_session.add(AdminSetting(
            key='PATREON_TIER_BRONZE_SESSIONS', value='3',
            description='Bronze sessions'))
        db_session.commit()

        with app.app_context():
            assert get_tier_limits('bronze') == (10, 3)
            assert get_tier_limits('Bronze') == (10, 3)
            assert get_tier_limits('BRONZE') == (10, 3)

    def test_returns_none_when_settings_missing(self, app):
        with app.app_context():
            assert get_tier_limits('platinum') == (None, None)
