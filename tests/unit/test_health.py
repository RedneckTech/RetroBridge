"""Tests for health-check endpoints (review #9): no sensitive disclosure,
optional token gate."""
from retrobridge import create_app


def test_ready_does_not_disclose_paths_or_errors(app, client):
    resp = client.get('/ready')
    assert resp.status_code == 200
    data = resp.get_json()

    for check in data['checks']['directories'].values():
        assert 'path' not in check

    assert 'error' not in data['checks']['database']
    assert 'free_bytes' not in data['checks']['disk']
    assert 'total_bytes' not in data['checks']['disk']
    assert 'free_percent' in data['checks']['disk']


def test_ready_token_gate(app, client):
    app.config['HEALTH_TOKEN'] = 'sekrit'
    assert client.get('/ready').status_code == 403
    assert client.get('/ready?token=wrong').status_code == 403
    assert client.get('/ready?token=sekrit').status_code == 200
    assert client.get('/ready',
                      headers={'X-Health-Token': 'sekrit'}).status_code == 200

    # /health (liveness) stays open.
    assert client.get('/health').status_code == 200


def test_ready_open_when_no_token_configured(app, client):
    assert 'HEALTH_TOKEN' in app.config
    assert client.get('/ready').status_code == 200


def test_prod_app_still_boots_with_health_config():
    # Ensure create_app imports are unaffected by the health changes.
    app = create_app('config.TestConfig')
    assert app is not None
