"""FastAPI-приложение авторизации.

Запуск из каталога cloud/:
    uvicorn --factory auth_service.app:create_app --port 8001 --loop asyncio:SelectorEventLoop

--loop asyncio:SelectorEventLoop обязателен на Windows: там uvicorn по
умолчанию берёт ProactorEventLoop, с которым psycopg в async-режиме не работает.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import Settings
from .provider import AuthProvider, PasswordAuthProvider
from .service import AuthService
from .store import AuthStore, SqlAuthStore
from .tokens import TokenService


def create_app(
    settings: Settings | None = None,
    store: AuthStore | None = None,
    tokens: TokenService | None = None,
    provider: AuthProvider | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    tokens = tokens or TokenService.from_settings(settings)
    own_store = store is None
    store = store or SqlAuthStore.from_url(settings.database_url)
    provider = provider or PasswordAuthProvider(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if own_store:
            await store.close()

    app = FastAPI(title="AI-bird Auth", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.tokens = tokens
    app.state.store = store
    app.state.auth = AuthService(provider, store, tokens, settings.access_ttl_seconds)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
            max_age=600,
        )

    app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok"}

    return app
