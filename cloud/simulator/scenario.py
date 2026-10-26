"""Сценарий: датчики, локальные треки и одиночные события.

Локальный трек — как в USERFLOW.md §5.6: несколько детекций подряд с
согласованным изменением пеленга (например 62° → 68° → 75° → 83°) и
общим track_id. Одиночная детекция идёт без track_id.

Всё детерминировано по seed: один и тот же seed даёт те же event_id,
азимуты и WAV.
"""

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .geometry import CHANNELS, bearing_quality, channel_response, device_azimuth, norm, sector

# Окрестности Магнитогорска — локация пилота (IMPLEMENTATION_PLAN.md §8).
PILOT_CENTER = (53.41, 58.98)


@dataclass(frozen=True)
class SimDevice:
    device_id: str
    latitude: float
    longitude: float
    orientation_deg: float


@dataclass
class SimEvent:
    device: SimDevice
    event_id: str
    timestamp: datetime
    azimuth_geo_deg: float
    azimuth_confidence: float
    bird_probability: float
    snr_db: float
    track_id: str | None
    seed: int
    channel_levels: dict[str, float] = field(default_factory=dict)

    @property
    def azimuth_device_deg(self) -> float:
        return round(device_azimuth(self.azimuth_geo_deg, self.device.orientation_deg), 1)

    @property
    def ts(self) -> str:
        return self.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    @property
    def wav_name(self) -> str:
        # USERFLOW.md §5.5: 2026-08-06_03-15-27_sensor-001_evt-000123.wav, event_id — UUID.
        return f"{self.timestamp:%Y-%m-%d_%H-%M-%S}_{self.device.device_id}_evt-{self.event_id}.wav"

    def event_payload(self) -> dict:
        return {
            "device_id": self.device.device_id,
            "event_id": self.event_id,
            "timestamp_utc": self.ts,
            "bird_flag": True,
            "bird_probability": self.bird_probability,
            "snr_db": self.snr_db,
            "channel_levels": self.channel_levels,
            "quality_flag": "ok",
            "track_id": self.track_id,
            "azimuth_device_deg": self.azimuth_device_deg,
            "azimuth_geo_deg": self.azimuth_geo_deg,
            "sector": sector(self.azimuth_geo_deg),
            "azimuth_confidence": self.azimuth_confidence,
            "bearing_quality": bearing_quality(self.azimuth_confidence),
        }

    def telemetry_payload(self, battery_v: float, temperature_c: float) -> dict:
        # Короткий LoRaWAN-пакет, MVP_SPEC.md §2.1.
        return {
            "device_id": self.device.device_id,
            "timestamp_utc": self.ts,
            "battery_v": battery_v,
            "temperature_c": temperature_c,
            "bird_flag": True,
            "bird_probability": self.bird_probability,
            "azimuth_geo_deg": self.azimuth_geo_deg,
            "azimuth_confidence": self.azimuth_confidence,
            "track_id": self.track_id,
            "quality_flag": "ok",
            "event_id": self.event_id,
        }


def make_devices(count: int, rng: random.Random, prefix: str = "sim") -> list[SimDevice]:
    lat0, lon0 = PILOT_CENTER
    return [
        SimDevice(
            device_id=f"{prefix}-{i + 1:03d}",
            latitude=round(lat0 + rng.uniform(-0.03, 0.03), 5),
            longitude=round(lon0 + rng.uniform(-0.05, 0.05), 5),
            orientation_deg=round(rng.uniform(0, 360), 1) % 360,
        )
        for i in range(count)
    ]


def _uuid4(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def make_events(devices: list[SimDevice], tracks: int, singles: int, start: datetime,
                rng: random.Random) -> list[SimEvent]:
    """tracks локальных треков по 3–5 детекций и singles одиночных событий."""
    events: list[SimEvent] = []
    clock = start

    def add(device, azimuth, track_id):
        nonlocal clock
        conf = round(rng.uniform(0.25, 0.95), 2)
        geo = round(norm(azimuth), 1)
        response = channel_response(device_azimuth(geo, device.orientation_deg), 0.03, 44100)
        # Уровни каналов в dBFS: громче всего микрофон, обращённый к источнику.
        levels = {ch: round(20 * math.log10(0.5 * response[ch][0]), 1) for ch in CHANNELS}
        events.append(
            SimEvent(
                device=device,
                event_id=_uuid4(rng),
                timestamp=clock,
                azimuth_geo_deg=geo,
                azimuth_confidence=conf,
                bird_probability=round(rng.uniform(0.6, 0.99), 2),
                snr_db=round(rng.uniform(6, 24), 1),
                track_id=track_id,
                seed=rng.getrandbits(32),
                channel_levels=levels,
            )
        )

    counters = {d.device_id: 0 for d in devices}
    for _ in range(tracks):
        device = rng.choice(devices)
        counters[device.device_id] += 1
        track_id = f"trk-{device.device_id}-{counters[device.device_id]:04d}"
        azimuth = rng.uniform(0, 360)
        step = rng.choice([-1, 1]) * rng.uniform(4, 9)
        for _ in range(rng.randint(3, 5)):
            add(device, azimuth, track_id)
            azimuth += step + rng.uniform(-1.5, 1.5)
            clock += timedelta(seconds=rng.randint(2, 4))
        clock += timedelta(seconds=rng.randint(20, 90))
    for _ in range(singles):
        add(rng.choice(devices), rng.uniform(0, 360), None)
        clock += timedelta(seconds=rng.randint(10, 60))
    return events
