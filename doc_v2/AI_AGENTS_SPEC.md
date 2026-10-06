# AI_AGENTS_SPEC.md
# Техническое задание для ИИ-агентов реализации Cloud/Web части
Версия: 1.0
Статус: Утверждено для MVP
Привязка: `MVP_SPEC.md`, `ARCHITECTURE.md`, `TEAM.md`, `DATASET_STRATEGY.md`, `ROADMAP.md`
---

## 1. Назначение и область применения

Настоящий документ определяет роли ИИ-агентов (LLM-based coding agents), которые автоматизируют разработку облачной и веб-части системы акустического мониторинга миграции птиц.

Агенты **не заменяют** людей из `TEAM.md`, а работают под контролем соответствующих лидов, получая задачи, контекст и код-ревью.

### 1.1. Область действия

Документ покрывает реализацию:
- Cloud Layer (Ingestion, Processing Pipeline, Tracking Service, Storage).
- Application Layer (Web-платформа, REST API, B2B-отчёты).
- Модуля авторизации и RBAC.

Не покрывает:
- Edge-прошивку и hardware (ответственность CTO).
- Обучение моделей NN1/NN2/NN3 (ответственность Lead ML Engineer).
- Полевые операции (ответственность Field Operations).

### 1.2. Рамка MVP

- Срок: 4 месяца (8 спринтов по 2 недели).
- Команда: 6 человек + ИИ-агенты.
- Пилот: 5 датчиков, 50 видов, LoRaWAN + SD, без OTA, без ЕСИА.
- B2B-фокус: экологический комплаенс.

---

## 2. Общие принципы работы агентов

| Принцип | Описание |
|---|---|
| **Один агент — одна зона** | Каждый агент отвечает за свой модуль. Пересечения — только через утверждённые API-контракты. |
| **Контракты первичны** | Агент не меняет API-контракт или схему БД без согласования с Lead Backend. |
| **Единый конфиг окна анализа** | Любой агент, работающий со спектрограммами, обязан использовать параметры из `ARCHITECTURE.md` §2 (окно 2.5 сек, FFT 1024, hop 512, Hann, 44.1 кГц, log-mel). |
| **MVP-рамка** | Запрещено реализовывать функционал за пределами `MVP_SPEC.md`. |
| **Верификация человеком** | Каждый артефакт агента проходит ревью соответствующего лида перед мержем. |
| **Идемпотентность** | Все миграции, скрипты и деплой-шаги должны быть идемпотентными. |
| **Сквозная трассируемость** | Все операции логируются с `event_id`, `device_id`, `trace_id`. |

---

## 3. Карта агентов и взаимодействие

```
┌─────────────────────────────────────────────────────────────┐
│                    Lead Backend (человек)                   │
│              код-ревью, архитектура, приоритеты             │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────┘
       │          │          │          │          │
       ▼          ▼          ▼          ▼          ▼
  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
  │Agent DB│ │Agent   │ │Agent   │ │Agent   │ │Agent   │
  │        │ │Auth    │ │Backend │ │Pipeline│ │Tracking│
  └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘
      │          │          │          │          │
      ▼          ▼          ▼          ▼          ▼
┌─────────────────────────────────────────────────────────┐
│                    Agent Frontend                       │
│         React + Mapbox + GeoJSON + RBAC UI              │
└───────────────────────┬─────────────────────────────────┘
                        ▼
                 ┌──────────────┐
                 │  B2B Client  │
                 └──────────────┘
```

---

## 4. Роли и ТЗ по агентам

### 4.1. Agent DB — Агент баз данных

**Роль:** Проектирование, создание и поддержка схемы PostgreSQL + PostGIS + TimescaleDB. Генерация Alembic-миграций. Оптимизация запросов.

#### ТЗ

**Цель:** Реализовать полную схему БД для MVP согласно `ARCHITECTURE.md` §5 и API-контрактам.

**Входные данные:**
- Схема таблиц: `roles`, `users`, `clients`, `devices`, `events`, `bearings`, `tracks`, `track_events`, `telemetry`, `species`, `unknown_queue`, `maintenance_logs`.
- Требования к PostGIS: GIST-индексы, `GEOGRAPHY(POINT,4326)`, `GEOMETRY(LineString,4326)`.
- Требования к TimescaleDB: гипертаблицы `events`, `bearings`, `telemetry`; чанки по 1 неделе.
- Политики ретеншена: WAV в S3 — 12 мес, телеметрия — 24 мес.

**Выходные артефакты:**
1. Alembic-миграции (up/down) для всех таблиц.
2. SQL-скрипты создания гипертаблиц и GIST-индексов.
3. Скрипты политик ретеншена TimescaleDB.
4. Seed-скрипт: 4 роли, ≥50 видов с `red_book_flag`.
5. ER-диаграмма в Mermaid.

**Стек:** PostgreSQL 16, PostGIS 3.4, TimescaleDB 2.x, Alembic, SQLAlchemy (async), Python 3.12.

**Ограничения:**
- Не создавать ORM-модели бизнес-логики — только схемы и миграции.
- Все `UUID PRIMARY KEY DEFAULT gen_random_uuid()`.
- Все временные метки — `TIMESTAMPTZ`.
- Таблицы `events`, `bearings`, `telemetry` — гипертаблицы.
- GIST-индексы на `bearings.geom`, `tracks.geom`, `devices.installation_geo`.
- Не удалять старые миграции.

**Критерии приёмки:**
- [ ] `alembic upgrade head` выполняется без ошибок на чистой БД.
- [ ] `alembic downgrade base` откатывает всё без ошибок.
- [ ] `create_hypertable(...)` вызван для 3 таблиц.
- [ ] GIST-индексы созданы.
- [ ] Seed-скрипт загружает 4 роли и ≥50 видов.
- [ ] ER-диаграмма соответствует утверждённой схеме.

**Ревьюер:** Lead Backend & Data Engineer.

---

### 4.2. Agent Auth — Агент авторизации и RBAC

**Роль:** Реализация изолированного модуля авторизации. MVP: email/password + JWT (RS256). Архитектурно: отдельный сервис, заменяемый на Keycloak/ЕСИА (OIDC) в v1.1 без изменения контрактов.

#### ТЗ

**Цель:** Реализовать auth-модуль с JWT-аутентификацией и RBAC-middleware для FastAPI.

**Входные данные:**
- Ролевая модель: `super_admin`, `lead_ornithologist`, `field_engineer`, `b2b_client`.
- Схема таблиц `roles`, `users`, `clients`.
- API-контракты: `POST /api/v1/auth/login`, `/refresh`, `/logout`.
- JWT claims: `sub`, `email`, `role`, `client_id`, `permissions`, `exp`.

**Выходные артефакты:**
1. Модуль `auth_service/` с эндпоинтами login/refresh/logout.
2. Генерация RS256 JWT (access + refresh).
3. Middleware `require_role(*roles)` и `require_permission(*perms)`.
4. Декоратор `@require_scope("client")` — автофильтрация по `client_id` из JWT.
5. Хеширование паролей (bcrypt/argon2).
6. Тесты: unit + integration.
7. Документация перехода на OIDC в v1.1.

**Стек:** FastAPI, PyJWT, cryptography, Passlib + bcrypt, pytest, httpx.

**Ограничения:**
- Модуль **архитектурно изолирован**: другие сервисы работают только через JWT.
- Интерфейс `AuthProvider` с методом `authenticate(credentials) -> JWTClaims` — заглушка для будущей замены на OIDC.
- Refresh token в БД (таблица `refresh_tokens`), отзыв при logout.
- Access token TTL: 1 час. Refresh token TTL: 7 дней.
- Настраиваемый CORS whitelist.

**Критерии приёмки:**
- [ ] `POST /auth/login` возвращает валидный JWT с корректными claims.
- [ ] `POST /auth/refresh` обновляет access token.
- [ ] `POST /auth/logout` отзывает refresh token.
- [ ] Middleware блокирует истёкший токен (401).
- [ ] Middleware блокирует недостаточную роль (403).
- [ ] `@require_scope("client")` добавляет `WHERE client_id = :jwt_client_id`.
- [ ] Интерфейс `AuthProvider` позволяет подменить реализацию.
- [ ] ≥90% покрытие тестами.

**Ревьюер:** Lead Backend & Data Engineer + CTO.

---

### 4.3. Agent Backend — Агент серверной логики и API

**Роль:** Реализация REST API, MQTT ingestion, валидации данных, интеграции с S3, управления устройствами и ТО.

#### ТЗ

**Цель:** Реализовать FastAPI-сервер с полным набором MVP-эндпоинтов, MQTT-приём телеметрии и загрузку WAV.

**Входные данные:**
- API-контракты: Ingestion, Devices, Events, Bearings, Tracks, Unknown Queue, Export, Webhooks.
- MQTT topics: `birdnet/{device_id}/telemetry`, `/event`, `/heartbeat`.
- Схема БД (от Agent DB).
- JWT claims и middleware (от Agent Auth).
- Формат GeoJSON для ответов карты.
- `MVP_SPEC.md` §2.2 (Cloud Pipeline).

**Выходные артефакты:**
1. FastAPI-приложение с роутерами: `ingest`, `devices`, `events`, `tracks`, `unknown_queue`, `export`, `webhooks`.
2. MQTT-клиент (aiomqtt/paho-mqtt), парсинг payload, запись в `telemetry` и `events`.
3. Эндпоинт `POST /api/v1/ingest/wav`: multipart → S3 → Celery.
4. CRUD для `devices` и `maintenance_logs` с RBAC.
5. Эндпоинты Unknown Queue.
6. Export: GeoJSON, CSV, PDF-заглушка.
7. Webhook при `red_book_flag=True`.
8. Presigned S3 URL (TTL 15 мин).
9. Валидация: `device_id`, временные метки, дедупликация по `event_id`.
10. OpenAPI-спецификация (`/docs`).
11. Тесты: unit + integration.

**Стек:** FastAPI, Uvicorn, SQLAlchemy (async), Alembic, aiomqtt, boto3/aioboto3, Celery + Redis/RabbitMQ, httpx, pytest, testcontainers.

**Ограничения:**
- Не реализовывать ML-логику (NN2/NN3/Open-Set) — только постановка задач в Celery.
- Не реализовывать трекинг-логику — только CRUD для `tracks`.
- Все эндпоинты, кроме `/auth/*` и `/ingest/*`, защищены JWT.
- B2B-клиенты видят только данные своего `client_id` (через `@require_scope`).
- Пагинация: cursor-based для `events`/`telemetry`, offset для остального.
- Rate limiting: 100 req/min на пользователя.
- Структурированные JSON-логи (structlog).

**Критерии приёмки:**
- [ ] `POST /ingest/wav` загружает файл в S3, создаёт запись в `events` со статусом `queued`.
- [ ] MQTT-клиент принимает payload, валидирует и записывает в `telemetry`/`events`.
- [ ] `GET /events?bbox=...&species=...&from=...&to=...` возвращает GeoJSON.
- [ ] `GET /devices/{id}/telemetry` возвращает таймсерию из TimescaleDB.
- [ ] `POST /unknown-queue/{id}/verify` обновляет `events.nn3_species_id` и `unknown_queue.status`.
- [ ] Webhook отправляется при `species.red_book_flag=True`.
- [ ] B2B-клиент с `client_id=X` не видит события `client_id=Y`.
- [ ] OpenAPI-спецификация доступна на `/docs`.
- [ ] ≥80% покрытие тестами.

**Ревьюер:** Lead Backend & Data Engineer.

---

### 4.4. Agent Pipeline — Агент ML-пайплайна обработки аудио

**Роль:** Реализация облачного processing pipeline: приём WAV из очереди, прогон через NN2 → NN3 → Open-Set, сохранение результатов. Интеграция Direction QA.

#### ТЗ

**Цель:** Реализовать Celery-воркеры и сервисный слой для пакетной обработки аудио-событий.

**Входные данные:**
- `ARCHITECTURE.md` §5 (Processing Pipeline, Direction QA).
- `MVP_SPEC.md` §2.2 (Обработка аудио, Обработка направлений).
- `DATASET_STRATEGY.md` §6 (NN3: 50 видов + Unknown, ArcFace/Open-Set).
- Единый конфиг окна анализа: 2.5 сек, 44.1 кГц, FFT 1024, hop 512, Hann, log-mel.
- Модели NN2 и NN3 (предоставляются Lead ML Engineer как артефакты: ONNX/PyTorch weights + inference code).

**Выходные артефакты:**
1. Celery task `process_event(event_id)`:
   - Забрать WAV из S3 по `wav_s3_key`.
   - Прогнать через NN2 (source separation).
   - Fallback на оригинал при ухудшении SNR (проверка через SI-SDR или proxy).
   - Прогнать через NN3 (классификация).
   - Прогнать через Open-Set Detector.
   - Если Open-Set flag → `nn3_species_id=NULL`, `open_set_flag=True`.
   - Обновить запись в `events`.
   - Создать запись в `unknown_queue` при `open_set_flag=True`.
2. Celery task `direction_qa(event_id)`:
   - Проверка `azimuth_confidence` ≥ порога (дефолт 0.5).
   - Проверка согласованности `azimuth_geo_deg` с `orientation_deg` датчика.
   - Опциональный пересчёт направления в облаке (заглушка для MVP).
   - Обновление `bearings.bearing_quality`.
3. Сервис генерации спектрограмм для Web (PNG в S3, параметры из единого конфига).
4. Тесты с mock NN2/NN3.

**Стек:** Celery + Redis, PyTorch/ONNX Runtime, librosa/torchaudio, boto3, SQLAlchemy (async), numpy, scipy.

**Ограничения:**
- **Не обучать модели** — только инференс. Модели предоставляются Lead ML Engineer.
- Единый конфиг окна анализа — **из конфига**, не изобретать свои параметры.
- Время обработки одного события ≤ 20 секунд (`MVP_SPEC.md` §3).
- Пакетная обработка до 1000 событий за сессию.
- При ошибке модели событие помечается `quality_flag='pipeline_error'`, не теряется.
- Спектрограммы для Web: log-mel, PNG 800×400 px.

**Критерии приёмки:**
- [ ] `process_event` забирает WAV из S3, прогоняет NN2→NN3→Open-Set, обновляет `events`.
- [ ] Fallback: при ухудшении SNR после NN2 используется оригинал.
- [ ] Open-Set: неизвестный звук получает `open_set_flag=True`, `nn3_species_id=NULL`.
- [ ] `direction_qa` фильтрует low-confidence bearings.
- [ ] Спектрограмма генерируется с параметрами единого конфига.
- [ ] Обработка одного события ≤ 20 сек.
- [ ] При ошибке модели событие не теряется, помечается `pipeline_error`.
- [ ] ≥80% покрытие тестами (с mock-моделями).

**Ревьюер:** Lead ML Engineer / Audio AI + Lead Backend.

---

### 4.5. Agent Tracking — Агент сервиса трекинга

**Роль:** Реализация Tracking Service: группировка событий, построение пеленгов в PostGIS, фузия пеленгов от нескольких датчиков, формирование вероятностных треков и миграционных коридоров.

#### ТЗ

**Цель:** Реализовать Tracking Service, обрабатывающий события с пеленгами и строящий вероятностные траектории уровней L0–L3 согласно `ROADMAP.md` §5.

**Входные данные:**
- `ROADMAP.md` §5 (Уровни трекинга L0–L3).
- `ARCHITECTURE.md` §5 (Tracking Service).
- `MVP_SPEC.md` §2.2 (Трекинг).
- Схема БД: `events`, `bearings`, `tracks`, `track_events`.
- Локальные `track_id` с Edge (`events.local_track_id`).
- Параметры: max дальность пеленга 2–3 км, окно группировки 5 мин.

**Выходные артефакты:**
1. Сервис `tracking_service/` с функциями:
   - `group_events(device_id, time_window)` — группировка событий одного датчика.
   - `build_bearing_ray(event_id)` — LineString от `devices.installation_geo` под углом `bearings.azimuth_geo_deg`, длина = max_range (дефолт 3000 м).
   - `build_local_track(group)` — трек L1 из серии пеленгов одного датчика: circular mean азимут, дельта, флаг движения, геометрия.
   - `fuse_tracks(track_a, track_b)` — фузия L2: пересечение лучей от разных датчиков (ST_Intersection).
   - `build_migration_corridor(species_id, time_range)` — агрегация L3: кластеризация (DBSCAN), convex hull/buffer.
2. Периодическая задача (Celery Beat): запуск трекинга каждые 5 минут.
3. GeoJSON-генератор для треков.
4. Тесты с синтетическими данными.

**Стек:** PostGIS (ST_Project, ST_Intersection, ST_MakeLine, ST_Buffer, ST_ConvexHull, ST_DWithin), SQLAlchemy + GeoAlchemy2, Celery + Celery Beat, scikit-learn (DBSCAN), numpy, pytest.

**Ограничения:**
- Один датчик **не даёт точную позицию** — только пеленг (луч). Трек L1 — веер/полигон, не точка.
- Фузия L2 возможна только при ≥2 датчиках, засёкших одно событие (по времени ±30 сек и виду).
- **Circular mean** для азимутов (не арифметическое среднее!).
- Максимальная длина луча: 3000 м (настраивается).
- Не строить L3 при < 50 треках одного вида.
- Все геометрии в SRID 4326.

**Критерии приёмки:**
- [ ] `build_bearing_ray` создаёт LineString правильной длины и направления.
- [ ] `build_local_track` группирует события и создаёт трек L1 с корректным circular mean.
- [ ] `fuse_tracks` находит пересечение лучей двух датчиков и создаёт трек L2.
- [ ] `build_migration_corridor` не падает при < 50 треках (возвращает пустой результат).
- [ ] Celery Beat запускает трекинг каждые 5 минут.
- [ ] GeoJSON треков валиден и отображается на карте.
- [ ] Синтетический тест: 2 датчика на расстоянии 1 км, источник на известной позиции → пересечение лучей в пределах 200 м от истины.

**Ревьюер:** Lead Backend + Lead Ornithologist (валидация биологической осмысленности).

---

### 4.6. Agent Frontend — Агент веб-интерфейса и GIS-визуализации

**Роль:** Реализация React-приложения с интерактивной картой, слоями, карточками событий, аудио-плеером, очередью Unknown, экспортом и RBAC-интерфейсом.

#### ТЗ

**Цель:** Реализовать SPA на React, отображающее все слои карты и бизнес-интерфейс MVP согласно `MVP_SPEC.md` §2.3.

**Входные данные:**
- `MVP_SPEC.md` §2.3 (Обязательные экраны, Слои карты).
- API-контракты (REST, GeoJSON).
- JWT-токен от Agent Auth.
- Ролевая модель: 4 роли с разными наборами экранов.

**Выходные артефакты:**
1. React-приложение (Vite + TypeScript):
   - **Авторизация:** логин-форма, хранение JWT, авто-refresh, logout.
   - **Карта (Mapbox GL JS / Leaflet):**
     - Слой «Датчики» (точки, цвет по статусу).
     - Слой «Пеленги» (линии-лучи, прозрачность по confidence).
     - Слой «Треки L1» (полигоны/веера).
     - Слой «Треки L2» (точки/эллипсы пересечения).
     - Слой «Тепловая карта» (Kernel Density).
     - Слой «Миграционные коридоры L3» (полигоны).
     - Фильтры: вид, дата, датчик, качество, уверенность.
   - **Карточка события:** аудио-плеер (presigned URL), спектрограмма (PNG), метаданные, кнопка «Показать на карте».
   - **Очередь Unknown (только `lead_ornithologist`):** список событий с `open_set_flag=True`, плеер, спектрограмма, выпадающий список видов, кнопки «Подтвердить»/«Отклонить».
   - **Флот и ТО (только `field_engineer`):** карта датчиков, чек-лист ТО, история визитов.
   - **Экспорт (для `b2b_client`):** скачивание GeoJSON/CSV/PDF.
   - **Дашборд (базовый):** события за сегодня/неделю, топ-5 видов, статус батареи.
2. RBAC на фронтенде: скрытие/показ экранов по роли из JWT.
3. Тесты: Vitest + React Testing Library, E2E (Playwright, 3 базовых сценария).

**Стек:** React 18 + TypeScript + Vite, Mapbox GL JS (или Leaflet + react-leaflet), TanStack Query, Zustand/Context, Tailwind CSS/MUI, Vitest, Playwright.

**Ограничения:**
- Не реализовывать обработку аудио на фронте — только плеер и PNG-спектрограммы.
- Карта должна работать при 10 000+ точек (кластеризация на зуме < 12).
- Не хардкодить виды — загружать из API (`GET /species`).
- Аудио-плеер: стандартный HTML5 `<audio>` с presigned URL.
- RBAC на фронте — только UI-скрытие. Реальная проверка прав на бэкенде.
- Мобильная адаптация: базовая (responsive), не полноценное мобильное приложение.
- Не реализовывать анимацию миграционных потоков в MVP (бэклог v1.1).

**Критерии приёмки:**
- [ ] Логин → JWT → доступ к карте.
- [ ] Карта загружает и отображает все 5 слоёв из GeoJSON API.
- [ ] Клик по событию → карточка с плеером и спектрограммой.
- [ ] Фильтры по виду и дате работают.
- [ ] B2B-клиент не видит «Unknown Queue» и «Флот».
- [ ] Field Engineer видит только «Флот и ТО».
- [ ] Экспорт GeoJSON скачивает валидный файл.
- [ ] 10 000 точек на карте не вызывают freeze.
- [ ] ≥70% покрытие component-тестами.
- [ ] 3 E2E-сценария: логин → карта → карточка; логин → unknown queue → верификация; логин → экспорт.

**Ревьюер:** Full-Stack / GIS Developer + Lead Backend.

---

## 5. Матрица ответственности и зависимостей

| Агент | Зависит от | Поставляет для | Ревьюер |
|---|---|---|---|
| **Agent DB** | — (стартует первым) | Все агенты | Lead Backend |
| **Agent Auth** | DB (таблицы roles, users) | Backend, Frontend | Lead Backend + CTO |
| **Agent Backend** | DB, Auth | Frontend, Pipeline, Tracking | Lead Backend |
| **Agent Pipeline** | DB, Backend (S3 keys, queues), ML-модели от Lead ML | Backend (результаты в events) | Lead ML + Lead Backend |
| **Agent Tracking** | DB, Backend (events/bearings) | Frontend (GeoJSON треков) | Lead Backend + Орнитолог |
| **Agent Frontend** | Backend (API), Auth (JWT) | Пользователи | Full-Stack/GIS Dev + Lead Backend |

---

## 6. Порядок запуска по спринтам

Спринт 1–2 (Недели 1–4):
  Agent DB → Agent Auth → Agent Backend (ingest + devices) → Agent Frontend (карта датчиков)

Спринт 3–4 (Недели 5–8):
  Agent Pipeline (заглушка NN3) → Agent Tracking (L0–L1) → Agent Frontend (пеленги, треки)

Спринт 5–6 (Недели 9–12):
  Agent Pipeline (реальные модели) → Agent Tracking (L2–L3) → Agent Frontend (Unknown, Export)

Спринт 7–8 (Недели 13–16):
  Все агенты: багфиксы, тесты, нагрузочное тестирование, подготовка к пилоту

---

## 7. Общие правила для всех агентов

### 7.1. Единый конфиг окна анализа

Если агент генерирует или обрабатывает спектрограммы, параметры берутся из `config/window_config.yaml`:

```yaml
window_length_sec: 2.5
sample_rate: 44100
n_fft: 1024
hop_length: 512
window_function: hann
freq_max: 22050
representation: log_mel
```

Изменение этого файла требует синхронного обновления прошивки и датасета (правило из `ARCHITECTURE.md` §2 и `TEAM.md`).

### 7.2. Формат event_id

UUID v4, генерируется на Edge, передаётся через MQTT и REST, является сквозным идентификатором во всех таблицах.

### 7.3. Обработка ошибок

Все Celery-задачи имеют retry (max 3, exponential backoff). Необработанные ошибки → `quality_flag='error'` + запись в `error_log`.

### 7.4. Логирование

Структурированные JSON-логи с `event_id`, `device_id`, `trace_id` для сквозной трассировки.

### 7.5. Безопасность

- Все presigned URLs с TTL ≤ 15 мин.
- Никаких публичных S3-бакетов.
- TLS 1.3 для всех внешних соединений.
- Уникальные device-сертификаты для LoRaWAN.

### 7.6. Документация

Каждый агент ведёт `README.md` в своём модуле с инструкцией запуска, переменными окружения и примерами запросов.

---

## 8. Связь с другими документами

| Документ | Связь |
|---|---|
| `MVP_SPEC.md` | Определяет функциональные и нефункциональные требования, которые агенты обязаны соблюдать. |
| `ARCHITECTURE.md` | Определяет общую архитектуру, единый конфиг окна анализа, слои системы. |
| `TEAM.md` | Определяет роли людей-лидов, которые проводят ревью артефактов агентов. |
| `DATASET_STRATEGY.md` | Определяет параметры обучающих данных, которые должны совпадать с параметрами обработки в Agent Pipeline. |
| `ROADMAP.md` | Определяет уровни трекинга L0–L3, которые реализует Agent Tracking. |

---

## 9. Изменения документа

| Версия | Дата | Описание | Автор |
|---|---|---|---|
| 1.0 | 2026-10-01 | Первоначальная версия | CTO + Lead Backend |
