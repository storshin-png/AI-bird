"""Настройки backend из переменных окружения. Таблица — в README.md."""

import os
from dataclasses import dataclass, field

from auth_service.config import Settings as AuthSettings
from auth_service.config import _split, _stand_database_url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_stand_database_url)
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_client_id: str = "aibird-ingest"
    mqtt_topic_prefix: str = "birdnet"
    # Насколько время пакета может опережать часы сервера.
    max_future_skew_seconds: int = 300
    cors_origins: tuple[str, ...] = ()
    auth: AuthSettings = field(default_factory=AuthSettings)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        kwargs: dict = {"auth": AuthSettings.from_env(env)}
        if env.get("AIBIRD_DATABASE_URL"):
            kwargs["database_url"] = env["AIBIRD_DATABASE_URL"]
        if env.get("MQTT_HOST"):
            kwargs["mqtt_host"] = env["MQTT_HOST"]
        if env.get("MQTT_PORT"):
            kwargs["mqtt_port"] = int(env["MQTT_PORT"])
        if env.get("MQTT_USERNAME"):
            kwargs["mqtt_username"] = env["MQTT_USERNAME"]
        if env.get("MQTT_PASSWORD"):
            kwargs["mqtt_password"] = env["MQTT_PASSWORD"]
        if env.get("MQTT_CLIENT_ID"):
            kwargs["mqtt_client_id"] = env["MQTT_CLIENT_ID"]
        if env.get("MQTT_TOPIC_PREFIX"):
            kwargs["mqtt_topic_prefix"] = env["MQTT_TOPIC_PREFIX"].strip("/")
        if env.get("INGEST_MAX_FUTURE_SKEW_SECONDS"):
            kwargs["max_future_skew_seconds"] = int(env["INGEST_MAX_FUTURE_SKEW_SECONDS"])
        if "BACKEND_CORS_ORIGINS" in env:
            kwargs["cors_origins"] = _split(env["BACKEND_CORS_ORIGINS"])
        settings = cls(**kwargs)
        if "*" in settings.cors_origins:
            raise ValueError("BACKEND_CORS_ORIGINS: '*' не допускается, нужен явный список адресов")
        return settings
