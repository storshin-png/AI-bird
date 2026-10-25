"""python -m simulator — синтетические события для стенда.

Примеры из каталога cloud/:

    python -m simulator --register --mqtt 127.0.0.1:1883
    python -m simulator --devices 3 --tracks 5 --singles 10 --seed 7 --no-wav --mqtt 127.0.0.1:1883
    python -m simulator --out sd_card --seed 7          # только файлы, как выгрузка SD-карты

--register заводит датчики в БД стенда (без этого backend отклонит пакеты
как unknown_device). Повторный --register безвреден.
"""

import argparse
import json
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .scenario import SimDevice, SimEvent, make_devices, make_events
from .wav import load_format, synthesize

DEFAULT_OUT = Path(__file__).resolve().parent / "out"


def register(devices: list[SimDevice], database_url: str) -> int:
    import psycopg

    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    created = 0
    with psycopg.connect(dsn) as conn:
        for d in devices:
            cur = conn.execute(
                """
                INSERT INTO devices (device_id, name, installation_geo, orientation_deg, status, firmware_version)
                VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, 'active', 'sim-0.1')
                ON CONFLICT (device_id) DO NOTHING
                """,
                (d.device_id, f"Синтетический {d.device_id}", d.longitude, d.latitude, d.orientation_deg),
            )
            created += cur.rowcount
    return created


class Publisher:
    def __init__(self, host: str, port: int, prefix: str):
        import paho.mqtt.client as paho

        self.prefix = prefix
        self.client = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=f"aibird-sim-{random.getrandbits(32):08x}")
        self.client.connect(host, port)
        self.client.loop_start()
        self.sent = 0

    def send(self, device_id: str, kind: str, payload: dict) -> None:
        info = self.client.publish(f"{self.prefix}/{device_id}/{kind}", json.dumps(payload, ensure_ascii=False), qos=1)
        info.wait_for_publish(10)
        self.sent += 1

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def _manifest_row(e: SimEvent, wav: str | None) -> dict:
    return {
        "event_id": e.event_id,
        "device_id": e.device.device_id,
        "timestamp_utc": e.ts,
        "track_id": e.track_id,
        "true_azimuth_geo_deg": e.azimuth_geo_deg,
        "orientation_deg": e.device.orientation_deg,
        "azimuth_device_deg": e.azimuth_device_deg,
        "azimuth_confidence": e.azimuth_confidence,
        "wav": wav,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m simulator", description=__doc__.splitlines()[0])
    p.add_argument("--devices", type=int, default=2)
    p.add_argument("--tracks", type=int, default=3, help="локальных треков по 3–5 детекций")
    p.add_argument("--singles", type=int, default=4, help="одиночных событий без трека")
    p.add_argument("--seed", type=int, help="один seed — те же event_id, азимуты и WAV")
    p.add_argument("--prefix", default="sim", help="начало device_id: sim-001, sim-002, ...")
    p.add_argument("--start", help="время первого события, ISO 8601 с поясом; по умолчанию час назад")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="куда класть WAV и events.jsonl")
    p.add_argument("--no-wav", action="store_true", help="не писать WAV, только пакеты и манифест")
    p.add_argument("--mqtt", help="host:port брокера; без него пакеты не отправляются")
    p.add_argument("--topic-prefix", default="birdnet")
    p.add_argument("--register", action="store_true", help="завести датчики в БД стенда")
    p.add_argument("--database-url", help="по умолчанию AIBIRD_DATABASE_URL или стенд")
    p.add_argument("--delay", type=float, default=0.0, help="пауза между событиями при отправке, секунды")
    args = p.parse_args(argv)

    seed = args.seed if args.seed is not None else random.SystemRandom().getrandbits(31)
    rng = random.Random(seed)
    start = datetime.fromisoformat(args.start) if args.start else datetime.now(UTC) - timedelta(hours=1)
    if start.tzinfo is None:
        p.error("--start должен быть с часовым поясом, например 2026-10-25T03:00:00+00:00")
    devices = make_devices(args.devices, rng, args.prefix)
    events = make_events(devices, args.tracks, args.singles, start.astimezone(UTC), rng)
    if events and events[-1].timestamp > datetime.now(UTC) + timedelta(minutes=5):
        p.error("последнее событие оказалось в будущем — backend его отклонит; сдвиньте --start назад")

    print(f"seed {seed}: {len(devices)} датчика, {len(events)} событий, "
          f"{len({e.track_id for e in events if e.track_id})} локальных треков")

    if args.register:
        from auth_service.config import Settings

        url = args.database_url or Settings.from_env().database_url
        created = register(devices, url)
        print(f"датчиков заведено в БД: {created}, уже были: {len(devices) - created}")

    fmt = None if args.no_wav else load_format()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = args.out / "events.jsonl"
    with manifest.open("w", encoding="utf-8") as mf:
        for e in events:
            wav_name = None
            if fmt:
                synthesize(args.out / e.wav_name, e.azimuth_device_deg, fmt, e.seed, snr_db=e.snr_db)
                wav_name = e.wav_name
            mf.write(json.dumps(_manifest_row(e, wav_name), ensure_ascii=False) + "\n")
    print(f"манифест: {manifest}" + ("" if args.no_wav else f", WAV: {len(events)} шт. в {args.out}"))

    if args.mqtt:
        host, _, port = args.mqtt.partition(":")
        pub = Publisher(host, int(port or 1883), args.topic_prefix)
        try:
            battery = {d.device_id: round(rng.uniform(3.5, 3.9), 2) for d in devices}
            first = events[0].timestamp if events else datetime.now(UTC)
            heartbeat_ts = (first - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            for d in devices:
                pub.send(d.device_id, "heartbeat", {"device_id": d.device_id, "timestamp_utc": heartbeat_ts,
                                                    "battery_v": battery[d.device_id], "temperature_c": -5.0,
                                                    "firmware_version": "sim-0.1"})
            for e in events:
                battery[e.device.device_id] = round(battery[e.device.device_id] - 0.001, 3)
                pub.send(e.device.device_id, "event", e.event_payload())
                pub.send(e.device.device_id, "telemetry", e.telemetry_payload(battery[e.device.device_id], -5.0))
                if args.delay:
                    time.sleep(args.delay)
        finally:
            pub.close()
        print(f"в MQTT отправлено пакетов: {pub.sent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
