"""Запись в БД: телеметрия, события, пеленги, дедупликация, отказы."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from backend.ingest import IngestService, Status

from .conftest import needs_db, run

pytestmark = needs_db


def ts(seconds_ago: int = 60) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


def send(service, topic, **payload):
    return run(service.handle(topic, json.dumps(payload).encode()))


def test_telemetry_stored_once(engine, db):
    dev = db.device("t1")
    svc = IngestService(engine)
    t = ts()
    payload = dict(timestamp_utc=t, battery_v=3.71, temperature_c=-4.5, bird_flag=True, bird_probability=0.93,
                   azimuth_geo_deg=152.0, azimuth_confidence=0.78, track_id="trk-1", quality_flag="ok")
    first = send(svc, f"birdnet/{dev}/telemetry", **payload)
    assert first.status is Status.STORED and first.device_id == dev
    assert send(svc, f"birdnet/{dev}/telemetry", **payload).status is Status.DUPLICATE
    rows = db.exec("SELECT battery_v, quality_flag, azimuth_geo_deg FROM telemetry WHERE device_id = :d", d=dev)
    assert [tuple(r) for r in rows] == [(3.71, "ok", 152.0)]
    assert svc.counters == {"stored": 1, "duplicate": 1}


def test_heartbeat_updates_firmware(engine, db):
    dev = db.device("hb")
    svc = IngestService(engine)
    assert send(svc, f"birdnet/{dev}/heartbeat", timestamp_utc=ts(), battery_v=3.3,
                firmware_version="0.1.2").status is Status.STORED
    assert db.scalar("SELECT firmware_version FROM devices WHERE device_id = :d", d=dev) == "0.1.2"
    assert db.scalar("SELECT count(*) FROM telemetry WHERE device_id = :d AND bird_flag IS NULL", d=dev) == 1


def test_event_with_bearing_and_dedup(engine, db):
    cid = db.client()
    dev = db.device("ev", client_id=cid)
    svc = IngestService(engine)
    eid = str(uuid.uuid4())
    event = dict(event_id=eid, timestamp_utc=ts(), bird_flag=True, bird_probability=0.91, snr_db=14.2,
                 channel_levels={"N": -31, "E": -28, "S": -35, "W": -40}, quality_flag="ok", track_id="trk-1",
                 azimuth_device_deg=62.5, azimuth_geo_deg=152.5, sector="SE", azimuth_confidence=0.78,
                 bearing_quality="good")
    first = send(svc, f"birdnet/{dev}/event", **event)
    assert first.status is Status.STORED and first.event_id == eid
    # Повтор того же пакета и тот же event_id с другим временем — дубликаты.
    assert send(svc, f"birdnet/{dev}/event", **event).status is Status.DUPLICATE
    assert send(svc, f"birdnet/{dev}/event", **{**event, "timestamp_utc": ts(5)}).status is Status.DUPLICATE
    row = db.exec("SELECT client_id, status, channel_levels, snr_db FROM events WHERE event_id = :e", e=eid)
    assert len(row) == 1
    assert row[0].client_id == cid and row[0].status == "received" and row[0].channel_levels["E"] == -28
    b = db.exec("SELECT sector, azimuth_geo_deg, source, bearing_quality FROM bearings WHERE event_id = :e", e=eid)
    assert [tuple(r) for r in b] == [("SE", 152.5, "edge", "good")]


def test_event_without_bearing(engine, db):
    dev = db.device("nb")
    eid = str(uuid.uuid4())
    assert send(IngestService(engine), f"birdnet/{dev}/event", event_id=eid, timestamp_utc=ts()).status \
        is Status.STORED
    assert db.scalar("SELECT count(*) FROM bearings WHERE event_id = :e", e=eid) == 0


def test_unknown_and_retired_devices_rejected(engine, db):
    svc = IngestService(engine)
    r = send(svc, f"birdnet/{db.dev('ghost')}/telemetry", timestamp_utc=ts())
    assert r.status is Status.REJECTED and r.reason == "unknown_device"
    old = db.device("old", status="retired")
    assert send(svc, f"birdnet/{old}/telemetry", timestamp_utc=ts()).reason == "device_retired"
    assert db.scalar("SELECT count(*) FROM telemetry WHERE device_id = :d", d=old) == 0


def test_bad_payloads_rejected_with_reason(engine, db, capsys):
    from backend import logs

    logs.configure()
    dev = db.device("bad")
    svc = IngestService(engine)
    assert run(svc.handle(f"birdnet/{dev}/telemetry", b"{oops")).reason == "bad_json"
    assert run(svc.handle("birdnet/x", b"{}")).reason == "bad_topic"
    assert send(svc, f"birdnet/{dev}/telemetry", timestamp_utc=ts(), quality="good").status is Status.STORED
    out = capsys.readouterr().out
    assert '"reason": "bad_json"' in out and '"event": "rejected"' in out
    assert '"unknown_fields"' in out and '"trace_id"' in out
    assert svc.counters["rejected:bad_json"] == 1 and svc.counters["rejected:bad_topic"] == 1


def test_heartbeat_and_telemetry_in_same_second(engine, db):
    dev = db.device("same")
    svc = IngestService(engine)
    t = ts()
    eid = str(uuid.uuid4())
    assert send(svc, f"birdnet/{dev}/heartbeat", timestamp_utc=t, battery_v=3.7).status is Status.STORED
    assert send(svc, f"birdnet/{dev}/telemetry", timestamp_utc=t, bird_flag=True, event_id=eid).status \
        is Status.STORED
    assert send(svc, f"birdnet/{dev}/telemetry", timestamp_utc=t, bird_flag=True, event_id=eid).status \
        is Status.DUPLICATE
    assert send(svc, f"birdnet/{dev}/heartbeat", timestamp_utc=t, battery_v=3.7).status is Status.DUPLICATE
    assert db.scalar("SELECT count(*) FROM telemetry WHERE device_id = :d", d=dev) == 2
