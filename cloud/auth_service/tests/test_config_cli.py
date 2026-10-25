from pathlib import Path
from uuid import uuid4

import pytest

from auth_service import cli
from auth_service.config import DEFAULT_KEYS_DIR, Settings
from auth_service.provider import PasswordAuthProvider
from auth_service.roles import Role

from .conftest import MemoryStore


def test_settings_defaults():
    s = Settings.from_env({})
    assert s.access_ttl_seconds == 3600
    assert s.refresh_ttl_seconds == 604800
    assert s.cors_origins == ()
    assert s.private_key_file == DEFAULT_KEYS_DIR / "private.pem"
    assert s.database_url.startswith("postgresql+psycopg://aibird:")


def test_settings_from_env(tmp_path):
    s = Settings.from_env(
        {
            "AIBIRD_DATABASE_URL": "postgresql+psycopg://u:p@db:5432/x",
            "AUTH_PRIVATE_KEY_FILE": str(tmp_path / "k"),
            "AUTH_PUBLIC_KEY_FILE": str(tmp_path / "p"),
            "AUTH_ISSUER": "iss",
            "AUTH_AUDIENCE": "aud",
            "AUTH_ACCESS_TTL_SECONDS": "60",
            "AUTH_REFRESH_TTL_SECONDS": "120",
            "AUTH_CORS_ORIGINS": "http://localhost:5173, https://map.aibird.ru ,",
        }
    )
    assert s.database_url.endswith("@db:5432/x")
    assert s.private_key_file == Path(tmp_path / "k")
    assert (s.issuer, s.audience, s.access_ttl_seconds, s.refresh_ttl_seconds) == ("iss", "aud", 60, 120)
    assert s.cors_origins == ("http://localhost:5173", "https://map.aibird.ru")


def test_cors_wildcard_forbidden():
    with pytest.raises(ValueError):
        Settings.from_env({"AUTH_CORS_ORIGINS": "*"})


def test_cli_keys(tmp_path, capsys):
    out = tmp_path / "keys"
    assert cli.main(["keys", "--out", str(out), "--bits", "2048"]) == 0
    assert (out / "private.pem").exists() and (out / "public.pem").exists()
    assert cli.main(["keys", "--out", str(out), "--bits", "2048"]) == 1
    assert "--force" in capsys.readouterr().err
    assert cli.main(["keys", "--out", str(out), "--bits", "2048", "--force"]) == 0


@pytest.fixture
def memory():
    store = MemoryStore()
    return store, (lambda url: store)


def test_cli_create_user(memory, monkeypatch, capsys):
    store, factory = memory
    monkeypatch.setenv("AIBIRD_NEW_PASSWORD", "very-long-password")
    assert cli.main(["create-user", "--email", " admin@aibird.local ", "--role", "super_admin"], factory) == 0
    (user,) = store.users.values()
    assert user.email == "admin@aibird.local" and user.role is Role.SUPER_ADMIN
    assert store.closed
    assert "Создан пользователь" in capsys.readouterr().out


def test_cli_created_user_can_log_in(memory, monkeypatch):
    import asyncio

    from auth_service.provider import PasswordCredentials

    store, factory = memory
    monkeypatch.setenv("AIBIRD_NEW_PASSWORD", "very-long-password")
    cid = str(uuid4())
    cli.main(["create-user", "--email", "c@acme.ru", "--role", "b2b_client", "--client-id", cid], factory)
    claims = asyncio.run(PasswordAuthProvider(store).authenticate(PasswordCredentials("c@acme.ru", "very-long-password")))
    assert str(claims.client_id) == cid


def test_cli_create_user_errors(memory, monkeypatch, capsys):
    store, factory = memory
    monkeypatch.setenv("AIBIRD_NEW_PASSWORD", "very-long-password")
    with pytest.raises(SystemExit):
        cli.main(["create-user", "--email", "c@acme.ru", "--role", "b2b_client"], factory)
    assert cli.main(["create-user", "--email", "a@x", "--role", "super_admin"], factory) == 0
    assert cli.main(["create-user", "--email", "A@X", "--role", "super_admin"], factory) == 1
    assert "уже есть" in capsys.readouterr().err
    monkeypatch.setenv("AIBIRD_NEW_PASSWORD", "short")
    assert cli.main(["create-user", "--email", "b@x", "--role", "super_admin"], factory) == 1


def test_cli_unknown_role_in_db(memory, monkeypatch, capsys):
    from auth_service.store import UnknownRole

    store, factory = memory

    async def no_roles(*args):
        raise UnknownRole("super_admin")

    monkeypatch.setattr(store, "create_user", no_roles)
    monkeypatch.setenv("AIBIRD_NEW_PASSWORD", "very-long-password")
    assert cli.main(["create-user", "--email", "a@x", "--role", "super_admin"], factory) == 1
    assert "alembic upgrade head" in capsys.readouterr().err


def test_cli_password_prompt(monkeypatch):
    monkeypatch.delenv("AIBIRD_NEW_PASSWORD", raising=False)
    answers = iter(["very-long-password", "very-long-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))
    assert cli._read_password() == "very-long-password"
    answers = iter(["very-long-password", "different-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))
    with pytest.raises(SystemExit):
        cli._read_password()


def test_app_owns_and_closes_its_store(settings, tokens):
    from fastapi.testclient import TestClient

    from auth_service.app import create_app
    from auth_service.store import SqlAuthStore

    app = create_app(settings=settings, tokens=tokens)
    assert isinstance(app.state.store, SqlAuthStore)
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
