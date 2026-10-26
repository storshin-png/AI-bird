"""Окружение Alembic для схемы AI-bird.

ORM-моделей нет: миграции пишутся явным SQL, поэтому target_metadata = None
и автогенерация не используется.
"""

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

STAND_ENV = Path(__file__).resolve().parents[2] / ".env.example"


def _stand_url() -> str:
    """Адрес локального стенда из cloud/.env.example."""
    values = {}
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


def database_url() -> str:
    return os.environ.get("AIBIRD_DATABASE_URL") or _stand_url()


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
