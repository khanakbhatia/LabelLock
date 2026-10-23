import sys

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import REPO_ROOT, Settings

sys.path.insert(0, str(REPO_ROOT / "contracts"))
import validate_examples  # noqa: E402

SPEC = validate_examples.load_spec()


def assert_matches(schema_name: str, data) -> None:
    """Fail if `data` does not validate against a contracts/openapi.yaml schema."""
    problems = validate_examples.validate_example(SPEC, data, schema_name)
    assert not problems, problems


@pytest.fixture(scope="session")
def settings(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("db")
    return Settings(database_url=f"sqlite:///{(tmp / 'test.db').as_posix()}", auth_secret="test-secret",
                    cors_origin="http://localhost:5173", extension_origin="chrome-extension://labellocktestid",
                    upload_dir=tmp / "uploads", sim_database_url=f"sqlite:///{(tmp / 'sim.db').as_posix()}",
                    sim_api_key="test-sim-key", seed_dir=tmp / "no-seed-here", demo_mode=True)


@pytest.fixture(scope="session")
def app(settings):
    app = create_app(settings)
    app.state.sim_http = TestClient(app)  # adapters call /sim/* in-process instead of over a socket
    return app


@pytest.fixture(scope="session")
def client(app):
    return TestClient(app)


@pytest.fixture(scope="session")
def token_for(client):
    cache = {}

    def get(username: str) -> str:
        if username not in cache:
            r = client.post("/api/auth/login", json={"username": username, "password": "demo"})
            assert r.status_code == 200, r.text
            cache[username] = r.json()["token"]
        return cache[username]
    return get
