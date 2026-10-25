from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth_service.app import create_app
from auth_service.config import Settings
from auth_service.passwords import hash_password
from auth_service.roles import Role
from auth_service.store import RefreshRecord, UnknownRole, UserAlreadyExists, UserRecord
from auth_service.tokens import TokenService, generate_private_key, private_pem, public_pem

PASSWORD = "correct-horse-battery"


class Clock:
    """Часы выпуска токенов. PyJWT проверяет exp по настоящему времени,
    поэтому истёкший токен получают, сдвинув часы выпуска в прошлое."""

    def __init__(self):
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class MemoryStore:
    """Хранилище в памяти с тем же протоколом, что SqlAuthStore."""

    def __init__(self):
        self.users: dict[UUID, UserRecord] = {}
        self.tokens: dict[UUID, RefreshRecord] = {}
        self.logins: list[UUID] = []
        self.closed = False

    def add_user(self, email, role=Role.SUPER_ADMIN, client_id=None, active=True, password=PASSWORD) -> UserRecord:
        user = UserRecord(uuid4(), email, hash_password(password, rounds=4), role, client_id, active)
        self.users[user.id] = user
        return user

    def set_user(self, user_id, **changes) -> None:
        self.users[user_id] = replace(self.users[user_id], **changes)

    async def get_user_by_email(self, email):
        return next((u for u in self.users.values() if u.email.lower() == email.lower()), None)

    async def get_user(self, user_id):
        return self.users.get(user_id)

    async def touch_login(self, user_id):
        self.logins.append(user_id)

    async def create_user(self, email, password_hash, role, client_id, full_name):
        if role not in set(Role):
            raise UnknownRole(role)
        if any(u.email.lower() == email.lower() for u in self.users.values()):
            raise UserAlreadyExists(email)
        user = UserRecord(uuid4(), email, password_hash, role, client_id, True)
        self.users[user.id] = user
        return user.id

    async def save_refresh(self, jti, user_id, expires_at):
        self.tokens[jti] = RefreshRecord(jti, user_id, expires_at, None)

    async def get_refresh(self, jti):
        return self.tokens.get(jti)

    async def rotate_refresh(self, old_jti, new_jti, user_id, expires_at):
        old = self.tokens.get(old_jti)
        if old is None or old.revoked_at is not None:
            return False
        self.tokens[old_jti] = replace(old, revoked_at=datetime.now(UTC))
        self.tokens[new_jti] = RefreshRecord(new_jti, user_id, expires_at, None)
        return True

    async def revoke_refresh(self, jti):
        rec = self.tokens.get(jti)
        if rec and rec.revoked_at is None:
            self.tokens[jti] = replace(rec, revoked_at=datetime.now(UTC))

    async def revoke_all_for_user(self, user_id):
        n = 0
        for jti, rec in list(self.tokens.items()):
            if rec.user_id == user_id and rec.revoked_at is None:
                self.tokens[jti] = replace(rec, revoked_at=datetime.now(UTC))
                n += 1
        return n

    async def close(self):
        self.closed = True


@pytest.fixture(scope="session")
def key_pems():
    key = generate_private_key(2048)
    return private_pem(key), public_pem(key)


@pytest.fixture(scope="session")
def other_key_pems():
    key = generate_private_key(2048)
    return private_pem(key), public_pem(key)


@pytest.fixture
def settings():
    return Settings(database_url="postgresql+psycopg://unused/unused", cors_origins=("http://localhost:5173",))


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def tokens(key_pems, settings, clock):
    return TokenService(key_pems[0], key_pems[1], settings, clock=clock)


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def client(settings, store, tokens):
    app = create_app(settings=settings, store=store, tokens=tokens)
    with TestClient(app) as c:
        yield c


def login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}
