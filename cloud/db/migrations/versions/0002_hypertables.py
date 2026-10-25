"""Гипертаблицы TimescaleDB: events, bearings, telemetry

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25

Чанки по 1 неделе (AI_AGENTS_SPEC.md §4.1).

Имена полей взяты без переименования из MVP_SPEC.md §2.1 (телеметрия и
направление) и ARCHITECTURE.md §3 (выход Direction Estimation).

TimescaleDB требует, чтобы колонка времени входила в каждый уникальный
ключ гипертаблицы. Поэтому первичные ключи составные: (event_id,
timestamp_utc) у events и (id, timestamp_utc) у bearings и telemetry.
Повтор того же MQTT-пакета несёт тот же event_id и то же время, так что
дубликат упирается в этот ключ.

event_id создаётся на устройстве (UUID v4, AI_AGENTS_SPEC.md §7.2), поэтому
у events.event_id нет DEFAULT: событие без идентификатора должно падать,
а не получать новый идентификатор в облаке.

Ретеншен:
- telemetry — 24 месяца, политика TimescaleDB ниже;
- events и bearings — без автоудаления, это научные данные пилота;
- WAV в объектном хранилище — 12 месяцев. Это правило жизненного цикла
  бакета S3, а не таблицы: оно задаётся вместе с приёмом WAV
  (POST /ingest/wav, AI_AGENTS_SPEC.md §4.3). Колонка wav_s3_key хранит
  только ключ объекта.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CHUNK = "INTERVAL '1 week'"
TELEMETRY_RETENTION = "INTERVAL '24 months'"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE events (
            event_id         UUID NOT NULL,
            timestamp_utc    TIMESTAMPTZ NOT NULL,
            device_id        TEXT NOT NULL REFERENCES devices (device_id) ON DELETE RESTRICT,
            client_id        UUID REFERENCES clients (id) ON DELETE RESTRICT,
            bird_flag        BOOLEAN,
            bird_probability DOUBLE PRECISION
                CHECK (bird_probability BETWEEN 0 AND 1),
            snr_db           DOUBLE PRECISION,
            channel_levels   JSONB,
            quality_flag     TEXT,
            track_id         TEXT,
            wav_s3_key       TEXT,
            status           TEXT NOT NULL DEFAULT 'received'
                CHECK (status IN ('received', 'queued', 'processing', 'done', 'error')),
            nn3_species_id   UUID REFERENCES species (id) ON DELETE RESTRICT,
            nn3_confidence   DOUBLE PRECISION
                CHECK (nn3_confidence BETWEEN 0 AND 1),
            open_set_flag    BOOLEAN,
            received_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (event_id, timestamp_utc)
        )
        """
    )
    op.execute(
        f"SELECT create_hypertable('events', by_range('timestamp_utc', {CHUNK}))"
    )
    op.execute("CREATE INDEX events_event_id_idx ON events (event_id)")
    op.execute("CREATE INDEX events_device_time_idx ON events (device_id, timestamp_utc DESC)")
    op.execute("CREATE INDEX events_client_time_idx ON events (client_id, timestamp_utc DESC)")
    op.execute("CREATE INDEX events_species_idx ON events (nn3_species_id, timestamp_utc DESC)")
    op.execute(
        "CREATE INDEX events_status_idx ON events (status, timestamp_utc DESC) "
        "WHERE status <> 'done'"
    )

    op.execute(
        """
        CREATE TABLE bearings (
            id                 UUID NOT NULL DEFAULT gen_random_uuid(),
            event_id           UUID NOT NULL,
            timestamp_utc      TIMESTAMPTZ NOT NULL,
            device_id          TEXT NOT NULL REFERENCES devices (device_id) ON DELETE RESTRICT,
            azimuth_device_deg DOUBLE PRECISION
                CHECK (azimuth_device_deg >= 0 AND azimuth_device_deg < 360),
            azimuth_geo_deg    DOUBLE PRECISION NOT NULL
                CHECK (azimuth_geo_deg >= 0 AND azimuth_geo_deg < 360),
            sector             TEXT
                CHECK (sector IN ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')),
            azimuth_confidence DOUBLE PRECISION
                CHECK (azimuth_confidence BETWEEN 0 AND 1),
            bearing_quality    TEXT
                CHECK (bearing_quality IN ('good', 'medium', 'poor', 'ambiguous')),
            source             TEXT NOT NULL DEFAULT 'edge'
                CHECK (source IN ('edge', 'cloud')),
            geom               GEOMETRY(LINESTRING, 4326),
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, timestamp_utc)
        )
        """
    )
    op.execute(
        f"SELECT create_hypertable('bearings', by_range('timestamp_utc', {CHUNK}))"
    )
    op.execute("CREATE INDEX bearings_geom_gist ON bearings USING GIST (geom)")
    op.execute("CREATE INDEX bearings_event_id_idx ON bearings (event_id)")
    op.execute("CREATE INDEX bearings_device_time_idx ON bearings (device_id, timestamp_utc DESC)")

    op.execute(
        """
        CREATE TABLE telemetry (
            id                 UUID NOT NULL DEFAULT gen_random_uuid(),
            timestamp_utc      TIMESTAMPTZ NOT NULL,
            device_id          TEXT NOT NULL REFERENCES devices (device_id) ON DELETE RESTRICT,
            battery_v          DOUBLE PRECISION,
            temperature_c      DOUBLE PRECISION,
            bird_flag          BOOLEAN,
            bird_probability   DOUBLE PRECISION
                CHECK (bird_probability BETWEEN 0 AND 1),
            azimuth_geo_deg    DOUBLE PRECISION
                CHECK (azimuth_geo_deg >= 0 AND azimuth_geo_deg < 360),
            azimuth_confidence DOUBLE PRECISION
                CHECK (azimuth_confidence BETWEEN 0 AND 1),
            track_id           TEXT,
            quality_flag       TEXT,
            event_id           UUID,
            received_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, timestamp_utc)
        )
        """
    )
    op.execute(
        f"SELECT create_hypertable('telemetry', by_range('timestamp_utc', {CHUNK}))"
    )
    op.execute("CREATE INDEX telemetry_device_time_idx ON telemetry (device_id, timestamp_utc DESC)")
    op.execute("CREATE INDEX telemetry_event_id_idx ON telemetry (event_id) WHERE event_id IS NOT NULL")
    op.execute(
        f"SELECT add_retention_policy('telemetry', drop_after => {TELEMETRY_RETENTION})"
    )


def downgrade() -> None:
    op.execute("SELECT remove_retention_policy('telemetry', if_exists => true)")
    op.execute("DROP TABLE IF EXISTS telemetry")
    op.execute("DROP TABLE IF EXISTS bearings")
    op.execute("DROP TABLE IF EXISTS events")
