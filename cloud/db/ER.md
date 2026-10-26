# ER-диаграмма схемы MVP

Источник — миграции `migrations/versions/0001`–`0006`. Требования — `doc_v2/AI_AGENTS_SPEC.md` §4.1.

Сплошная связь — внешний ключ в БД. Пунктир — ссылка по `event_id` и `timestamp_utc` без внешнего ключа: `events` — гипертаблица TimescaleDB с составным ключом.

`events`, `bearings` и `telemetry` — гипертаблицы, чанки по 1 неделе. Телеметрия хранится 24 месяца. WAV в объектном хранилище — 12 месяцев, правилом бакета.

```mermaid
erDiagram
    roles ||--o{ users : "role_id"
    clients |o--o{ users : "client_id"
    clients |o--o{ devices : "client_id"
    clients |o--o{ events : "client_id"
    clients |o--o{ tracks : "client_id"

    devices ||--o{ events : "device_id"
    devices ||--o{ bearings : "device_id"
    devices ||--o{ telemetry : "device_id"
    devices |o--o{ tracks : "device_id"
    devices ||--o{ maintenance_logs : "device_id"
    users |o--o{ maintenance_logs : "performed_by"

    species |o--o{ events : "nn3_species_id"
    species |o--o{ tracks : "species_id"
    species |o--o{ unknown_queue : "suggested / verified"
    users |o--o{ unknown_queue : "verified_by"
    users ||--o{ refresh_tokens : "user_id"

    tracks ||--o{ track_events : "track_id"
    events ||..o{ bearings : "event_id"
    events ||..o{ track_events : "event_id"
    events ||..o| unknown_queue : "event_id"
    events ||..o{ telemetry : "event_id"

    roles {
        uuid id PK
        text name UK
        text description
        timestamptz created_at
    }
    clients {
        uuid id PK
        text name
        text contact_email
        bool is_active
        timestamptz created_at
        timestamptz updated_at
    }
    users {
        uuid id PK
        text email UK "lower(email)"
        text password_hash
        text full_name
        uuid role_id FK
        uuid client_id FK
        bool is_active
        timestamptz last_login_at
        timestamptz created_at
        timestamptz updated_at
    }
    species {
        uuid id PK
        text scientific_name UK
        text common_name_ru
        bool red_book_flag
        bool in_pilot_50
        timestamptz created_at
    }
    devices {
        uuid id PK
        text device_id UK "идентификатор с устройства"
        uuid client_id FK
        text name
        geography installation_geo "POINT 4326, GIST"
        float orientation_deg
        timestamptz installed_at
        text status
        text firmware_version
        text notes
        timestamptz created_at
        timestamptz updated_at
    }
    events {
        uuid event_id PK "с устройства"
        timestamptz timestamp_utc PK "гипертаблица"
        text device_id FK
        uuid client_id FK
        bool bird_flag
        float bird_probability
        float snr_db
        jsonb channel_levels
        text quality_flag
        text track_id "локальный трек с устройства"
        text wav_s3_key
        text status "received, queued, processing, done, error"
        uuid nn3_species_id FK
        float nn3_confidence
        bool open_set_flag
        timestamptz received_at
        timestamptz updated_at
    }
    bearings {
        uuid id PK
        timestamptz timestamp_utc PK "гипертаблица"
        uuid event_id
        text device_id FK
        float azimuth_device_deg
        float azimuth_geo_deg
        text sector
        float azimuth_confidence
        text bearing_quality
        text source "edge, cloud"
        geometry geom "LINESTRING 4326, GIST"
        timestamptz created_at
    }
    telemetry {
        uuid id PK
        timestamptz timestamp_utc PK "гипертаблица, 24 мес"
        text device_id FK
        float battery_v
        float temperature_c
        bool bird_flag
        float bird_probability
        float azimuth_geo_deg
        float azimuth_confidence
        text track_id
        text quality_flag
        uuid event_id
        timestamptz received_at
    }
    tracks {
        uuid id PK
        text device_id FK
        uuid client_id FK
        text local_track_id
        text level "L0-L3"
        timestamptz start_time
        timestamptz end_time
        float mean_bearing
        float bearing_change
        float track_confidence
        text motion_flag
        uuid species_id FK
        geometry geom "LINESTRING 4326, GIST"
        timestamptz created_at
        timestamptz updated_at
    }
    track_events {
        uuid track_id PK, FK
        uuid event_id PK
        timestamptz timestamp_utc
    }
    unknown_queue {
        uuid id PK
        uuid event_id UK
        timestamptz timestamp_utc
        text status "pending, verified, rejected"
        uuid suggested_species_id FK
        uuid verified_species_id FK
        uuid verified_by FK
        timestamptz verified_at
        text comment
        timestamptz created_at
        timestamptz updated_at
    }
    refresh_tokens {
        uuid jti PK "jti из JWT"
        uuid user_id FK
        timestamptz issued_at
        timestamptz expires_at
        timestamptz revoked_at
        uuid replaced_by
    }
    maintenance_logs {
        uuid id PK
        text device_id FK
        uuid performed_by FK
        timestamptz performed_at
        text kind
        float orientation_deg
        text notes
        timestamptz created_at
    }
```
