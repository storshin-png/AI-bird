"""Расширения и справочные таблицы: roles, clients, users, species, devices

Revision ID: 0001
Revises:
Create Date: 2026-10-25

Схема — doc_v2/AI_AGENTS_SPEC.md §4.1. Первичные ключи UUID с
gen_random_uuid(), время TIMESTAMPTZ.

devices.device_id — идентификатор с устройства (как в телеметрии
MVP_SPEC.md §2.1). Его имя не меняется: events, bearings, telemetry и
maintenance_logs ссылаются на devices.device_id.
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # timescaledb создаёт init-скрипт стенда; IF NOT EXISTS — для чистой БД без него.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.execute(
        """
        CREATE TABLE roles (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name        TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE clients (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name          TEXT NOT NULL,
            contact_email TEXT,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE users (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email         TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            full_name     TEXT,
            role_id       UUID NOT NULL REFERENCES roles (id) ON DELETE RESTRICT,
            client_id     UUID REFERENCES clients (id) ON DELETE RESTRICT,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            last_login_at TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX users_email_lower_uq ON users (lower(email))")
    op.execute("CREATE INDEX users_role_id_idx ON users (role_id)")
    op.execute("CREATE INDEX users_client_id_idx ON users (client_id)")

    # Колонки совпадают с заголовком data/species/species.csv.
    op.execute(
        """
        CREATE TABLE species (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            scientific_name TEXT NOT NULL UNIQUE,
            common_name_ru  TEXT,
            red_book_flag   BOOLEAN NOT NULL DEFAULT false,
            in_pilot_50     BOOLEAN NOT NULL DEFAULT false,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX species_red_book_idx ON species (red_book_flag) WHERE red_book_flag"
    )

    op.execute(
        """
        CREATE TABLE devices (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            device_id        TEXT NOT NULL UNIQUE,
            client_id        UUID REFERENCES clients (id) ON DELETE RESTRICT,
            name             TEXT,
            installation_geo GEOGRAPHY(POINT, 4326),
            orientation_deg  DOUBLE PRECISION
                CHECK (orientation_deg >= 0 AND orientation_deg < 360),
            installed_at     TIMESTAMPTZ,
            status           TEXT NOT NULL DEFAULT 'registered'
                CHECK (status IN ('registered', 'active', 'maintenance', 'retired')),
            firmware_version TEXT,
            notes            TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX devices_installation_geo_gist ON devices USING GIST (installation_geo)"
    )
    op.execute("CREATE INDEX devices_client_id_idx ON devices (client_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS devices")
    op.execute("DROP TABLE IF EXISTS species")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS clients")
    op.execute("DROP TABLE IF EXISTS roles")
    # timescaledb остаётся: его ставит init-скрипт стенда, а не миграции.
    op.execute("DROP EXTENSION IF EXISTS postgis")
