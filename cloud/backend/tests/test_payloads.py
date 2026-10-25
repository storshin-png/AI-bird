import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.config import Settings
from backend.mqtt import topics
from backend.payloads import EventPayload, Kind, Rejected, Topic, parse_payload, parse_topic

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
TS = "2026-10-25T11:59:00Z"


def raw(**fields) -> bytes:
    return json.dumps(fields).encode()


def reason(topic: Topic, payload: bytes) -> str:
    with pytest.raises(Rejected) as err:
        parse_payload(topic, payload, NOW)
    return err.value.reason


@pytest.mark.parametrize(
    "topic,device,kind",
    [
        ("birdnet/sensor-001/telemetry", "sensor-001", Kind.TELEMETRY),
        ("birdnet/s.1_A/event", "s.1_A", Kind.EVENT),
        ("birdnet/x/heartbeat", "x", Kind.HEARTBEAT),
    ],
)
def test_parse_topic(topic, device, kind):
    assert parse_topic(topic) == Topic(device, kind)


@pytest.mark.parametrize(
    "topic,code",
    [
        ("birdnet/sensor-001", "bad_topic"),
        ("other/sensor-001/telemetry", "bad_topic"),
        ("birdnet/sensor-001/status", "bad_topic"),
        ("birdnet/sensor-001/telemetry/extra", "bad_topic"),
        ("birdnet/-bad/telemetry", "bad_device_id"),
        ("birdnet/" + "a" * 65 + "/telemetry", "bad_device_id"),
    ],
)
def test_bad_topics(topic, code):
    with pytest.raises(Rejected) as err:
        parse_topic(topic)
    assert err.value.reason == code


def test_userflow_example_telemetry():
    # Пакет из USERFLOW.md §5.7, но с quality_flag, как в MVP_SPEC.md §2.1.
    p = parse_payload(
        Topic("sensor-001", Kind.TELEMETRY),
        raw(device_id="sensor-001", timestamp_utc=TS, battery_v=3.71, temperature_c=14.2, bird_flag=True,
            bird_probability=0.93, azimuth_geo_deg=152.0, azimuth_confidence=0.78, track_id="trk-000012",
            quality_flag="good"),
        NOW,
    )
    assert p.battery_v == 3.71 and p.quality_flag == "good" and p.unknown_fields == []


def test_unknown_fields_are_reported_not_rejected():
    p = parse_payload(Topic("s1", Kind.TELEMETRY), raw(timestamp_utc=TS, quality="good"), NOW)
    assert p.unknown_fields == ["quality"] and p.quality_flag is None


def test_event_with_bearing():
    eid = str(uuid.uuid4())
    p = parse_payload(
        Topic("s1", Kind.EVENT),
        raw(event_id=eid, timestamp_utc=TS, bird_probability=0.9, snr_db=14.2,
            channel_levels={"N": -31, "E": -28, "S": -35, "W": -40}, azimuth_device_deg=62.5,
            azimuth_geo_deg=152.5, sector="SE", azimuth_confidence=0.78, bearing_quality="good"),
        NOW,
    )
    assert isinstance(p, EventPayload) and p.has_bearing and str(p.event_id) == eid


@pytest.mark.parametrize(
    "kind,payload,code",
    [
        (Kind.TELEMETRY, b"not json", "bad_json"),
        (Kind.TELEMETRY, b"\xff\xfe", "bad_json"),
        (Kind.TELEMETRY, b"[1,2]", "bad_json"),
        (Kind.TELEMETRY, b"{" + b" " * 17000 + b"}", "payload_too_large"),
        (Kind.TELEMETRY, raw(battery_v=3.7), "missing_timestamp_utc"),
        (Kind.TELEMETRY, raw(timestamp_utc="2026-10-25T11:59:00"), "invalid_timestamp_utc"),
        (Kind.TELEMETRY, raw(timestamp_utc=TS, bird_probability=1.5), "invalid_bird_probability"),
        (Kind.TELEMETRY, raw(timestamp_utc=TS, azimuth_geo_deg=360), "invalid_azimuth_geo_deg"),
        (Kind.TELEMETRY, raw(timestamp_utc=TS, device_id="other"), "device_id_mismatch"),
        (Kind.TELEMETRY, raw(timestamp_utc="2026-10-25T12:06:00Z"), "timestamp_in_future"),
        (Kind.TELEMETRY, raw(timestamp_utc="1970-01-01T00:00:10Z"), "clock_not_set"),
        (Kind.EVENT, raw(timestamp_utc=TS), "bad_event_id"),
        (Kind.EVENT, raw(timestamp_utc=TS, event_id="evt-000123"), "bad_event_id"),
        (Kind.EVENT, raw(timestamp_utc=TS, event_id=str(uuid.uuid1())), "bad_event_id"),
        (Kind.EVENT, raw(timestamp_utc=TS, event_id=str(uuid.uuid4()), sector="NNE"), "invalid_sector"),
        (Kind.EVENT, raw(timestamp_utc=TS, event_id=str(uuid.uuid4()), channel_levels={"X": 1}),
         "invalid_channel_levels"),
        (Kind.EVENT, raw(timestamp_utc=TS, event_id=str(uuid.uuid4()), bearing_quality="ok"),
         "invalid_bearing_quality"),
    ],
)
def test_rejections(kind, payload, code):
    assert reason(Topic("s1", kind), payload) == code


def test_small_clock_skew_is_fine():
    parse_payload(Topic("s1", Kind.HEARTBEAT), raw(timestamp_utc="2026-10-25T12:04:00Z"), NOW)


def test_topics_and_settings():
    assert topics("birdnet") == [
        ("birdnet/+/telemetry", 1), ("birdnet/+/event", 1), ("birdnet/+/heartbeat", 1)
    ]
    s = Settings.from_env({
        "MQTT_HOST": "broker", "MQTT_PORT": "8883", "MQTT_USERNAME": "u", "MQTT_PASSWORD": "p",
        "MQTT_CLIENT_ID": "c", "MQTT_TOPIC_PREFIX": "/birdnet/", "INGEST_MAX_FUTURE_SKEW_SECONDS": "60",
        "BACKEND_CORS_ORIGINS": "http://localhost:5173", "AIBIRD_DATABASE_URL": "postgresql+psycopg://x/y",
    })
    assert (s.mqtt_host, s.mqtt_port, s.mqtt_username, s.mqtt_password, s.mqtt_client_id) == (
        "broker", 8883, "u", "p", "c")
    assert s.mqtt_topic_prefix == "birdnet" and s.max_future_skew_seconds == 60
    assert s.cors_origins == ("http://localhost:5173",) and s.database_url == "postgresql+psycopg://x/y"
    assert Settings.from_env({}).mqtt_port == 1883
    with pytest.raises(ValueError):
        Settings.from_env({"BACKEND_CORS_ORIGINS": "*"})


def test_future_window_is_configurable():
    later = NOW + timedelta(minutes=30)
    parse_payload(Topic("s1", Kind.HEARTBEAT), raw(timestamp_utc=later.isoformat()), NOW, max_future_skew=3600)


def test_app_reads_public_key_file(tmp_path):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from auth_service.tokens import KeyFileError, write_key_pair
    from backend.app import create_app

    base = Settings()
    missing = replace(base, auth=replace(base.auth, public_key_file=tmp_path / "nope.pem"))
    with pytest.raises(KeyFileError, match="python -m auth_service keys"):
        create_app(settings=missing)
    _, pub = write_key_pair(tmp_path / "keys", bits=2048)
    app = create_app(settings=replace(base, auth=replace(base.auth, public_key_file=pub)))
    with TestClient(app) as client:  # свой движок БД создаётся и закрывается приложением
        assert client.get("/healthz").json() == {"status": "ok"}
