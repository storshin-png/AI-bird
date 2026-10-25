"""Треки, связь трек–события, очередь Unknown, журнал обслуживания

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25

Таблицы только создаются. Логику трекинга и очереди пишут другие пакеты.

Ссылки на события (track_events, unknown_queue) хранят пару
(event_id, timestamp_utc), но без внешнего ключа: events — гипертаблица,
и её первичный ключ составной. Пара позволяет найти событие по ключу
и сразу попасть в нужный чанк.

Поля трека — USERFLOW.md §5.6 и MVP_SPEC.md §2.1 (локальный трек):
track_id с устройства хранится в local_track_id, mean_bearing,
bearing_change, track_confidence, motion_flag.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tracks (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            device_id        TEXT REFERENCES devices (device_id) ON DELETE RESTRICT,
            client_id        UUID REFERENCES clients (id) ON DELETE RESTRICT,
            local_track_id   TEXT,
            level            TEXT NOT NULL DEFAULT 'L0'
                CHECK (level IN ('L0', 'L1', 'L2', 'L3')),
            start_time       TIMESTAMPTZ NOT NULL,
            end_time         TIMESTAMPTZ,
            mean_bearing     DOUBLE PRECISION
                CHECK (mean_bearing >= 0 AND mean_bearing < 360),
            bearing_change   DOUBLE PRECISION,
            track_confidence DOUBLE PRECISION
                CHECK (track_confidence BETWEEN 0 AND 1),
            motion_flag      TEXT NOT NULL DEFAULT 'unknown'
                CHECK (motion_flag IN ('moving', 'stationary', 'unknown')),
            species_id       UUID REFERENCES species (id) ON DELETE RESTRICT,
            geom             GEOMETRY(LINESTRING, 4326),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (end_time IS NULL OR end_time >= start_time)
        )
        """
    )
    op.execute("CREATE INDEX tracks_geom_gist ON tracks USING GIST (geom)")
    op.execute("CREATE INDEX tracks_time_idx ON tracks (start_time DESC)")
    op.execute("CREATE INDEX tracks_client_time_idx ON tracks (client_id, start_time DESC)")
    op.execute(
        "CREATE UNIQUE INDEX tracks_device_local_uq ON tracks (device_id, local_track_id) "
        "WHERE local_track_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE track_events (
            track_id      UUID NOT NULL REFERENCES tracks (id) ON DELETE CASCADE,
            event_id      UUID NOT NULL,
            timestamp_utc TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (track_id, event_id)
        )
        """
    )
    op.execute("CREATE INDEX track_events_event_idx ON track_events (event_id, timestamp_utc)")

    op.execute(
        """
        CREATE TABLE unknown_queue (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id             UUID NOT NULL UNIQUE,
            timestamp_utc        TIMESTAMPTZ NOT NULL,
            status               TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'verified', 'rejected')),
            suggested_species_id UUID REFERENCES species (id) ON DELETE RESTRICT,
            verified_species_id  UUID REFERENCES species (id) ON DELETE RESTRICT,
            verified_by          UUID REFERENCES users (id) ON DELETE SET NULL,
            verified_at          TIMESTAMPTZ,
            comment              TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX unknown_queue_status_idx ON unknown_queue (status, created_at)")

    op.execute(
        """
        CREATE TABLE maintenance_logs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            device_id       TEXT NOT NULL REFERENCES devices (device_id) ON DELETE RESTRICT,
            performed_by    UUID REFERENCES users (id) ON DELETE SET NULL,
            performed_at    TIMESTAMPTZ NOT NULL,
            kind            TEXT NOT NULL
                CHECK (kind IN ('installation', 'inspection', 'repair', 'battery',
                                'calibration', 'removal', 'other')),
            orientation_deg DOUBLE PRECISION
                CHECK (orientation_deg >= 0 AND orientation_deg < 360),
            notes           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX maintenance_logs_device_time_idx "
        "ON maintenance_logs (device_id, performed_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS maintenance_logs")
    op.execute("DROP TABLE IF EXISTS unknown_queue")
    op.execute("DROP TABLE IF EXISTS track_events")
    op.execute("DROP TABLE IF EXISTS tracks")
