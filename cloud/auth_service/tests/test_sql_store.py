"""Интеграция с PostgreSQL стенда.

Нужна БД после `alembic upgrade head`. Адрес — в AIBIRD_TEST_DATABASE_URL,
например postgresql+psycopg://aibird:aibird-stand@127.0.0.1:5432/aibird.
Без переменной тесты пропускаются. Созданных пользователей тесты удаляют.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from auth_service.app import create_app
from auth_service.passwords import hash_password
from auth_service.roles import Role
from auth_service.store import SqlAuthStore, UnknownRole, UserAlreadyExists

from .conftest import PASSWORD, bearer, login

URL = os.environ.get("AIBIRD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="AIBIRD_TEST_DATABASE_URL не задан")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sql_store():
    # NullPool: каждый asyncio.run — свой цикл событий, соединения между ними не переносятся.
    store = SqlAuthStore(create_async_engine(URL, poolclass=NullPool))
    tag = uuid4().hex[:8]
    yield store, tag

    async def cleanup():
        async with store._engine.begin() as conn:
            await conn.execute(text("DELETE FROM users WHERE email LIKE :p"), {"p": f"%-{tag}@test.aibird"})
            await conn.execute(text("DELETE FROM clients WHERE name = :n"), {"n": f"test-{tag}"})
        await store.close()

    run(cleanup())


def _email(tag, name):
    return f"{name}-{tag}@test.aibird"


def test_create_and_read_user(sql_store):
    store, tag = sql_store
    uid = run(store.create_user(_email(tag, "Admin"), hash_password(PASSWORD, rounds=4), Role.SUPER_ADMIN, None, "Админ"))
    by_email = run(store.get_user_by_email(_email(tag, "admin").upper()))
    assert by_email.id == uid and by_email.role is Role.SUPER_ADMIN and by_email.is_active
    assert run(store.get_user(uid)).email == _email(tag, "Admin")
    assert run(store.get_user(uuid4())) is None
    assert run(store.get_user_by_email("nobody@test.aibird")) is None
    with pytest.raises(UserAlreadyExists):
        run(store.create_user(_email(tag, "ADMIN"), "x", Role.SUPER_ADMIN, None, None))
    run(store.touch_login(uid))


def test_unknown_role(sql_store, monkeypatch):
    store, tag = sql_store

    class FakeRole:
        value = "no_such_role"

    with pytest.raises(UnknownRole):
        run(store.create_user(_email(tag, "x"), "x", FakeRole(), None, None))


def test_refresh_token_rows(sql_store):
    store, tag = sql_store
    uid = run(store.create_user(_email(tag, "t"), hash_password(PASSWORD, rounds=4), Role.FIELD_ENGINEER, None, None))
    exp = datetime.now(UTC) + timedelta(days=7)
    a, b, c = uuid4(), uuid4(), uuid4()
    run(store.save_refresh(a, uid, exp))
    assert run(store.get_refresh(a)).revoked_at is None
    assert run(store.get_refresh(uuid4())) is None
    assert run(store.rotate_refresh(a, b, uid, exp)) is True
    # Второй rotate того же токена проигрывает гонку.
    assert run(store.rotate_refresh(a, c, uid, exp)) is False
    assert run(store.get_refresh(c)) is None
    assert run(store.get_refresh(a)).revoked_at is not None
    assert run(store.revoke_all_for_user(uid)) == 1
    run(store.revoke_refresh(b))
    assert run(store.get_refresh(b)).revoked_at is not None


def test_full_http_flow_on_postgres(sql_store, settings, tokens):
    store, tag = sql_store

    async def make_client():
        async with store._engine.begin() as conn:
            return (
                await conn.execute(text("INSERT INTO clients (name) VALUES (:n) RETURNING id"), {"n": f"test-{tag}"})
            ).scalar_one()

    cid = run(make_client())
    run(store.create_user(_email(tag, "b2b"), hash_password(PASSWORD, rounds=4), Role.B2B_CLIENT, cid, None))
    app = create_app(settings=settings, store=store, tokens=tokens)
    with TestClient(app) as client:
        assert login(client, _email(tag, "b2b"), "wrong-password").status_code == 401
        pair = login(client, _email(tag, "b2b")).json()
        me = client.get("/api/v1/auth/me", headers=bearer(pair["access_token"])).json()
        assert me["client_id"] == str(cid) and me["role"] == "b2b_client"
        new = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert new.status_code == 200
        reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert reuse.status_code == 401
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": new.json()["refresh_token"]}).status_code == 401
        again = login(client, _email(tag, "b2b")).json()
        assert client.post("/api/v1/auth/logout", json={"refresh_token": again["refresh_token"]}).status_code == 204
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": again["refresh_token"]}).status_code == 401
