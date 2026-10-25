"""Доступ к users, roles и refresh_tokens.

ORM-моделей нет: запросы на SQLAlchemy Core (text), async-движок
psycopg 3. Таблицы создают миграции cloud/db (0001, 0004, 0006).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .roles import Role


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    email: str
    password_hash: str
    role: Role
    client_id: UUID | None
    is_active: bool


@dataclass(frozen=True)
class RefreshRecord:
    jti: UUID
    user_id: UUID
    expires_at: datetime
    revoked_at: datetime | None


class UserAlreadyExists(Exception):
    pass


class UnknownRole(Exception):
    pass


class AuthStore(Protocol):
    async def get_user_by_email(self, email: str) -> UserRecord | None: ...

    async def get_user(self, user_id: UUID) -> UserRecord | None: ...

    async def touch_login(self, user_id: UUID) -> None: ...

    async def create_user(
        self, email: str, password_hash: str, role: Role, client_id: UUID | None, full_name: str | None
    ) -> UUID: ...

    async def save_refresh(self, jti: UUID, user_id: UUID, expires_at: datetime) -> None: ...

    async def get_refresh(self, jti: UUID) -> RefreshRecord | None: ...

    async def rotate_refresh(self, old_jti: UUID, new_jti: UUID, user_id: UUID, expires_at: datetime) -> bool:
        """Отзывает old_jti и сохраняет new_jti в одной транзакции.

        False — old_jti уже отозван (гонка двух /refresh с одним токеном).
        """
        ...

    async def revoke_refresh(self, jti: UUID) -> None: ...

    async def revoke_all_for_user(self, user_id: UUID) -> int: ...

    async def close(self) -> None: ...


_USER_COLUMNS = """
    u.id, u.email, u.password_hash, r.name AS role, u.client_id, u.is_active
    FROM users u JOIN roles r ON r.id = u.role_id
"""


def _user(row) -> UserRecord | None:
    if row is None:
        return None
    return UserRecord(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        role=Role(row.role),
        client_id=row.client_id,
        is_active=row.is_active,
    )


class SqlAuthStore:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine

    @classmethod
    def from_url(cls, url: str) -> "SqlAuthStore":
        return cls(create_async_engine(url, pool_pre_ping=True))

    async def get_user_by_email(self, email: str) -> UserRecord | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(f"SELECT {_USER_COLUMNS} WHERE lower(u.email) = lower(:email)"), {"email": email}
                )
            ).first()
        return _user(row)

    async def get_user(self, user_id: UUID) -> UserRecord | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(text(f"SELECT {_USER_COLUMNS} WHERE u.id = :id"), {"id": user_id})).first()
        return _user(row)

    async def touch_login(self, user_id: UUID) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(text("UPDATE users SET last_login_at = now() WHERE id = :id"), {"id": user_id})

    async def create_user(
        self, email: str, password_hash: str, role: Role, client_id: UUID | None, full_name: str | None
    ) -> UUID:
        async with self._engine.begin() as conn:
            role_id = (await conn.execute(text("SELECT id FROM roles WHERE name = :n"), {"n": role.value})).scalar()
            if role_id is None:
                raise UnknownRole(role.value)
            try:
                return (
                    await conn.execute(
                        text(
                            "INSERT INTO users (email, password_hash, full_name, role_id, client_id) "
                            "VALUES (:email, :hash, :name, :role_id, :client_id) RETURNING id"
                        ),
                        {
                            "email": email,
                            "hash": password_hash,
                            "name": full_name,
                            "role_id": role_id,
                            "client_id": client_id,
                        },
                    )
                ).scalar_one()
            except IntegrityError as exc:
                raise UserAlreadyExists(email) from exc

    async def save_refresh(self, jti: UUID, user_id: UUID, expires_at: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO refresh_tokens (jti, user_id, expires_at) VALUES (:jti, :uid, :exp)"),
                {"jti": jti, "uid": user_id, "exp": expires_at},
            )

    async def get_refresh(self, jti: UUID) -> RefreshRecord | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT jti, user_id, expires_at, revoked_at FROM refresh_tokens WHERE jti = :jti"),
                    {"jti": jti},
                )
            ).first()
        if row is None:
            return None
        return RefreshRecord(row.jti, row.user_id, row.expires_at, row.revoked_at)

    async def rotate_refresh(self, old_jti: UUID, new_jti: UUID, user_id: UUID, expires_at: datetime) -> bool:
        async with self._engine.begin() as conn:
            updated = (
                await conn.execute(
                    text(
                        "UPDATE refresh_tokens SET revoked_at = now(), replaced_by = :new "
                        "WHERE jti = :old AND revoked_at IS NULL RETURNING jti"
                    ),
                    {"old": old_jti, "new": new_jti},
                )
            ).first()
            if updated is None:
                return False
            await conn.execute(
                text("INSERT INTO refresh_tokens (jti, user_id, expires_at) VALUES (:jti, :uid, :exp)"),
                {"jti": new_jti, "uid": user_id, "exp": expires_at},
            )
            return True

    async def revoke_refresh(self, jti: UUID) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE refresh_tokens SET revoked_at = now() WHERE jti = :jti AND revoked_at IS NULL"),
                {"jti": jti},
            )

    async def revoke_all_for_user(self, user_id: UUID) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = :uid AND revoked_at IS NULL"),
                {"uid": user_id},
            )
            return result.rowcount

    async def close(self) -> None:
        await self._engine.dispose()
