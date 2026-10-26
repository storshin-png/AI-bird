# Переход на OIDC в v1.1

В MVP вход — email и пароль из таблицы `users`. В v1.1 вход переезжает к внешнему провайдеру OIDC: Keycloak или ЕСИА. `AI_AGENTS_SPEC.md` §4.2 требует, чтобы контракты при этом не менялись.

## Что остаётся как есть

- Claims access-токена: `sub`, `email`, `role`, `client_id`, `permissions`, `exp`. Их читают Backend и Frontend.
- Зависимости `get_current_claims`, `require_role`, `require_permission`, `require_scope("client")`.
- Набор ролей и прав из `roles.py`.
- Адреса `/api/v1/auth/refresh`, `/logout`, `/me`, `/.well-known/jwks.json`.

## Что меняется

### 1. Новый провайдер

Реализовать тот же интерфейс, что `PasswordAuthProvider`:

```python
class OidcAuthProvider:
    async def authenticate(self, credentials: OidcCode) -> JWTClaims:
        # 1. Обменять authorization code на id_token у провайдера.
        # 2. Проверить подпись id_token по JWKS провайдера, iss, aud, nonce.
        # 3. Найти пользователя по sub провайдера (или email) в users.
        # 4. Роль и client_id взять из users, а не из токена провайдера.
        return JWTClaims.for_user(user.id, user.email, user.role, user.client_id)
```

Подставить его в `create_app(provider=OidcAuthProvider(...))`. `AuthService`, выпуск токенов и `refresh_tokens` при этом не меняются.

Роли остаются в нашей БД. У ЕСИА нет наших ролей, а Keycloak может их хранить, но тогда сменой роли управляют в двух местах. Если решат хранить роли в Keycloak, меняется шаг 4, а claims остаются прежними.

### 2. Вход во Frontend

Форма логина заменяется на перенаправление к провайдеру (Authorization Code + PKCE). Провайдер возвращает `code`, Frontend отправляет его в новый эндпоинт `POST /api/v1/auth/oidc/callback`. Ответ тот же, что у `/login`: пара токенов AI-bird. Остальной Frontend не меняется.

`/login` по паролю можно оставить для служебных учётных записей или выключить флагом.

### 3. Схема БД

В `users` добавить связь с внешней учётной записью. Это отдельная миграция и отдельный запрос с пометкой `contract`:

```sql
ALTER TABLE users ADD COLUMN external_issuer TEXT, ADD COLUMN external_subject TEXT;
CREATE UNIQUE INDEX users_external_uq ON users (external_issuer, external_subject);
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
```

## Вариант без своих токенов

Можно отдавать клиентам токены провайдера напрямую. Тогда `deps.py` проверяет подпись по JWKS провайдера, а claims собираются из его токена. Это вариант на потом: у ЕСИА нет `client_id` и наших прав, их пришлось бы подтягивать из БД на каждый запрос. Пока рекомендуем схему выше: провайдер только подтверждает личность, а токены выпускает AI-bird.

## Чеклист перехода

- [ ] Решение по провайдеру (Keycloak или ЕСИА) записано в журнал плана
- [ ] Миграция `external_issuer` и `external_subject`, запрос `contract`
- [ ] `OidcAuthProvider` и `/oidc/callback`, тесты на подделку `id_token` и неверный `nonce`
- [ ] Frontend: Authorization Code + PKCE
- [ ] Существующие пользователи связаны со своими внешними учётками
