"""Сквозной приём через настоящий брокер: публикация → клиент → БД."""

import asyncio
import json
import threading
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import paho.mqtt.client as paho
import pytest

from backend.config import Settings
from backend.ingest import IngestService
from backend.mqtt import consume

from .conftest import MQTT, needs_mqtt


class Runner:
    """Запускает consume() в отдельном потоке со своим циклом событий."""

    def __init__(self, settings, engine_url):
        self.settings = settings
        self.url = engine_url
        self.ready = threading.Event()
        self.loop = asyncio.new_event_loop()
        self.stop = None
        self.ingest = None

    def _main(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        async def go():
            self.stop = asyncio.Event()
            ready = asyncio.Event()
            engine = create_async_engine(self.url, poolclass=NullPool)
            self.ingest = IngestService(engine, self.settings.mqtt_topic_prefix)

            async def flag():
                await ready.wait()
                self.ready.set()

            asyncio.ensure_future(flag())
            await consume(self.settings, self.ingest, self.stop, ready)
            await engine.dispose()

        self.loop.run_until_complete(go())

    def __enter__(self):
        self.thread = threading.Thread(target=self._main, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        while self.stop is None:
            time.sleep(0.01)
        self.loop.call_soon_threadsafe(self.stop.set)
        self.thread.join(10)
        assert not self.thread.is_alive()


def publish(topic, payload, host, port):
    client = paho.Client(paho.CallbackAPIVersion.VERSION2)
    client.connect(host, port)
    client.loop_start()
    info = client.publish(topic, json.dumps(payload), qos=1)
    info.wait_for_publish(5)
    client.loop_stop()
    client.disconnect()


def wait_for(fn, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.1)
    return False


@needs_mqtt
def test_end_to_end(db):
    from .conftest import DB_URL

    host, port = MQTT.split(":")
    prefix = f"birdnet-{db.tag}"  # своя ветка тем, чтобы не мешать стенду
    settings = Settings(mqtt_host=host, mqtt_port=int(port), mqtt_topic_prefix=prefix,
                        mqtt_client_id=f"test-{db.tag}")
    dev = db.device("mq")
    eid = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    with Runner(settings, DB_URL) as r:
        assert r.ready.wait(10)
        publish(f"{prefix}/{dev}/telemetry", {"timestamp_utc": now, "battery_v": 3.6}, host, int(port))
        publish(f"{prefix}/{dev}/event", {"event_id": eid, "timestamp_utc": now, "azimuth_geo_deg": 10.0,
                                         "sector": "N"}, host, int(port))
        publish(f"{prefix}/{dev}/event", {"event_id": eid, "timestamp_utc": now}, host, int(port))
        publish(f"{prefix}/{db.dev('ghost')}/heartbeat", {"timestamp_utc": now}, host, int(port))
        assert wait_for(lambda: sum(r.ingest.counters.values()) >= 4), r.ingest.counters
    assert r.ingest.counters == {"stored": 2, "duplicate": 1, "rejected:unknown_device": 1}
    assert db.scalar("SELECT count(*) FROM telemetry WHERE device_id = :d", d=dev) == 1
    assert db.scalar("SELECT count(*) FROM events WHERE event_id = :e", e=eid) == 1
    assert db.scalar("SELECT count(*) FROM bearings WHERE event_id = :e", e=eid) == 1


@needs_mqtt
def test_reconnects_until_stopped(engine, capsys):
    from backend import logs

    logs.configure()
    settings = replace(Settings(), mqtt_host="127.0.0.1", mqtt_port=1)  # здесь брокера нет
    ingest = IngestService(engine)

    async def go():
        stop = asyncio.Event()
        task = asyncio.ensure_future(consume(settings, ingest, stop))
        await asyncio.sleep(1.5)
        stop.set()
        await asyncio.wait_for(task, 5)

    asyncio.run(go())
    out = capsys.readouterr().out
    assert '"mqtt_disconnected"' in out and '"stopped"' in out


@needs_mqtt
def test_db_error_does_not_stop_consumer(db, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from .conftest import DB_URL

    host, port = MQTT.split(":")
    prefix = f"birdnet-{db.tag}e"
    settings = Settings(mqtt_host=host, mqtt_port=int(port), mqtt_topic_prefix=prefix,
                        mqtt_client_id=f"test-{db.tag}e")
    calls = []

    async def broken(self, topic, raw, trace_id=None):
        calls.append(topic)
        if len(calls) == 1:
            raise OperationalError("SELECT 1", {}, Exception("db down"))
        return await original(self, topic, raw, trace_id)

    original = IngestService.handle
    monkeypatch.setattr(IngestService, "handle", broken)
    dev = db.device("dberr")
    with Runner(settings, DB_URL) as r:
        assert r.ready.wait(10)
        for i in range(2):
            publish(f"{prefix}/{dev}/heartbeat",
                    {"timestamp_utc": datetime.now(UTC).isoformat(), "battery_v": 3.0 + i}, host, int(port))
            time.sleep(0.2)
        assert wait_for(lambda: len(calls) >= 2)
        assert wait_for(lambda: r.ingest.counters.get("stored") == 1)
    assert r.ingest.counters["rejected:db_error"] == 1


def test_cli_parses_command(monkeypatch):
    from backend import __main__ as cli

    seen = {}

    async def fake(settings):
        seen["host"] = settings.mqtt_host

    monkeypatch.setattr(cli, "_run_mqtt", fake)
    monkeypatch.setenv("MQTT_HOST", "broker.local")
    assert cli.main(["mqtt"]) == 0 and seen == {"host": "broker.local"}
    with pytest.raises(SystemExit):
        cli.main([])
