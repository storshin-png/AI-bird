from uuid import uuid4

import jwt

from auth_service.roles import Role

from .conftest import bearer, login


def test_login_returns_valid_jwt_with_claims(client, store):
    cid = uuid4()
    user = store.add_user("client@acme.ru", role=Role.B2B_CLIENT, client_id=cid)
    r = login(client, "client@acme.ru")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 3600
    me = client.get("/api/v1/auth/me", headers=bearer(body["access_token"])).json()
    assert me == {
        "sub": str(user.id),
        "email": "client@acme.ru",
        "role": "b2b_client",
        "client_id": str(cid),
        "permissions": ["events:read", "export:read", "species:read", "tracks:read"],
    }
    assert store.logins == [user.id]


def test_login_email_is_case_insensitive(client, store):
    store.add_user("Admin@AIbird.local")
    assert login(client, "  admin@aibird.local ").status_code == 200


def test_login_failures_look_the_same(client, store):
    store.add_user("a@aibird.local")
    store.add_user("off@aibird.local", active=False)
    for email, pw in [("a@aibird.local", "wrong-password"), ("nobody@aibird.local", "x"), ("off@aibird.local", None)]:
        r = login(client, email, pw) if pw else login(client, email)
        assert r.status_code == 401
        assert r.json() == {"detail": "invalid_credentials"}
    assert store.logins == []


def test_login_validates_body(client):
    assert client.post("/api/v1/auth/login", json={"email": "a@b"}).status_code == 422


def test_refresh_rotates_tokens(client, store):
    store.add_user("a@aibird.local")
    first = login(client, "a@aibird.local").json()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert client.get("/api/v1/auth/me", headers=bearer(second["access_token"])).status_code == 200


def test_refresh_reuse_revokes_everything(client, store):
    store.add_user("a@aibird.local")
    first = login(client, "a@aibird.local").json()
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).json()
    # Старый токен предъявлен ещё раз — например, его украли.
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401 and r.json()["detail"] == "token_revoked"
    # Вместе с ним отозван и честный новый.
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.status_code == 401
    assert all(t.revoked_at is not None for t in store.tokens.values())


def test_refresh_picks_up_role_change(client, store):
    user = store.add_user("a@aibird.local", role=Role.FIELD_ENGINEER)
    first = login(client, "a@aibird.local").json()
    store.set_user(user.id, role=Role.LEAD_ORNITHOLOGIST)
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).json()
    me = client.get("/api/v1/auth/me", headers=bearer(second["access_token"])).json()
    assert me["role"] == "lead_ornithologist"


def test_refresh_for_deactivated_user(client, store):
    user = store.add_user("a@aibird.local")
    first = login(client, "a@aibird.local").json()
    store.set_user(user.id, is_active=False)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401 and r.json()["detail"] == "user_inactive"


def test_refresh_for_deleted_user(client, store):
    user = store.add_user("a@aibird.local")
    first = login(client, "a@aibird.local").json()
    del store.users[user.id]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401


def test_refresh_rejects_access_token_and_garbage(client, store):
    store.add_user("a@aibird.local")
    access = login(client, "a@aibird.local").json()["access_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert r.status_code == 401 and r.json()["detail"] == "wrong_token_type"
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": "abc"}).status_code == 401


def test_refresh_unknown_jti(client, tokens):
    token = tokens.issue_refresh(uuid4()).token  # подписан верно, но в БД его нет
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 401 and r.json()["detail"] == "invalid_token"


def test_refresh_lost_race(client, store, monkeypatch):
    store.add_user("a@aibird.local")
    first = login(client, "a@aibird.local").json()

    async def lost(*args):
        return False

    monkeypatch.setattr(store, "rotate_refresh", lost)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401 and r.json()["detail"] == "token_revoked"


def test_logout_revokes_refresh(client, store):
    store.add_user("a@aibird.local")
    pair = login(client, "a@aibird.local").json()
    assert client.post("/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]}).status_code == 204
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert r.status_code == 401
    # Повторный logout безвреден.
    assert client.post("/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]}).status_code == 204


def test_logout_accepts_expired_refresh(client, store, tokens, clock):
    user = store.add_user("a@aibird.local")
    clock.advance(-8 * 24 * 3600)
    old = tokens.issue_refresh(user.id)
    clock.advance(8 * 24 * 3600)
    assert client.post("/api/v1/auth/logout", json={"refresh_token": old.token}).status_code == 204


def test_logout_rejects_garbage(client):
    assert client.post("/api/v1/auth/logout", json={"refresh_token": "abc"}).status_code == 401


def test_me_requires_token(client, store, tokens, clock):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401 and r.json()["detail"] == "missing_token"
    assert r.headers["www-authenticate"].startswith("Bearer")
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401
    store.add_user("a@aibird.local")
    clock.advance(-2 * 3600)
    expired = login(client, "a@aibird.local").json()["access_token"]
    r = client.get("/api/v1/auth/me", headers=bearer(expired))
    assert r.status_code == 401 and r.json()["detail"] == "token_expired"


def test_jwks_and_health(client, tokens):
    keys = client.get("/api/v1/auth/.well-known/jwks.json").json()["keys"]
    assert keys == [tokens.jwk]
    assert client.get("/healthz").json() == {"status": "ok"}


def test_openapi_lists_auth_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout", "/api/v1/auth/me"):
        assert p in paths


def test_cors_whitelist(client):
    pre = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    ok = client.options("/api/v1/auth/login", headers={"Origin": "http://localhost:5173", **pre})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    bad = client.options("/api/v1/auth/login", headers={"Origin": "https://evil.example", **pre})
    assert "access-control-allow-origin" not in bad.headers


def test_tokens_are_rs256_signed(client, store):
    store.add_user("a@aibird.local")
    body = login(client, "a@aibird.local").json()
    for t in (body["access_token"], body["refresh_token"]):
        assert jwt.get_unverified_header(t)["alg"] == "RS256"
