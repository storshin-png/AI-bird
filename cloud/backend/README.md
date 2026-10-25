# backend

Приём телеметрии с датчиков по MQTT и REST устройств. Спецификация — `doc_v2/AI_AGENTS_SPEC.md` §4.3, пакет «приём телеметрии MQTT и устройств» из `doc_v2/agents/04_BACKEND.md`.

Здесь нет пайплайна NN2/NN3, логики треков и приёма WAV — это следующие пакеты.

## Что внутри

| Файл | Что делает |
|---|---|
| `mqtt.py` | Подписка на `birdnet/+/telemetry`, `/event`, `/heartbeat`, переподключение к брокеру |
| `payloads.py` | Разбор темы и проверка пакета |
| `ingest.py` | Запись в `telemetry`, `events`, `bearings`, дедупликация |
| `api.py` | REST устройств, журнала обслуживания и телеметрии |
| `logs.py` | JSON-логи structlog с `trace_id`, `device_id`, `event_id` |
| `docs/MQTT_PAYLOADS.md` | Формат пакетов и причины отказа — черновик для CTO |

## Подготовка, один раз

Стенд запущен, миграции применены, ключи созданы (`cloud/README.md`, `auth_service/README.md`). Из каталога `cloud/` с активным окружением:

```text
pip install -r backend/requirements-dev.txt
```

## Запуск

Из каталога `cloud/`, каждая команда в своём окне терминала:

```text
uvicorn --factory auth_service.app:create_app --port 8001 --loop asyncio:SelectorEventLoop
uvicorn --factory backend.app:create_app --port 8000 --loop asyncio:SelectorEventLoop
python -m backend mqtt
```

Первая — вход и токены, вторая — REST устройств, третья — приём MQTT. `--loop asyncio:SelectorEventLoop` нужен на Windows: без него драйвер PostgreSQL в async-режиме не работает.

Документация OpenAPI: http://127.0.0.1:8000/docs

## Переменные окружения

Все необязательные. Без них сервис работает со стендом.

| Переменная | По умолчанию | Что задаёт |
|---|---|---|
| `AIBIRD_DATABASE_URL` | стенд из `cloud/.env.example` | Адрес БД |
| `AUTH_PUBLIC_KEY_FILE` | `auth_service/keys/public.pem` | Ключ для проверки токенов |
| `MQTT_HOST` | `127.0.0.1` | Брокер |
| `MQTT_PORT` | `1883` | |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | нет | На стенде брокер без пароля |
| `MQTT_CLIENT_ID` | `aibird-ingest` | |
| `MQTT_TOPIC_PREFIX` | `birdnet` | |
| `INGEST_MAX_FUTURE_SKEW_SECONDS` | `300` | Насколько время пакета может опережать сервер |
| `BACKEND_CORS_ORIGINS` | пусто | Адреса фронтенда через запятую |

## Проверка руками

Завести датчик (токен — из `POST /api/v1/auth/login`, роль `super_admin` или `field_engineer`):

```text
curl -X POST http://127.0.0.1:8000/api/v1/devices -H "Authorization: Bearer <токен>" -H "Content-Type: application/json" -d "{\"device_id\":\"sensor-001\",\"latitude\":53.41,\"longitude\":58.98,\"status\":\"active\"}"
```

Отправить пакет в брокер стенда:

```text
docker compose exec mqtt mosquitto_pub -t birdnet/sensor-001/telemetry -q 1 -m "{\"timestamp_utc\":\"2026-10-25T03:15:27Z\",\"battery_v\":3.71}"
```

В окне `python -m backend mqtt` появится строка с `"event": "stored"`. Таймсерия:

```text
curl http://127.0.0.1:8000/api/v1/devices/sensor-001/telemetry -H "Authorization: Bearer <токен>"
```

## REST

| Метод и путь | Право | Что делает |
|---|---|---|
| `GET /api/v1/devices` | `devices:read` | Список; `?format=geojson` — FeatureCollection для карты; `status`, `limit`, `offset` |
| `GET /api/v1/devices/{device_id}` | `devices:read` | Один датчик |
| `POST /api/v1/devices` | `devices:write` | Завести датчик |
| `PATCH /api/v1/devices/{device_id}` | `devices:write` | Изменить; координаты меняются парой |
| `DELETE /api/v1/devices/{device_id}` | `devices:write` | Удалить датчик без данных; с данными — 409, списывать через `status: retired` |
| `GET /api/v1/devices/{device_id}/maintenance` | `devices:read` | Журнал обслуживания |
| `POST /api/v1/devices/{device_id}/maintenance` | `maintenance:write` | Запись в журнал |
| `GET /api/v1/devices/{device_id}/telemetry` | `telemetry:read` | Таймсерия; `from`, `to`, `limit`, `cursor` из `next_cursor` |

B2B-клиент видит только датчики своего `client_id`. В черновике прав у клиента нет `devices:read`, поэтому сейчас эти адреса ему отвечают 403.

## Тесты

Из каталога `cloud/`:

```text
pytest backend auth_service --cov=backend --cov=auth_service
```

Тесты с БД и брокером запускаются, если заданы адреса:

PowerShell:

```text
$env:AIBIRD_TEST_DATABASE_URL = "postgresql+psycopg://aibird:aibird-stand@127.0.0.1:5432/aibird"
$env:AIBIRD_TEST_MQTT = "127.0.0.1:1883"
pytest backend auth_service --cov=backend --cov=auth_service
```

Linux и macOS:

```text
AIBIRD_TEST_DATABASE_URL=postgresql+psycopg://aibird:aibird-stand@127.0.0.1:5432/aibird AIBIRD_TEST_MQTT=127.0.0.1:1883 pytest backend auth_service --cov=backend --cov=auth_service
```

Тесты создают датчики с уникальным префиксом и удаляют их за собой. Брокерные тесты публикуют в свою ветку тем, а не в `birdnet/`.

## Известные ограничения

- Пакет подтверждается брокеру при получении. Если БД недоступна, пакет уходит в лог как `db_error` и не повторяется. Для пилота телеметрия дублируется на SD-карте; ручное подтверждение после записи — задача спринта 3 вместе с валидацией.
- Луч пеленга (`bearings.geom`) не строится: это Direction QA и трекинг, спринты 5–6.
- Счётчики приёма пока только в логе при остановке; метрики — вместе с мониторингом.
