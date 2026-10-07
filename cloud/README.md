# Облако

Локальный стенд подготовки. Миграций, API и моделей в этом пакете нет. Трекинг не входит.

## Состав

| Сервис | Образ | Порт на этой машине |
|---|---|---|
| PostgreSQL 16.4, PostGIS 3.4, TimescaleDB 2.17.2 | сборка `postgres/` | 127.0.0.1:5432 |
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
