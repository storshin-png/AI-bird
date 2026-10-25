"""Сценарии login, refresh, logout поверх провайдера, токенов и хранилища."""

import logging
from dataclasses import dataclass

from .claims import JWTClaims
from .provider import AuthProvider
from .store import AuthStore
from .tokens import TokenError, TokenService

log = logging.getLogger("auth_service")


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, provider: AuthProvider, store: AuthStore, tokens: TokenService, access_ttl: int):
        self._provider = provider
        self._store = store
        self._tokens = tokens
        self._access_ttl = access_ttl

    async def _issue(self, claims: JWTClaims) -> TokenPair:
        access = self._tokens.issue_access(claims)
        refresh = self._tokens.issue_refresh(claims.sub)
        await self._store.save_refresh(refresh.jti, claims.sub, refresh.expires_at)
        return TokenPair(access.token, refresh.token, self._access_ttl)

    async def login(self, credentials) -> TokenPair:
        claims = await self._provider.authenticate(credentials)
        log.info("login", extra={"user_id": str(claims.sub), "role": claims.role.value})
        return await self._issue(claims)

    async def refresh(self, refresh_token: str) -> TokenPair:
        payload = self._tokens.decode_refresh(refresh_token)
        record = await self._store.get_refresh(payload.jti)
        if record is None or record.user_id != payload.sub:
            raise TokenError("invalid_token")
        if record.revoked_at is not None:
            # Отозванный токен предъявили снова: считаем, что его украли.
            count = await self._store.revoke_all_for_user(record.user_id)
            log.warning("refresh_reuse", extra={"user_id": str(record.user_id), "revoked": count})
            raise TokenError("token_revoked")
        user = await self._store.get_user(record.user_id)
        if user is None or not user.is_active:
            await self._store.revoke_all_for_user(record.user_id)
            raise TokenError("user_inactive")
        # Роль и client_id берём из БД заново: смена роли действует с ближайшего refresh.
        claims = JWTClaims.for_user(user.id, user.email, user.role, user.client_id)
        access = self._tokens.issue_access(claims)
        new_refresh = self._tokens.issue_refresh(user.id)
        if not await self._store.rotate_refresh(payload.jti, new_refresh.jti, user.id, new_refresh.expires_at):
            await self._store.revoke_all_for_user(user.id)
            raise TokenError("token_revoked")
        return TokenPair(access.token, new_refresh.token, self._access_ttl)

    async def logout(self, refresh_token: str) -> None:
        # Истёкший токен тоже принимаем: выйти можно всегда.
        payload = self._tokens.decode_refresh(refresh_token, verify_exp=False)
        await self._store.revoke_refresh(payload.jti)
        log.info("logout", extra={"user_id": str(payload.sub)})
