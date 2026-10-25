"""python -m backend mqtt — запустить приём MQTT."""

import argparse
import asyncio
import signal
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from . import logs
from .config import Settings
from .ingest import IngestService
from .mqtt import consume


async def _run_mqtt(settings: Settings) -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    ingest = IngestService(engine, settings.mqtt_topic_prefix, settings.max_future_skew_seconds)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C прерывает asyncio.run
            pass
    try:
        await consume(settings, ingest, stop)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mqtt", help="приём телеметрии из брокера MQTT")
    parser.parse_args(argv)
    logs.configure()
    try:
        # SelectorEventLoop: psycopg и aiomqtt не работают с ProactorEventLoop Windows.
        asyncio.run(_run_mqtt(Settings.from_env()), loop_factory=asyncio.SelectorEventLoop)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
