"""Запись пакетов MQTT в telemetry, events и bearings.

Повтор пакета не плодит строк:
- событие — по event_id: второе событие с тем же event_id не пишется,
  даже если время в нём другое;
- телеметрия и heartbeat — по паре (device_id, timestamp_utc).

Неизвестный или списанный device_id — отказ с причиной в логе.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .logs import get_logger
from .payloads import EventPayload, HeartbeatPayload, Kind, Rejected, TelemetryPayload, parse_payload, parse_topic

log = get_logger("ingest")


class Status(StrEnum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Result:
    status: Status
    kind: str | None = None
    device_id: str | None = None
    event_id: str | None = None
    reason: str | None = None


_INSERT_TELEMETRY = text(
    """
    INSERT INTO telemetry (timestamp_utc, device_id, battery_v, temperature_c, bird_flag, bird_probability,
                           azimuth_geo_deg, azimuth_confidence, track_id, quality_flag, event_id)
    SELECT :ts, :device_id, :battery_v, :temperature_c, :bird_flag, :bird_probability,
           :azimuth_geo_deg, :azimuth_confidence, :track_id, :quality_flag, :event_id
    WHERE NOT EXISTS (SELECT 1 FROM telemetry WHERE device_id = :device_id AND timestamp_utc = :ts)
    RETURNING id
    """
)

_INSERT_EVENT = text(
    """
    INSERT INTO events (event_id, timestamp_utc, device_id, client_id, bird_flag, bird_probability, snr_db,
                        channel_levels, quality_flag, track_id)
    SELECT :event_id, :ts, :device_id, :client_id, :bird_flag, :bird_probability, :snr_db,
           CAST(:channel_levels AS JSONB), :quality_flag, :track_id
    WHERE NOT EXISTS (SELECT 1 FROM events WHERE event_id = :event_id)
    ON CONFLICT DO NOTHING
    RETURNING event_id
    """
)

_INSERT_BEARING = text(
    """
    INSERT INTO bearings (event_id, timestamp_utc, device_id, azimuth_device_deg, azimuth_geo_deg, sector,
                          azimuth_confidence, bearing_quality, source)
    VALUES (:event_id, :ts, :device_id, :azimuth_device_deg, :azimuth_geo_deg, :sector,
            :azimuth_confidence, :bearing_quality, 'edge')
    """
)


class IngestService:
    def __init__(self, engine: AsyncEngine, topic_prefix: str = "birdnet", max_future_skew: int = 300, clock=None):
        self._engine = engine
        self._prefix = topic_prefix
        self._skew = max_future_skew
        self._clock = clock or (lambda: datetime.now(UTC))
        self.counters: dict[str, int] = {}

    def _count(self, key: str) -> None:
        self.counters[key] = self.counters.get(key, 0) + 1

    async def handle(self, topic: str, raw: bytes, trace_id: str | None = None) -> Result:
        trace_id = trace_id or uuid.uuid4().hex
        bound = log.bind(trace_id=trace_id, topic=topic)
        try:
            parsed = parse_topic(topic, self._prefix)
            bound = bound.bind(device_id=parsed.device_id, kind=parsed.kind.value)
            payload = parse_payload(parsed, raw, self._clock(), self._skew)
            event_id = str(getattr(payload, "event_id", None) or "") or None
            if event_id:
                bound = bound.bind(event_id=event_id)
            if payload.unknown_fields:
                bound.warning("unknown_fields", fields=payload.unknown_fields)
            async with self._engine.begin() as conn:
                device = (
                    await conn.execute(
                        text("SELECT client_id, status, firmware_version FROM devices WHERE device_id = :d"),
                        {"d": parsed.device_id},
                    )
                ).first()
                if device is None:
                    raise Rejected("unknown_device", parsed.device_id)
                if device.status == "retired":
                    raise Rejected("device_retired", parsed.device_id)
                if parsed.kind is Kind.EVENT:
                    stored = await self._event(conn, parsed.device_id, device.client_id, payload)
                else:
                    stored = await self._telemetry(conn, parsed.device_id, payload)
                    if isinstance(payload, HeartbeatPayload) and payload.firmware_version and (
                        payload.firmware_version != device.firmware_version
                    ):
                        await conn.execute(
                            text(
                                "UPDATE devices SET firmware_version = :v, updated_at = now() WHERE device_id = :d"
                            ),
                            {"v": payload.firmware_version, "d": parsed.device_id},
                        )
        except Rejected as exc:
            self._count(f"rejected:{exc.reason}")
            bound.warning("rejected", reason=exc.reason, detail=exc.detail[:200])
            return Result(Status.REJECTED, reason=exc.reason)
        status = Status.STORED if stored else Status.DUPLICATE
        self._count(status.value)
        bound.info(status.value)
        return Result(status, parsed.kind.value, parsed.device_id, event_id)

    async def _telemetry(self, conn, device_id: str, p: TelemetryPayload | HeartbeatPayload) -> bool:
        row = (
            await conn.execute(
                _INSERT_TELEMETRY,
                {
                    "ts": p.timestamp_utc,
                    "device_id": device_id,
                    "battery_v": p.battery_v,
                    "temperature_c": p.temperature_c,
                    "bird_flag": getattr(p, "bird_flag", None),
                    "bird_probability": getattr(p, "bird_probability", None),
                    "azimuth_geo_deg": getattr(p, "azimuth_geo_deg", None),
                    "azimuth_confidence": getattr(p, "azimuth_confidence", None),
                    "track_id": getattr(p, "track_id", None),
                    "quality_flag": getattr(p, "quality_flag", None),
                    "event_id": getattr(p, "event_id", None),
                },
            )
        ).first()
        return row is not None

    async def _event(self, conn, device_id: str, client_id, p: EventPayload) -> bool:
        params = {
            "event_id": p.event_id,
            "ts": p.timestamp_utc,
            "device_id": device_id,
        }
        row = (
            await conn.execute(
                _INSERT_EVENT,
                {
                    **params,
                    "client_id": client_id,
                    "bird_flag": p.bird_flag,
                    "bird_probability": p.bird_probability,
                    "snr_db": p.snr_db,
                    "channel_levels": json.dumps(p.channel_levels) if p.channel_levels is not None else None,
                    "quality_flag": p.quality_flag,
                    "track_id": p.track_id,
                },
            )
        ).first()
        if row is None:
            return False
        if p.has_bearing:
            await conn.execute(
                _INSERT_BEARING,
                {
                    **params,
                    "azimuth_device_deg": p.azimuth_device_deg,
                    "azimuth_geo_deg": p.azimuth_geo_deg,
                    "sector": p.sector,
                    "azimuth_confidence": p.azimuth_confidence,
                    "bearing_quality": p.bearing_quality,
                },
            )
        return True
