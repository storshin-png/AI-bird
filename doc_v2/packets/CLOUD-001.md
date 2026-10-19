# CLOUD-001. Схема базы стенда

Статус: открыт
Дата: 2026-10-19
Кто выдал: руководитель проекта (`project-lead`)
Исполнитель: `backend-agent`
Зона: `cloud/`
Ветка: `cloud/schema`
Направление: `doc_v2/directions/2026-10-07-prep.md`, спринт 1
ТЗ: `doc_v2/agents/04_BACKEND.md`, первый из трёх запросов
Спека: `doc_v2/AI_AGENTS_SPEC.md` §4.1, таблицы из `doc_v2/ARCHITECTURE.md` §5
Вливает: CEO, GitHub `storshin-png`

## Входы

- стенд `cloud/docker-compose.yml` уже в `main`
- `doc_v2/AI_AGENTS_SPEC.md` §4.1
- `data/species/species.csv` — только заголовок, строк видов нет

## Сделать

Alembic-миграции схемы MVP: `roles`, `users`, `clients`, `devices`, `events`, `bearings`, `tracks`, `track_events`, `telemetry`, `species`, `unknown_queue`, `maintenance_logs`.

`events`, `bearings` и `telemetry` — гипертаблицы TimescaleDB, чанки по 1 неделе. GIST-индексы на географию, как в §4.1. Первичные ключи — UUID, время — `TIMESTAMPTZ`. Политики ретеншена из §4.1 описать в миграциях. ER-диаграмму в Mermaid положить в `cloud/`.

Seed: четыре роли `super_admin`, `lead_ornithologist`, `field_engineer`, `b2b_client`. Загрузка видов пустая: таблица `species` создаётся, строки не выдумываются.

## Границы

Auth §4.2 и приём телеметрии §4.3 в этот пакет не входят. Поля события и `event_id` не переименовывать. Окно анализа не менять. ORM бизнес-логики, API и модели не писать. Секреты и WAV не коммитить. Diff только в `cloud/`.

Пункт §4.1 «не меньше 50 видов в seed» закрывает орнитолог. Пока в `doc_v2/IMPLEMENTATION_PLAN.md` §8 список видов открыт, агент виды не заполняет.

## Проверка

На чистой БД стенда:

```text
alembic upgrade head
alembic downgrade base
```

Команды и способ вызова записать в `cloud/README.md`. Один pull request, описание по шаблону GitHub.
