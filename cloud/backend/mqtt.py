"""Клиент MQTT: подписка на birdnet/+/telemetry, /event, /heartbeat.

Запуск из каталога cloud/:
    python -m backend mqtt

При обрыве связи с брокером клиент переподключается с паузой 1, 2, 4 ... 30 с.
Ошибка БД на одном пакете не останавливает приём: пакет уходит в лог
с причиной db_error.
"""

import asyncio

import aiomqtt
from sqlalchemy.exc import SQLAlchemyError

from .config import Settings
from .ingest import IngestService
from .logs import get_logger
from .payloads import Kind

log = get_logger("mqtt")


def topics(prefix: str) -> list[tuple[str, int]]:
    return [(f"{prefix}/+/{kind.value}", 1) for kind in Kind]


async def consume(settings: Settings, ingest: IngestService, stop: asyncio.Event | None = None,
                  ready: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    delay = 1
    while not stop.is_set():
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                username=settings.mqtt_username,
                password=settings.mqtt_password,
                identifier=settings.mqtt_client_id,
            ) as client:
                await client.subscribe(topics(settings.mqtt_topic_prefix))
                log.info("subscribed", host=settings.mqtt_host, port=settings.mqtt_port,
                         topics=[t for t, _ in topics(settings.mqtt_topic_prefix)])
                delay = 1
                if ready:
                    ready.set()
                messages = aiomqtt_messages(client)
                while not stop.is_set():
                    get = asyncio.ensure_future(anext(messages))
                    stopper = asyncio.ensure_future(stop.wait())
                    done, _ = await asyncio.wait({get, stopper}, return_when=asyncio.FIRST_COMPLETED)
                    if get not in done:
                        get.cancel()
                        break
                    stopper.cancel()
                    message = get.result()
                    try:
                        await ingest.handle(str(message.topic), bytes(message.payload or b""))
                    except SQLAlchemyError as exc:
                        ingest._count("rejected:db_error")
                        log.error("db_error", topic=str(message.topic), error=str(exc)[:300])
        except aiomqtt.MqttError as exc:
            if stop.is_set():
                break
            log.warning("mqtt_disconnected", error=str(exc), retry_in=delay)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, 30)
    log.info("stopped", counters=ingest.counters)


async def aiomqtt_messages(client: aiomqtt.Client):
    async for message in client.messages:
        yield message
