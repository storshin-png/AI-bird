"""Зависимости FastAPI для защиты эндпоинтов.

    claims: JWTClaims = Depends(get_current_claims)               # любой вход
    claims = Depends(require_role(Role.SUPER_ADMIN))              # 403 для других ролей
    claims = Depends(require_permission(Permission.DEVICES_WRITE))
    scope: ClientScope = Depends(require_scope("client"))         # фильтр по client_id

Нет токена, подпись не та, токен истёк или это refresh — 401.
Роль или права не подходят — 403.

Другие сервисы могут подключить эти зависимости, им нужен только
TokenService с публичным ключом в app.state.tokens.
"""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.sql import ColumnElement, Select

from .claims import JWTClaims
from .roles import CLIENT_SCOPED_ROLES, Role
from .tokens import TokenError, TokenService

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(reason: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=reason,
        headers={"WWW-Authenticate": f'Bearer error="invalid_token", error_description="{reason}"'},
    )


def _forbidden(reason: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)


def get_token_service(request: Request) -> TokenService:
    return request.app.state.tokens


async def get_current_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    tokens: TokenService = Depends(get_token_service),
) -> JWTClaims:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("missing_token")
    try:
        return tokens.decode_access(credentials.credentials)
    except TokenError as exc:
        raise _unauthorized(exc.reason) from exc


def require_role(*roles: Role | str):
    allowed = {Role(r) for r in roles}
    if not allowed:
        raise ValueError("require_role: нужна хотя бы одна роль")

    async def dependency(claims: JWTClaims = Depends(get_current_claims)) -> JWTClaims:
        if claims.role not in allowed:
            raise _forbidden("insufficient_role")
        return claims

    return dependency


def require_permission(*perms: str):
    needed = tuple(str(p) for p in perms)
    if not needed:
        raise ValueError("require_permission: нужно хотя бы одно право")

    async def dependency(claims: JWTClaims = Depends(get_current_claims)) -> JWTClaims:
        if not claims.has_permissions(*needed):
            raise _forbidden("insufficient_permissions")
        return claims

    return dependency


@dataclass(frozen=True)
class ClientScope:
    """Ограничение выборки своим client_id.

    Для b2b_client добавляет WHERE client_id = :jwt_client_id, для
    внутренних ролей ничего не меняет.
    """

    claims: JWTClaims

    @property
    def restricted(self) -> bool:
        return self.claims.role in CLIENT_SCOPED_ROLES

    @property
    def client_id(self) -> UUID | None:
        return self.claims.client_id

    def apply(self, stmt: Select, column: ColumnElement) -> Select:
        """Для SQLAlchemy Core: scope.apply(select(events), events.c.client_id)."""
        if not self.restricted:
            return stmt
        return stmt.where(column == self.claims.client_id)

    def sql(self, column: str = "client_id") -> tuple[str, dict]:
        """Для text-запросов: фрагмент для WHERE и параметры к нему."""
        if not self.restricted:
            return "TRUE", {}
        return f"{column} = :jwt_client_id", {"jwt_client_id": self.claims.client_id}

    def allows(self, client_id: UUID | None) -> bool:
        """Проверка одной записи, уже прочитанной из БД."""
        return not self.restricted or (client_id is not None and client_id == self.claims.client_id)


def require_scope(kind: str):
    if kind != "client":
        raise ValueError(f"require_scope: неизвестная область {kind!r}, поддерживается только 'client'")

    async def dependency(claims: JWTClaims = Depends(get_current_claims)) -> ClientScope:
        scope = ClientScope(claims)
        if scope.restricted and scope.client_id is None:
            # Клиент без client_id не должен видеть ничего, а не всё.
            raise _forbidden("client_not_assigned")
        return scope

    return dependency
