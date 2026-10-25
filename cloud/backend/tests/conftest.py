"""Общие фикстуры. Тесты с БД и брокером пропускаются без адресов:

    AIBIRD_TEST_DATABASE_URL  postgresql+psycopg://... после alembic upgrade head
    AIBIRD_TEST_MQTT          host:port брокера, например 127.0.0.1:1883

Тесты создают датчики с уникальным префиксом и удаляют за собой всё.
"""

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from auth_service import JWTClaims, Role
from auth_service.config import Settings as AuthSettings
from auth_service.tokens import TokenService, generate_private_key, private_pem, public_pem
from backend.app import create_app
from backend.config import Settings

DB_URL = os.environ.get("AIBIRD_TEST_DATABASE_URL")
MQTT = os.environ.get("AIBIRD_TEST_MQTT")

needs_db = pytest.mark.skipif(not DB_URL, reason="AIBIRD_TEST_DATABASE_URL не задан")
needs_mqtt = pytest.mark.skipif(not (DB_URL and MQTT), reason="нужны AIBIRD_TEST_DATABASE_URL и AIBIRD_TEST_MQTT")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="session")
def tokens():
    key = generate_private_key(2048)
    return TokenService(private_pem(key), public_pem(key), AuthSettings())


def bearer(tokens: TokenService, role: str, client_id: UUID | None = None, permissions=None) -> dict:
    claims = JWTClaims.for_user(uuid4(), f"{role}@test.aibird", Role(role), client_id)
    if permissions is not None:
        claims = JWTClaims(claims.sub, claims.email, claims.role, claims.client_id, tuple(permissions))
    return {"Authorization": f"Bearer {tokens.issue_access(claims).token}"}


@pytest.fixture
def engine():
    if not DB_URL:
        pytest.skip("AIBIRD_TEST_DATABASE_URL не задан")
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    yield eng
    run(eng.dispose())


class Db:
    """Помощник для подготовки и проверки данных в тестах."""

    def __init__(self, engine):
        self.engine = engine
        self.tag = uuid4().hex[:8]
        self.clients: list[UUID] = []

    def dev(self, name: str) -> str:
        return f"t{self.tag}-{name}"

    def exec(self, sql: str, **params):
        returns_rows = sql.lstrip().upper().startswith(("SELECT", "WITH")) or "RETURNING" in sql.upper()

        async def go():
            async with self.engine.begin() as conn:
                result = await conn.execute(text(sql), params)
                return result.all() if returns_rows else None

        return run(go())

    def scalar(self, sql: str, **params):
        rows = self.exec(sql, **params)
        return rows[0][0] if rows else None

    def client(self) -> UUID:
        cid = self.scalar("INSERT INTO clients (name) VALUES (:n) RETURNING id", n=f"test-{self.tag}")
        self.clients.append(cid)
        return cid

    def device(self, name: str, client_id=None, status="active", lat=53.4, lon=59.0) -> str:
        device_id = self.dev(name)
        self.exec(
            "INSERT INTO devices (device_id, client_id, status, installation_geo) "
            "VALUES (:d, :c, :s, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)",
            d=device_id, c=client_id, s=status, lat=lat, lon=lon,
        )
        return device_id

    def cleanup(self):
        like = f"t{self.tag}-%"
        for table in ("bearings", "telemetry", "events", "maintenance_logs"):
            self.exec(f"DELETE FROM {table} WHERE device_id LIKE :p", p=like)
        self.exec("DELETE FROM devices WHERE device_id LIKE :p", p=like)
        self.exec("DELETE FROM clients WHERE name = :n", n=f"test-{self.tag}")


@pytest.fixture
def db(engine):
    helper = Db(engine)
    yield helper
    helper.cleanup()


@pytest.fixture
def api(engine, tokens):
    app = create_app(settings=Settings(cors_origins=("http://localhost:5173",)), engine=engine, tokens=tokens)
    with TestClient(app) as client:
        yield client
