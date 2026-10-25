"""FastAPI-приложение backend.

Запуск из каталога cloud/:
    uvicorn --factory backend.app:create_app --port 8000 --loop asyncio:SelectorEventLoop

--loop asyncio:SelectorEventLoop обязателен на Windows (см. auth_service/app.py).

Токены выпускает auth_service, backend только проверяет подпись
публичным ключом (AUTH_PUBLIC_KEY_FILE).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from auth_service.tokens import KeyFileError, TokenService

from . import logs
from .api import router
from .config import Settings


def verifier(settings: Settings) -> TokenService:
    try:
        public = settings.auth.public_key_file.read_bytes()
    except FileNotFoundError as exc:
        raise KeyFileError(
            f"Нет публичного ключа {exc.filename}. Создайте пару: python -m auth_service keys"
        ) from exc
    return TokenService(None, public, settings.auth)


def create_app(
    settings: Settings | None = None, engine: AsyncEngine | None = None, tokens: TokenService | None = None
) -> FastAPI:
    logs.configure()
    settings = settings or Settings.from_env()
    tokens = tokens or verifier(settings)
    own_engine = engine is None
    engine = engine or create_async_engine(settings.database_url, pool_pre_ping=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if own_engine:
            await engine.dispose()

    app = FastAPI(title="AI-bird Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.tokens = tokens
    app.state.engine = engine
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
            max_age=600,
        )
    app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok"}

    return app
