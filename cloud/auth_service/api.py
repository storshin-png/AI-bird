"""Эндпоинты /api/v1/auth/*: login, refresh, logout, me, jwks."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from .claims import JWTClaims
from .deps import _unauthorized, get_current_claims
from .provider import InvalidCredentials, PasswordCredentials
from .service import AuthService
from .tokens import TokenError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=8192)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    sub: str
    email: str
    role: str
    client_id: str | None
    permissions: list[str]


def _service(request: Request) -> AuthService:
    return request.app.state.auth


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, service: AuthService = Depends(_service)) -> TokenResponse:
    try:
        pair = await service.login(PasswordCredentials(body.email, body.password))
    except InvalidCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials") from exc
    return TokenResponse(access_token=pair.access_token, refresh_token=pair.refresh_token, expires_in=pair.expires_in)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, service: AuthService = Depends(_service)) -> TokenResponse:
    try:
        pair = await service.refresh(body.refresh_token)
    except TokenError as exc:
        raise _unauthorized(exc.reason) from exc
    return TokenResponse(access_token=pair.access_token, refresh_token=pair.refresh_token, expires_in=pair.expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, service: AuthService = Depends(_service)) -> Response:
    try:
        await service.logout(body.refresh_token)
    except TokenError as exc:
        raise _unauthorized(exc.reason) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def me(claims: JWTClaims = Depends(get_current_claims)) -> MeResponse:
    return MeResponse(
        sub=str(claims.sub),
        email=claims.email,
        role=claims.role.value,
        client_id=str(claims.client_id) if claims.client_id else None,
        permissions=list(claims.permissions),
    )


@router.get("/.well-known/jwks.json")
async def jwks(request: Request) -> dict:
    """Публичный ключ для проверки подписи другими сервисами."""
    return {"keys": [request.app.state.tokens.jwk]}
