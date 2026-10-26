"""Темы и полезная нагрузка MQTT. Описание формата — docs/MQTT_PAYLOADS.md.

Имена полей — без переименования из MVP_SPEC.md §2.1 (телеметрия),
USERFLOW.md §5.3 (событие) и ARCHITECTURE.md §3 (направление).
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MIN_TIMESTAMP = datetime(2025, 1, 1, tzinfo=UTC)
MAX_PAYLOAD_BYTES = 16 * 1024


class Kind(StrEnum):
    TELEMETRY = "telemetry"
    EVENT = "event"
    HEARTBEAT = "heartbeat"


class Rejected(Exception):
    """Пакет не принят. reason — короткий код для лога и счётчиков."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Topic:
    device_id: str
    kind: Kind


def parse_topic(topic: str, prefix: str = "birdnet") -> Topic:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != prefix:
        raise Rejected("bad_topic", topic)
    device_id, kind = parts[1], parts[2]
    if not DEVICE_ID_RE.match(device_id):
        raise Rejected("bad_device_id", device_id)
    try:
        return Topic(device_id, Kind(kind))
    except ValueError as exc:
        raise Rejected("bad_topic", topic) from exc


Probability = Annotated[float, Field(ge=0, le=1)]
Azimuth = Annotated[float, Field(ge=0, lt=360)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    device_id: str | None = None
    timestamp_utc: AwareDatetime

    @property
    def unknown_fields(self) -> list[str]:
        return sorted((self.model_extra or {}).keys())


class TelemetryPayload(_Base):
    battery_v: Annotated[float, Field(ge=0, le=10)] | None = None
    temperature_c: Annotated[float, Field(ge=-80, le=100)] | None = None
    bird_flag: bool | None = None
    bird_probability: Probability | None = None
    azimuth_geo_deg: Azimuth | None = None
    azimuth_confidence: Probability | None = None
    track_id: Annotated[str, Field(max_length=64)] | None = None
    quality_flag: Annotated[str, Field(max_length=32)] | None = None
    event_id: UUID | None = None


class HeartbeatPayload(_Base):
    battery_v: Annotated[float, Field(ge=0, le=10)] | None = None
    temperature_c: Annotated[float, Field(ge=-80, le=100)] | None = None
    firmware_version: Annotated[str, Field(max_length=64)] | None = None


class EventPayload(_Base):
    event_id: UUID
    bird_flag: bool | None = None
    bird_probability: Probability | None = None
    snr_db: Annotated[float, Field(ge=-100, le=200)] | None = None
    channel_levels: dict[Literal["N", "E", "S", "W"], float] | None = None
    quality_flag: Annotated[str, Field(max_length=32)] | None = None
    track_id: Annotated[str, Field(max_length=64)] | None = None
    # Направление, ARCHITECTURE.md §3. Пеленг пишется, если есть azimuth_geo_deg.
    azimuth_device_deg: Azimuth | None = None
    azimuth_geo_deg: Azimuth | None = None
    sector: Literal["N", "NE", "E", "SE", "S", "SW", "W", "NW"] | None = None
    azimuth_confidence: Probability | None = None
    bearing_quality: Literal["good", "medium", "poor", "ambiguous"] | None = None

    @field_validator("event_id")
    @classmethod
    def _uuid4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("event_id должен быть UUID v4")
        return value

    @property
    def has_bearing(self) -> bool:
        return self.azimuth_geo_deg is not None


MODELS: dict[Kind, type[_Base]] = {
    Kind.TELEMETRY: TelemetryPayload,
    Kind.EVENT: EventPayload,
    Kind.HEARTBEAT: HeartbeatPayload,
}


def _first_error(exc: ValidationError) -> tuple[str, str]:
    err = exc.errors()[0]
    field = ".".join(str(p) for p in err.get("loc", ())) or "payload"
    if field == "event_id":
        return "bad_event_id", err["msg"]
    if err["type"] == "missing":
        return f"missing_{field}", err["msg"]
    return f"invalid_{field.split('.')[0]}", err["msg"]


def parse_payload(topic: Topic, raw: bytes, now: datetime | None = None, max_future_skew: int = 300) -> _Base:
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise Rejected("payload_too_large", str(len(raw)))
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Rejected("bad_json", str(exc)) from exc
    if not isinstance(data, dict):
        raise Rejected("bad_json", "ожидался объект JSON")
    try:
        payload = MODELS[topic.kind].model_validate(data)
    except ValidationError as exc:
        raise Rejected(*_first_error(exc)) from exc
    if payload.device_id is not None and payload.device_id != topic.device_id:
        raise Rejected("device_id_mismatch", f"тема {topic.device_id}, пакет {payload.device_id}")
    now = now or datetime.now(UTC)
    ts = payload.timestamp_utc
    if ts > now + timedelta(seconds=max_future_skew):
        raise Rejected("timestamp_in_future", ts.isoformat())
    if ts < MIN_TIMESTAMP:
        # Часы устройства не выставлены (обычно 1970 год после сброса).
        raise Rejected("clock_not_set", ts.isoformat())
    return payload
