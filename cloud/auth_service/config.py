"""Настройки из переменных окружения. Таблица переменных — в README.md."""

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
CLOUD_DIR = PACKAGE_DIR.parent
DEFAULT_KEYS_DIR = PACKAGE_DIR / "keys"
STAND_ENV = CLOUD_DIR / ".env.example"


def _stand_database_url() -> str:
    """Адрес PostgreSQL локального стенда из cloud/.env.example."""
    values: dict[str, str] = {}
    if STAND_ENV.exists():
        for line in STAND_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    user = values.get("POSTGRES_USER", "aibird")
    password = values.get("POSTGRES_PASSWORD", "aibird-stand")
    db = values.get("POSTGRES_DB", "aibird")
    host = os.environ.get("AIBIRD_DB_HOST", "127.0.0.1")
    port = os.environ.get("AIBIRD_DB_PORT", "5432")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def _split(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_stand_database_url)
    private_key_file: Path = DEFAULT_KEYS_DIR / "private.pem"
    public_key_file: Path = DEFAULT_KEYS_DIR / "public.pem"
    issuer: str = "aibird-auth"
    audience: str = "aibird-api"
    access_ttl_seconds: int = 3600
    refresh_ttl_seconds: int = 7 * 24 * 3600
    cors_origins: tuple[str, ...] = ()
    leeway_seconds: int = 10

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        kwargs: dict = {}
        if env.get("AIBIRD_DATABASE_URL"):
            kwargs["database_url"] = env["AIBIRD_DATABASE_URL"]
        if env.get("AUTH_PRIVATE_KEY_FILE"):
            kwargs["private_key_file"] = Path(env["AUTH_PRIVATE_KEY_FILE"])
        if env.get("AUTH_PUBLIC_KEY_FILE"):
            kwargs["public_key_file"] = Path(env["AUTH_PUBLIC_KEY_FILE"])
        if env.get("AUTH_ISSUER"):
            kwargs["issuer"] = env["AUTH_ISSUER"]
        if env.get("AUTH_AUDIENCE"):
            kwargs["audience"] = env["AUTH_AUDIENCE"]
        if env.get("AUTH_ACCESS_TTL_SECONDS"):
            kwargs["access_ttl_seconds"] = int(env["AUTH_ACCESS_TTL_SECONDS"])
        if env.get("AUTH_REFRESH_TTL_SECONDS"):
            kwargs["refresh_ttl_seconds"] = int(env["AUTH_REFRESH_TTL_SECONDS"])
        if "AUTH_CORS_ORIGINS" in env:
            kwargs["cors_origins"] = _split(env["AUTH_CORS_ORIGINS"])
        settings = cls(**kwargs)
        if "*" in settings.cors_origins:
            raise ValueError("AUTH_CORS_ORIGINS: '*' не допускается, нужен явный список адресов")
        return settings
