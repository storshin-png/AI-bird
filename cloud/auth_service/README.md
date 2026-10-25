# auth_service

Вход по email и паролю, JWT RS256, роли и права. Спецификация — `doc_v2/AI_AGENTS_SPEC.md` §4.2.

Другие сервисы с модулем не связаны напрямую. Они проверяют подпись токена публичным ключом и читают claims. Ключ берётся из файла `public.pem` или из `GET /api/v1/auth/.well-known/jwks.json`.

## Что внутри

| Файл | Что делает |
|---|---|
| `api.py` | `POST /login`, `/refresh`, `/logout`, `GET /me`, `GET /.well-known/jwks.json` под `/api/v1/auth` |
| `provider.py` | Интерфейс `AuthProvider.authenticate(credentials) -> JWTClaims` и вход по паролю |
| `tokens.py` | Выпуск и проверка access (1 час) и refresh (7 дней), RS256 |
| `deps.py` | `get_current_claims`, `require_role`, `require_permission`, `require_scope("client")` |
| `roles.py` | Четыре роли и права, которые попадают в claim `permissions` |
| `store.py` | Запросы к `users`, `roles`, `refresh_tokens` |
| `cli.py` | Создание ключей и пользователей |

Таблица `refresh_tokens` создаётся миграцией `cloud/db/migrations/versions/0006_refresh_tokens.py`.

## Подготовка, один раз

Нужен Python 3.12, стенд запущен, миграции применены (`cloud/README.md`, раздел «Схема БД»). Из каталога `cloud/`:

Windows, PowerShell:

```text
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r auth_service/requirements-dev.txt
```

Linux и macOS:

```text
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r auth_service/requirements-dev.txt
```

Ключи подписи и первый администратор:

```text
python -m auth_service keys
python -m auth_service create-user --email admin@aibird.local --role super_admin --full-name "Админ стенда"
```

Пароль спрашивается в терминале, не короче 10 символов. Ключи ложатся в `auth_service/keys/`, эта папка в git не попадает.

Для клиента нужен `--client-id` — id строки из таблицы `clients`:

```text
python -m auth_service create-user --email client@acme.ru --role b2b_client --client-id <uuid>
```

## Запуск

Из каталога `cloud/`:

```text
uvicorn --factory auth_service.app:create_app --port 8001 --loop asyncio:SelectorEventLoop
```

`--loop asyncio:SelectorEventLoop` нужен на Windows: без него uvicorn берёт цикл событий, с которым драйвер PostgreSQL в async-режиме не работает, и первый же запрос к БД падает. На Linux и macOS флаг ничего не меняет.

Документация OpenAPI: http://127.0.0.1:8001/docs

## Переменные окружения

Все необязательные. Без них сервис работает со стендом.

| Переменная | По умолчанию | Что задаёт |
|---|---|---|
| `AIBIRD_DATABASE_URL` | стенд из `cloud/.env.example` | Адрес БД, `postgresql+psycopg://...` |
| `AUTH_PRIVATE_KEY_FILE` | `auth_service/keys/private.pem` | Закрытый ключ RSA |
| `AUTH_PUBLIC_KEY_FILE` | `auth_service/keys/public.pem` | Публичный ключ RSA |
| `AUTH_ISSUER` | `aibird-auth` | Claim `iss` |
| `AUTH_AUDIENCE` | `aibird-api` | Claim `aud` |
| `AUTH_ACCESS_TTL_SECONDS` | `3600` | Жизнь access-токена |
| `AUTH_REFRESH_TTL_SECONDS` | `604800` | Жизнь refresh-токена |
| `AUTH_CORS_ORIGINS` | пусто | Адреса фронтенда через запятую, например `http://localhost:5173`. `*` запрещён |

## Примеры запросов

```text
curl -X POST http://127.0.0.1:8001/api/v1/auth/login -H "Content-Type: application/json" -d "{\"email\":\"admin@aibird.local\",\"password\":\"...\"}"
```

Ответ:

```json
{"access_token": "eyJ...", "refresh_token": "eyJ...", "token_type": "bearer", "expires_in": 3600}
```

```text
curl http://127.0.0.1:8001/api/v1/auth/me -H "Authorization: Bearer <access_token>"
curl -X POST http://127.0.0.1:8001/api/v1/auth/refresh -H "Content-Type: application/json" -d "{\"refresh_token\":\"<refresh_token>\"}"
curl -X POST http://127.0.0.1:8001/api/v1/auth/logout -H "Content-Type: application/json" -d "{\"refresh_token\":\"<refresh_token>\"}"
```

## Claims access-токена

| Claim | Значение |
|---|---|
| `sub` | id пользователя |
| `email` | email |
| `role` | `super_admin`, `lead_ornithologist`, `field_engineer` или `b2b_client` |
| `client_id` | id клиента для `b2b_client`, иначе `null` |
| `permissions` | права роли из `roles.py` |
| `exp`, `iat`, `jti`, `iss`, `aud`, `typ` | служебные |

## Ответы с ошибкой

| Код | `detail` | Когда |
|---|---|---|
| 401 | `invalid_credentials` | Неверный email или пароль, пользователь отключён. Причина не уточняется |
| 401 | `missing_token` | Нет заголовка `Authorization: Bearer` |
| 401 | `token_expired` | Токен истёк |
| 401 | `invalid_token` | Подпись, издатель или формат не те |
| 401 | `wrong_token_type` | refresh вместо access или наоборот |
| 401 | `token_revoked` | refresh уже использован или отозван |
| 401 | `user_inactive` | Пользователя отключили, refresh больше не работает |
| 403 | `insufficient_role` | Роль не подходит |
| 403 | `insufficient_permissions` | Не хватает прав |
| 403 | `client_not_assigned` | У `b2b_client` нет `client_id` |

## Как защитить эндпоинт в другом сервисе

```python
from fastapi import Depends
from auth_service import ClientScope, Permission, Role, require_permission, require_role, require_scope

@router.get("/devices")
async def devices(claims=Depends(require_permission(Permission.DEVICES_READ))): ...

@router.post("/users")
async def create_user(claims=Depends(require_role(Role.SUPER_ADMIN))): ...

@router.get("/events")
async def events(scope: ClientScope = Depends(require_scope("client"))):
    stmt = scope.apply(select(events_table), events_table.c.client_id)
    # для b2b_client: ... WHERE events.client_id = :jwt_client_id
```

Сервису нужен только публичный ключ: `app.state.tokens = TokenService(None, public_pem, settings)`.

`require_scope` сделан зависимостью FastAPI, а не декоратором из §4.2: декоратор, который меняет SQL внутри функции, FastAPI не видит, и фильтр легко потерять. Через `Depends` область видна в сигнатуре и в OpenAPI.

## Безопасность

- Пароли хранятся как bcrypt, 12 раундов. Пароль длиннее 72 байт не принимается: bcrypt учитывает только первые 72.
- Неверный email и неверный пароль отвечают одинаково и за одинаковое время.
- В БД лежит только `jti` refresh-токена, не сам токен.
- `/refresh` выдаёт новый refresh, а старый отзывает. Если старый предъявят снова, отзываются все refresh-токены пользователя: так видна кража токена.
- Роль и `client_id` берутся из БД при каждом `/refresh`: смена роли действует не позже чем через час.
- Принимается только RS256. Токены HS256 и `none` отклоняются.

## Тесты

Из каталога `cloud/`:

```text
pytest auth_service --cov=auth_service --cov-report=term-missing
```

Тесты с PostgreSQL запускаются, если задан адрес БД после `alembic upgrade head`:

PowerShell:

```text
$env:AIBIRD_TEST_DATABASE_URL = "postgresql+psycopg://aibird:aibird-stand@127.0.0.1:5432/aibird"
pytest auth_service --cov=auth_service
```

Linux и macOS:

```text
AIBIRD_TEST_DATABASE_URL=postgresql+psycopg://aibird:aibird-stand@127.0.0.1:5432/aibird pytest auth_service --cov=auth_service
```

Без переменной эти 4 теста пропускаются, остальные идут на хранилище в памяти.

## Переход на OIDC в v1.1

`docs/OIDC_MIGRATION.md`.
