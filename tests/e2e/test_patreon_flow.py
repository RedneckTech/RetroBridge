"""E2E test for the Patreon OAuth callback route.

Regression test: the callback previously referenced an undefined `user`
variable (it should be `current_user`), which would raise NameError on any
successful Patreon link. This test exercises the full success path.
"""

import tempfile

import pytest

from retrobridge.models import User


@pytest.fixture
def app():
    from retrobridge import create_app

    app = create_app("config.TestConfig")
    app.config["UPLOAD_DIR"] = tempfile.mkdtemp()
    app.config["OUTPUT_DIR"] = tempfile.mkdtemp()

    from retrobridge.models import Base

    Base.metadata.create_all(bind=app.db_engine)

    yield app

    app.db_session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


def _register_and_login(client):
    client.post(
        "/auth/register",
        data={
            "username": "newuser",
            "email": "newuser@example.com",
            "full_name": "New User",
            "password": "SecurePass1",
            "confirm_password": "SecurePass1",
        },
        follow_redirects=True,
    )
    client.post(
        "/auth/login",
        data={"username": "newuser", "password": "SecurePass1"},
        follow_redirects=True,
    )


def test_patreon_callback_links_identity(client, app, monkeypatch):
    """A successful Patreon callback persists identity + tokens on the user."""
    _register_and_login(client)

    monkeypatch.setattr(
        "retrobridge.integrations.patreon.exchange_code",
        lambda code, redirect_uri: {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        "retrobridge.integrations.patreon.fetch_patreon_identity",
        lambda access_token: {"id": "patreon-123"},
    )
    monkeypatch.setattr(
        "retrobridge.integrations.patreon.fetch_membership_tier",
        lambda access_token: "gold",
    )

    with client.session_transaction() as sess:
        sess["patreon_oauth_state"] = "test-state"

    resp = client.get("/auth/profile/patreon/callback?code=abc&state=test-state")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/auth/profile")

    user = app.db_session.query(User).filter_by(username="newuser").first()
    assert user.patreon_id == "patreon-123"
    assert user.patreon_tier == "gold"
    assert user.patreon_access_token == "tok"
    assert user.patreon_refresh_token == "ref"
    assert user.patreon_expires_at is not None
