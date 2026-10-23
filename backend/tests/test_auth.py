import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api.auth import make_token
from api.main import create_app
from tests.conftest import assert_matches

DEMO_USERS = {
    "valley.ingredients": "supplier",
    "priya.qa": "qa_specialist",
    "daniel.qam": "qa_manager",
    "marco.ship": "shipping_supervisor",
    "admin": "admin",
    "labellock-agent": "agent",
}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def assert_error(r, status: int, code: str) -> dict:
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details", "request_id"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"].startswith("req_")
    assert r.headers["X-Request-ID"] == body["error"]["request_id"]
    assert_matches("Error", body)
    return body["error"]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert_matches("Health", r.json())


@pytest.mark.parametrize("username,role", DEMO_USERS.items())
def test_login_succeeds_for_each_demo_user(client, username, role):
    r = client.post("/api/auth/login", json={"username": username, "password": "demo"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert_matches("LoginResponse", body)
    assert body["user"]["role"] == role

    me = client.get("/api/auth/me", headers=bearer(body["token"]))
    assert me.status_code == 200
    assert_matches("User", me.json())
    assert me.json() == body["user"]


def test_bad_password_is_401(client):
    r = client.post("/api/auth/login", json={"username": "priya.qa", "password": "wrong"})
    assert_error(r, 401, "UNAUTHENTICATED")


def test_unknown_user_is_401_with_same_message(client):
    unknown = client.post("/api/auth/login", json={"username": "nobody", "password": "demo"})
    wrong_pw = client.post("/api/auth/login", json={"username": "priya.qa", "password": "wrong"})
    assert assert_error(unknown, 401, "UNAUTHENTICATED")["message"] == assert_error(wrong_pw, 401, "UNAUTHENTICATED")["message"]


def test_missing_token_is_401(client):
    assert_error(client.get("/api/auth/me"), 401, "UNAUTHENTICATED")
    assert_error(client.post("/api/actions/a_012/approve"), 401, "UNAUTHENTICATED")


def test_tampered_and_expired_tokens_are_401(client, settings, token_for):
    token = token_for("priya.qa")
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    assert_error(client.get("/api/auth/me", headers=bearer(tampered)), 401, "UNAUTHENTICATED")
    expired = make_token("u_priya", settings.auth_secret, ttl_seconds=-1)
    assert_error(client.get("/api/auth/me", headers=bearer(expired)), 401, "UNAUTHENTICATED")
    forged = make_token("u_daniel", "some-other-secret", ttl_seconds=3600)
    assert_error(client.get("/api/auth/me", headers=bearer(forged)), 401, "UNAUTHENTICATED")


def test_qa_specialist_cannot_approve(client, token_for):
    r = client.post("/api/actions/a_012/approve", json={"comment": "ok"}, headers=bearer(token_for("priya.qa")))
    err = assert_error(r, 403, "FORBIDDEN")
    assert "qa_specialist" in err["message"]
    assert err["details"] == {"allowed_roles": ["qa_manager"]}


@pytest.mark.parametrize("username", [u for u, role in DEMO_USERS.items() if role != "qa_manager"])
def test_only_qa_manager_passes_approve_role_check(client, token_for, username):
    r = client.post("/api/actions/a_012/approve", headers=bearer(token_for(username)))
    assert_error(r, 403, "FORBIDDEN")


def test_qa_manager_reaches_approve_placeholder(client, token_for):
    r = client.post("/api/actions/a_012/approve", json={"comment": "ok"}, headers=bearer(token_for("daniel.qam")))
    err = assert_error(r, 501, "NOT_IMPLEMENTED")
    assert err["details"] == {"action_id": "a_012"}


def test_validation_error_format(client):
    r = client.post("/api/auth/login", json={"username": "priya.qa"})
    err = assert_error(r, 422, "VALIDATION_ERROR")
    assert {"field": "body.password", "message": "Field required"} in err["details"]["fields"]


def test_unknown_route_and_wrong_method_use_error_format(client):
    assert_error(client.get("/api/does-not-exist"), 404, "NOT_FOUND")
    assert_error(client.get("/api/auth/login"), 405, "NOT_FOUND")


def test_unhandled_exception_uses_error_format(settings):
    app = create_app(settings)

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("secret internals")

    r = TestClient(app, raise_server_exceptions=False).get("/api/boom")
    err = assert_error(r, 500, "INTERNAL_ERROR")
    assert "secret" not in err["message"]


def test_cors_allows_configured_origin_only(client):
    ok = client.options("/api/auth/me", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/api/auth/me", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


PUBLIC_ROUTES = {"/api/health", "/api/auth/login"}


def _uses_require_roles(dependant) -> bool:
    return any(
        d.call.__qualname__.startswith("require_roles.") or _uses_require_roles(d)
        for d in dependant.dependencies
    )


def test_every_non_public_route_uses_require_roles(app):
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path not in PUBLIC_ROUTES]
    assert routes
    missing = [r.path for r in routes if not _uses_require_roles(r.dependant)]
    assert not missing, f"routes without require_roles: {missing}"
