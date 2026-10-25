# Облако

Локальный стенд подготовки и схема БД MVP. API и моделей пока нет. Трекинг не входит.

## Состав

| Сервис | Образ | Порт на этой машине |
|---|---|---|
| PostgreSQL 16.15, PostGIS 3.4, TimescaleDB 2.17.2 | сборка `postgres/` | 127.0.0.1:5432 |
| Брокер MQTT | `eclipse-mosquitto:2.0` | 127.0.0.1:1883 |
| Хранилище, совместимое с S3 | `pgsty/silo:RELEASE.2026-09-16T00-00-00Z` | API 127.0.0.1:9000, консоль 127.0.0.1:9001 |
| Redis | `redis:7.4-alpine` | 127.0.0.1:6379 |

Образ `minio/minio` с открытых реестров больше не скачивается. Silo принимает те же `MINIO_ROOT_USER` и `MINIO_ROOT_PASSWORD` и ту же команду `server /data`.

Пароли лежат в `.env.example` и годятся только для этого стенда. Порты слушаются на `127.0.0.1`. Брокер MQTT на стенде без пароля: слушатель доступен только с этой машины.

Повторный `docker compose up -d` поднимает те же сервисы. Именованные тома создаёт Compose, править их вручную не нужно.

## Запуск

Из каталога `cloud/`:

```text
docker compose up -d
```

## Остановка

Из каталога `cloud/`:

```text
docker compose down
```

Данные в томах остаются. `docker compose down -v` удаляет тома стенда.

## Проверка

```text
docker compose ps
docker compose exec postgres psql -U aibird -d aibird -c "SHOW server_version;"
docker compose exec postgres psql -U aibird -d aibird -c "SELECT PostGIS_Lib_Version();"
docker compose exec postgres psql -U aibird -d aibird -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';"
docker compose exec redis redis-cli -a aibird-stand-redis ping
docker compose exec mqtt mosquitto_pub -h 127.0.0.1 -t stand/ping -m ok
```

Консоль хранилища: http://127.0.0.1:9001

## Схема БД

Миграции Alembic лежат в `db/`. ER-диаграмма — `db/ER.md`.

| Миграция | Что делает |
|---|---|
| `0001` | PostGIS; `roles`, `clients`, `users`, `species`, `devices` |
| `0002` | Гипертаблицы `events`, `bearings`, `telemetry` с чанками по 1 неделе; ретеншен телеметрии 24 месяца |
| `0003` | `tracks`, `track_events`, `unknown_queue`, `maintenance_logs` |
| `0004` | Seed четырёх ролей: `super_admin`, `lead_ornithologist`, `field_engineer`, `b2b_client` |

Таблица `species` создаётся пустой. Виды загружаются отдельной миграцией, когда в `doc_v2/IMPLEMENTATION_PLAN.md` §8 закрыт список 50 видов.

WAV в объектном хранилище живут 12 месяцев. Это правило бакета, оно задаётся вместе с приёмом WAV, а не в этих миграциях.

### Подготовка, один раз

Нужен Python 3.12. Из каталога `cloud/db/`:

Windows, PowerShell:

```text
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux и macOS:

```text
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Каталог `.venv/` в git не попадает.

### Применить и откатить

Стенд должен быть запущен (`docker compose up -d` из `cloud/`). Из каталога `cloud/db/` с активным окружением:

```text
alembic upgrade head
alembic downgrade base
```

Без переменных окружения Alembic подключается к стенду на `127.0.0.1:5432` с логином и паролем из `cloud/.env.example`. Другая БД задаётся переменной `AIBIRD_DATABASE_URL`, например `postgresql+psycopg://user:pass@host:5432/db`.

Текущая версия схемы:

```text
alembic current
```

### Проверка схемы

```text
docker compose exec postgres psql -U aibird -d aibird -c "SELECT hypertable_name FROM timescaledb_information.hypertables;"
docker compose exec postgres psql -U aibird -d aibird -c "SELECT tablename, indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE '%_gist';"
docker compose exec postgres psql -U aibird -d aibird -c "SELECT hypertable_name, config FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention';"
docker compose exec postgres psql -U aibird -d aibird -c "SELECT name FROM roles ORDER BY name;"
```

Ожидается: три гипертаблицы, три GIST-индекса (`devices`, `bearings`, `tracks`), одна политика ретеншена для `telemetry`, четыре роли.
