"""AuthProvider — точка замены входа по паролю на OIDC (Keycloak, ЕСИА) в v1.1.

Остальной код видит только authenticate(credentials) -> JWTClaims.
Как подменить реализацию — docs/OIDC_MIGRATION.md.
"""

from dataclasses import dataclass
from typing import Protocol

from .claims import JWTClaims
from .passwords import verify_password
from .store import AuthStore


class InvalidCredentials(Exception):
    """Неверный логин, пароль или пользователь отключён. Причину наружу не отдаём."""


@dataclass(frozen=True)
class PasswordCredentials:
    email: str
    password: str


class AuthProvider(Protocol):
    async def authenticate(self, credentials) -> JWTClaims: ...


class PasswordAuthProvider:
    """MVP: email и пароль из таблицы users, хеш bcrypt."""

    def __init__(self, store: AuthStore):
        self._store = store

    async def authenticate(self, credentials: PasswordCredentials) -> JWTClaims:
        user = await self._store.get_user_by_email(credentials.email.strip())
        ok = verify_password(credentials.password, user.password_hash if user else None)
        if user is None or not ok or not user.is_active:
            raise InvalidCredentials()
        await self._store.touch_login(user.id)
        return JWTClaims.for_user(user.id, user.email, user.role, user.client_id)
