from uuid import uuid4

import jwt
import pytest

from auth_service.claims import JWTClaims
from auth_service.passwords import WeakPasswordError, hash_password, validate_new_password, verify_password
from auth_service.roles import ROLE_PERMISSIONS, Permission, Role, permissions_for
from auth_service.tokens import KeyFileError, TokenError, TokenService, write_key_pair


# --- пароли ---------------------------------------------------------------

def test_hash_and_verify():
    h = hash_password("правильный-пароль", rounds=4)
    assert h.startswith("$2")
    assert verify_password("правильный-пароль", h)
    assert not verify_password("неправильный", h)


def test_verify_without_hash_is_false():
    assert verify_password("anything", None) is False


def test_verify_malformed_hash_is_false():
    assert verify_password("anything", "not-a-bcrypt-hash") is False


@pytest.mark.parametrize("pw", ["short", "я" * 37])
def test_weak_passwords_rejected(pw):
    with pytest.raises(WeakPasswordError):
        validate_new_password(pw)


def test_overlong_password_never_matches():
    base = "a" * 72
    h = hash_password(base, rounds=4)
    # Тот же префикс в 72 байта, но длиннее: bcrypt бы совпал, мы — нет.
    assert not verify_password(base + "tail", h)


# --- роли -----------------------------------------------------------------

def test_super_admin_has_everything():
    assert ROLE_PERMISSIONS[Role.SUPER_ADMIN] == frozenset(Permission)


def test_b2b_client_cannot_see_fleet_or_unknown_queue():
    perms = set(permissions_for(Role.B2B_CLIENT))
    assert Permission.DEVICES_READ not in perms
    assert Permission.UNKNOWN_QUEUE_READ not in perms
    assert Permission.EXPORT_READ in perms


def test_field_engineer_sees_fleet():
    assert Permission.DEVICES_READ in permissions_for(Role.FIELD_ENGINEER)


# --- токены ---------------------------------------------------------------

def _claims(role=Role.B2B_CLIENT, client_id=None):
    return JWTClaims.for_user(uuid4(), "user@aibird.local", role, client_id or uuid4())


def test_access_roundtrip(tokens):
    claims = _claims()
    issued = tokens.issue_access(claims)
    decoded = tokens.decode_access(issued.token)
    assert decoded.sub == claims.sub
    assert decoded.email == claims.email
    assert decoded.role is Role.B2B_CLIENT
    assert decoded.client_id == claims.client_id
    assert decoded.permissions == claims.permissions
    assert decoded.exp == issued.expires_at


def test_access_token_has_spec_claims_and_kid(tokens, key_pems):
    issued = tokens.issue_access(_claims())
    header = jwt.get_unverified_header(issued.token)
    assert header["alg"] == "RS256"
    assert header["kid"] == tokens.kid
    body = jwt.decode(issued.token, options={"verify_signature": False})
    for name in ("sub", "email", "role", "client_id", "permissions", "exp"):
        assert name in body
    assert body["exp"] - body["iat"] == 3600


def test_refresh_ttl_is_seven_days(tokens):
    issued = tokens.issue_refresh(uuid4())
    body = jwt.decode(issued.token, options={"verify_signature": False})
    assert body["exp"] - body["iat"] == 7 * 24 * 3600


def test_expired_access(tokens, clock):
    clock.advance(-2 * 3600)
    token = tokens.issue_access(_claims()).token
    with pytest.raises(TokenError) as err:
        tokens.decode_access(token)
    assert err.value.reason == "token_expired"


def test_refresh_is_not_access(tokens):
    token = tokens.issue_refresh(uuid4()).token
    with pytest.raises(TokenError) as err:
        tokens.decode_access(token)
    assert err.value.reason == "wrong_token_type"


def test_access_is_not_refresh(tokens):
    token = tokens.issue_access(_claims()).token
    with pytest.raises(TokenError) as err:
        tokens.decode_refresh(token)
    assert err.value.reason == "wrong_token_type"


def test_foreign_key_rejected(tokens, other_key_pems, settings):
    foreign = TokenService(other_key_pems[0], other_key_pems[1], settings)
    token = foreign.issue_access(_claims()).token
    with pytest.raises(TokenError) as err:
        tokens.decode_access(token)
    assert err.value.reason == "invalid_token"


def test_hs256_and_none_rejected(tokens, key_pems):
    base = {"sub": str(uuid4()), "jti": str(uuid4()), "iss": "aibird-auth", "aud": "aibird-api",
            "iat": 0, "exp": 4102444800, "typ": "access"}
    for token in (
        jwt.encode(base, "secret", algorithm="HS256"),
        jwt.encode(base, None, algorithm="none"),
    ):
        with pytest.raises(TokenError):
            tokens.decode_access(token)


def test_wrong_audience_rejected(key_pems, settings):
    from dataclasses import replace

    a = TokenService(key_pems[0], key_pems[1], settings)
    b = TokenService(key_pems[0], key_pems[1], replace(settings, audience="другой-сервис"))
    with pytest.raises(TokenError):
        b.decode_access(a.issue_access(_claims()).token)


def _signed(key_pems, **payload):
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(key_pems[0], None)
    base = {"sub": str(uuid4()), "jti": str(uuid4()), "iss": "aibird-auth", "aud": "aibird-api",
            "iat": 1_700_000_000, "exp": 4_102_444_800, "typ": "access",
            "email": "x@y", "role": "super_admin", "client_id": None, "permissions": []}
    base.update(payload)
    return jwt.encode(base, key, algorithm="RS256")


@pytest.mark.parametrize(
    "payload",
    [{"role": "hacker"}, {"client_id": "not-a-uuid"}, {"sub": "not-a-uuid"}, {"permissions": None}],
)
def test_malformed_claims_rejected(tokens, key_pems, payload):
    with pytest.raises(TokenError) as err:
        tokens.decode_access(_signed(key_pems, **payload))
    assert err.value.reason == "invalid_token"


def test_jwk_matches_public_key(tokens):
    from jwt.algorithms import RSAAlgorithm

    pub = RSAAlgorithm.from_jwk(tokens.jwk)
    token = tokens.issue_access(_claims()).token
    jwt.decode(token, pub, algorithms=["RS256"], audience="aibird-api")
    assert tokens.jwk["kid"] == tokens.kid and tokens.jwk["alg"] == "RS256"


def test_verify_only_service(key_pems, settings, tokens):
    verifier = TokenService(None, key_pems[1], settings)
    token = tokens.issue_access(_claims()).token
    assert verifier.decode_access(token).email == "user@aibird.local"
    with pytest.raises(KeyFileError):
        verifier.issue_access(_claims())


def test_non_rsa_public_key_rejected(settings):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pem = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    with pytest.raises(KeyFileError):
        TokenService(None, pem, settings)


def test_key_files(tmp_path, settings):
    from dataclasses import replace

    priv, pub = write_key_pair(tmp_path / "keys", bits=2048)
    assert oct(priv.stat().st_mode & 0o777) == "0o600"
    svc = TokenService.from_settings(replace(settings, private_key_file=priv, public_key_file=pub))
    assert svc.decode_refresh(svc.issue_refresh(uuid4()).token)
    with pytest.raises(FileExistsError):
        write_key_pair(tmp_path / "keys", bits=2048)
    write_key_pair(tmp_path / "keys", bits=2048, overwrite=True)


def test_missing_key_files(tmp_path, settings):
    from dataclasses import replace

    missing = replace(settings, private_key_file=tmp_path / "no.pem", public_key_file=tmp_path / "no.pub")
    with pytest.raises(KeyFileError, match="python -m auth_service keys"):
        TokenService.from_settings(missing)
