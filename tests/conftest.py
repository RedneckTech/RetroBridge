import pytest


@pytest.fixture
def app():
    from retrobridge import create_app
    app = create_app('config.TestConfig')
    from retrobridge.models import Base
    Base.metadata.create_all(bind=app.db_engine)
    yield app
    Base.metadata.drop_all(bind=app.db_engine)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


@pytest.fixture
def db_session(app):
    return app.db_session
