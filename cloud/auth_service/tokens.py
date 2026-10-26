"""Выпуск и проверка JWT RS256: access (1 час) и refresh (7 дней)."""

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from .claims import JWTClaims
from .config import Settings
from .roles import Role

ALGORITHM = "RS256"
ACCESS = "access"
REFRESH = "refresh"


class TokenError(Exception):
    """Токен не прошёл проверку. reason уходит в ответ 401."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class KeyFileError(RuntimeError):
    pass


@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: UUID
    expires_at: datetime


@dataclass(frozen=True)
class RefreshPayload:
    jti: UUID
    sub: UUID
    expires_at: datetime


def generate_private_key(bits: int = 3072) -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def private_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def public_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def write_key_pair(directory: Path, bits: int = 3072, overwrite: bool = False) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    priv_path, pub_path = directory / "private.pem", directory / "public.pem"
    if not overwrite and (priv_path.exists() or pub_path.exists()):
        raise FileExistsError(f"Ключи уже есть в {directory}")
    key = generate_private_key(bits)
    priv_path.write_bytes(private_pem(key))
    priv_path.chmod(0o600)
    pub_path.write_bytes(public_pem(key))
    return priv_path, pub_path


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TokenService:
    def __init__(self, private_key_pem: bytes | None, public_key_pem: bytes, settings: Settings, clock=_utcnow):
        self._private = (
            serialization.load_pem_private_key(private_key_pem, password=None) if private_key_pem else None
        )
        self._public = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(self._public, rsa.RSAPublicKey):
            raise KeyFileError("Публичный ключ должен быть RSA")
        self._settings = settings
        self._clock = clock
        self.jwk = self._make_jwk()
        self.kid = self.jwk["kid"]

    @classmethod
    def from_settings(cls, settings: Settings, clock=_utcnow) -> "TokenService":
        try:
            priv = settings.private_key_file.read_bytes()
            pub = settings.public_key_file.read_bytes()
        except FileNotFoundError as exc:
            raise KeyFileError(
                f"Нет файла ключа {exc.filename}. Создайте пару: python -m auth_service keys"
            ) from exc
        return cls(priv, pub, settings, clock)

    def _make_jwk(self) -> dict:
        numbers = self._public.public_numbers()
        n = _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big"))
        e = _b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big"))
        # RFC 7638: отпечаток ключа как kid.
        thumb = json.dumps({"e": e, "kty": "RSA", "n": n}, separators=(",", ":"), sort_keys=True)
        kid = _b64(hashlib.sha256(thumb.encode("ascii")).digest())
        return {"kty": "RSA", "use": "sig", "alg": ALGORITHM, "kid": kid, "n": n, "e": e}

    def _encode(self, payload: dict) -> str:
        if self._private is None:
            raise KeyFileError("Без закрытого ключа токены можно только проверять")
        return jwt.encode(payload, self._private, algorithm=ALGORITHM, headers={"kid": self.kid})

    def _base(self, typ: str, sub: UUID, ttl: int) -> tuple[dict, UUID, datetime]:
        now = self._clock()
        exp = now + timedelta(seconds=ttl)
        jti = uuid4()
        payload = {
            "iss": self._settings.issuer,
            "aud": self._settings.audience,
            "sub": str(sub),
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "jti": str(jti),
            "typ": typ,
        }
        return payload, jti, datetime.fromtimestamp(payload["exp"], UTC)

    def issue_access(self, claims: JWTClaims) -> IssuedToken:
        payload, jti, exp = self._base(ACCESS, claims.sub, self._settings.access_ttl_seconds)
        payload.update(
            email=claims.email,
            role=claims.role.value,
            client_id=str(claims.client_id) if claims.client_id else None,
            permissions=list(claims.permissions),
        )
        return IssuedToken(self._encode(payload), jti, exp)

    def issue_refresh(self, user_id: UUID) -> IssuedToken:
        payload, jti, exp = self._base(REFRESH, user_id, self._settings.refresh_ttl_seconds)
        return IssuedToken(self._encode(payload), jti, exp)

    def _decode(self, token: str, typ: str, verify_exp: bool = True) -> dict:
        try:
            payload = jwt.decode(
                token,
                self._public,
                algorithms=[ALGORITHM],
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                leeway=self._settings.leeway_seconds,
                options={
                    "require": ["exp", "iat", "sub", "jti", "iss", "aud"],
                    "verify_exp": verify_exp,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenError("token_expired") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenError("invalid_token") from exc
        if payload.get("typ") != typ:
            raise TokenError("wrong_token_type")
        try:
            UUID(payload["sub"])
            UUID(payload["jti"])
        except (ValueError, TypeError) as exc:
            raise TokenError("invalid_token") from exc
        return payload

    def decode_access(self, token: str) -> JWTClaims:
        payload = self._decode(token, ACCESS)
        try:
            role = Role(payload["role"])
            client_id = UUID(payload["client_id"]) if payload.get("client_id") else None
            email = str(payload["email"])
            permissions = tuple(str(p) for p in payload["permissions"])
        except (KeyError, ValueError, TypeError) as exc:
            raise TokenError("invalid_token") from exc
        return JWTClaims(
            sub=UUID(payload["sub"]),
            email=email,
            role=role,
            client_id=client_id,
            permissions=permissions,
            exp=datetime.fromtimestamp(payload["exp"], UTC),
        )

    def decode_refresh(self, token: str, verify_exp: bool = True) -> RefreshPayload:
        payload = self._decode(token, REFRESH, verify_exp=verify_exp)
        return RefreshPayload(
            jti=UUID(payload["jti"]),
            sub=UUID(payload["sub"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
