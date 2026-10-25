import array
import json
import math
import random
import uuid
import wave
from datetime import UTC, datetime, timedelta

import pytest

from backend.payloads import Kind, Topic, parse_payload
from simulator import __main__ as cli
from simulator.geometry import channel_response, device_azimuth, sector
from simulator.scenario import make_devices, make_events
from simulator.wav import CONFIG_PATH, WavFormat, load_format, synthesize


# --- геометрия ------------------------------------------------------------

@pytest.mark.parametrize(
    "az,expected",
    [(0, "N"), (22.4, "N"), (22.5, "NE"), (67.5, "E"), (112.5, "SE"), (157.5, "S"),
     (202.5, "SW"), (247.5, "W"), (292.5, "NW"), (337.4, "NW"), (337.5, "N"), (359.9, "N"), (360, "N")],
)
def test_sector_table_from_stand(az, expected):
    assert sector(az) == expected


def test_device_azimuth():
    assert device_azimuth(152.5, 90.0) == 62.5
    assert device_azimuth(10.0, 350.0) == 20.0


@pytest.mark.parametrize("az,loud,quiet", [(0, "N", "S"), (90, "E", "W"), (180, "S", "N"), (270, "W", "E")])
def test_facing_channel_is_loudest_and_earliest(az, loud, quiet):
    r = channel_response(az, 0.03, 44100)
    assert max(r, key=lambda c: r[c][0]) == loud and min(r, key=lambda c: r[c][0]) == quiet
    assert r[loud][1] == 0 and r[quiet][1] == max(d for _, d in r.values()) > 0


# --- WAV ------------------------------------------------------------------

def test_format_comes_from_window_config():
    fmt = load_format()
    text = CONFIG_PATH.read_text(encoding="utf-8")
    assert f"sample_rate: {fmt.sample_rate}" in text
    assert (fmt.sample_rate, fmt.seconds, fmt.pre_roll_sec) == (44100, 10.0, 2.0)


def test_missing_config_key(tmp_path):
    bad = tmp_path / "w.yaml"
    bad.write_text("sample_rate: 44100\n", encoding="utf-8")
    with pytest.raises(ValueError, match="event_wav_sec"):
        load_format(bad)


def _rms(samples):
    return math.sqrt(sum(x * x for x in samples) / len(samples))


def test_wav_is_4ch_16bit_and_points_to_source(tmp_path):
    fmt = WavFormat(sample_rate=8000, seconds=3.0, pre_roll_sec=1.0)  # короткий, чтобы тест шёл быстро
    path = tmp_path / "e.wav"
    synthesize(path, azimuth_device_deg=90.0, fmt=fmt, seed=1)
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (4, 2, 8000, 24000)
        pcm = array.array("h", w.readframes(w.getnframes()))
    channels = {name: pcm[i::4] for i, name in enumerate("NESW")}
    pre = 8000  # pre-roll 1 с — только фон
    after = {n: _rms(ch[pre:2 * pre]) for n, ch in channels.items()}
    before = {n: _rms(ch[:pre]) for n, ch in channels.items()}
    assert max(after, key=after.get) == "E" and min(after, key=after.get) == "W"
    assert all(after[n] > 2 * before[n] for n in "NES")


def test_wav_is_deterministic(tmp_path):
    fmt = WavFormat(sample_rate=8000, seconds=2.0, pre_roll_sec=0.5)
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    synthesize(a, 45.0, fmt, seed=5)
    synthesize(b, 45.0, fmt, seed=5)
    assert a.read_bytes() == b.read_bytes()


# --- сценарий ---------------------------------------------------------------

START = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)


def _scenario(seed=3):
    rng = random.Random(seed)
    devices = make_devices(3, rng)
    return devices, make_events(devices, tracks=4, singles=5, start=START, rng=rng)


def test_scenario_is_deterministic_and_well_formed():
    devices, events = _scenario()
    _, again = _scenario()
    assert [e.event_id for e in events] == [e.event_id for e in again]
    assert [d.device_id for d in devices] == ["sim-001", "sim-002", "sim-003"]
    assert all(uuid.UUID(e.event_id).version == 4 for e in events)
    assert len({e.event_id for e in events}) == len(events)
    assert sum(1 for e in events if e.track_id is None) == 5
    assert [e.timestamp for e in events] == sorted(e.timestamp for e in events)
    for d in devices:
        assert abs(d.latitude - 53.41) < 0.05 and abs(d.longitude - 58.98) < 0.06


def test_local_tracks_drift_consistently():
    _, events = _scenario()
    tracks: dict[str, list] = {}
    for e in events:
        if e.track_id:
            tracks.setdefault(e.track_id, []).append(e)
    assert len(tracks) == 4
    for items in tracks.values():
        assert 3 <= len(items) <= 5 and len({e.device.device_id for e in items}) == 1
        steps = [((b.azimuth_geo_deg - a.azimuth_geo_deg + 180) % 360) - 180 for a, b in zip(items, items[1:])]
        assert all(2 <= abs(s) <= 11 for s in steps) and len({s > 0 for s in steps}) == 1


def test_payloads_pass_backend_validation():
    _, events = _scenario()
    now = events[-1].timestamp + timedelta(minutes=1)
    for e in events:
        ev = parse_payload(Topic(e.device.device_id, Kind.EVENT), json.dumps(e.event_payload()).encode(), now)
        assert ev.unknown_fields == [] and ev.has_bearing and ev.sector == sector(e.azimuth_geo_deg)
        assert max(ev.channel_levels, key=ev.channel_levels.get) == max(
            "NESW", key=lambda c: channel_response(e.azimuth_device_deg, 0.03, 44100)[c][0])
        tel = parse_payload(Topic(e.device.device_id, Kind.TELEMETRY),
                            json.dumps(e.telemetry_payload(3.7, -5.0)).encode(), now)
        assert tel.unknown_fields == [] and str(tel.event_id) == e.event_id
    assert events[0].wav_name.startswith("2026-10-25_03-00-00_sim-")
    assert events[0].wav_name.endswith(f"_evt-{events[0].event_id}.wav")


# --- командная строка -------------------------------------------------------

def test_cli_writes_manifest_without_wav(tmp_path, capsys):
    assert cli.main(["--seed", "4", "--out", str(tmp_path), "--no-wav", "--start", "2026-10-25T03:00:00+00:00"]) == 0
    rows = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and all(r["wav"] is None for r in rows)
    assert {"event_id", "true_azimuth_geo_deg", "orientation_deg", "track_id"} <= set(rows[0])
    assert "seed 4" in capsys.readouterr().out


def test_cli_writes_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_format", lambda: WavFormat(8000, 1.0, 0.2))
    cli.main(["--seed", "4", "--out", str(tmp_path), "--tracks", "0", "--singles", "2",
              "--start", "2026-10-25T03:00:00+00:00"])
    rows = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and all((tmp_path / r["wav"]).exists() for r in rows)


def test_cli_rejects_bad_start(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["--out", str(tmp_path), "--no-wav", "--start", "2026-10-25T03:00:00"])
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    with pytest.raises(SystemExit):
        cli.main(["--out", str(tmp_path), "--no-wav", "--start", future])


def test_cli_publishes_in_order(tmp_path, monkeypatch):
    sent = []

    class FakePublisher:
        def __init__(self, host, port, prefix):
            assert (host, port, prefix) == ("broker", 1884, "birdnet")
            self.sent = 0

        def send(self, device_id, kind, payload):
            sent.append((device_id, kind, payload))
            self.sent += 1

        def close(self):
            pass

    monkeypatch.setattr(cli, "Publisher", FakePublisher)
    cli.main(["--seed", "4", "--out", str(tmp_path), "--no-wav", "--devices", "2", "--tracks", "1", "--singles", "1",
              "--start", "2026-10-25T03:00:00+00:00", "--mqtt", "broker:1884"])
    kinds = [k for _, k, _ in sent]
    assert kinds[:2] == ["heartbeat", "heartbeat"] and kinds[2:4] == ["event", "telemetry"]
    hb, first_event = sent[0][2], sent[2][2]
    assert hb["timestamp_utc"] < first_event["timestamp_utc"]


# --- сквозной прогон: генератор → брокер → backend → БД --------------------

def test_end_to_end_with_backend(tmp_path):
    from backend.config import Settings
    from backend.tests.conftest import DB_URL, MQTT, Db, run
    from backend.tests.test_mqtt import Runner, wait_for

    if not (DB_URL and MQTT):
        pytest.skip("нужны AIBIRD_TEST_DATABASE_URL и AIBIRD_TEST_MQTT")
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(DB_URL, poolclass=NullPool)
    db = Db(engine)
    host, port = MQTT.split(":")
    topic_prefix = f"birdnet-{db.tag}"
    settings = Settings(mqtt_host=host, mqtt_port=int(port), mqtt_topic_prefix=topic_prefix,
                        mqtt_client_id=f"sim-{db.tag}")
    start = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    args = ["--seed", "9", "--out", str(tmp_path), "--no-wav", "--devices", "2", "--tracks", "2", "--singles", "2",
            "--prefix", f"t{db.tag}-sim", "--start", start, "--register", "--database-url", DB_URL,
            "--mqtt", MQTT, "--topic-prefix", topic_prefix]
    try:
        with Runner(settings, DB_URL) as r:
            assert r.ready.wait(10)
            assert cli.main(args) == 0
            rows = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
            expected = 2 + 2 * len(rows)  # heartbeat на датчик + событие и телеметрия на каждое событие
            assert wait_for(lambda: sum(r.ingest.counters.values()) >= expected), r.ingest.counters
            assert r.ingest.counters == {"stored": expected}
            # Тот же seed ещё раз: всё — дубликаты.
            assert cli.main(args) == 0
            assert wait_for(lambda: r.ingest.counters.get("duplicate", 0) >= expected)
        like = f"t{db.tag}-sim-%"
        assert db.scalar("SELECT count(*) FROM events WHERE device_id LIKE :p", p=like) == len(rows)
        assert db.scalar("SELECT count(*) FROM bearings WHERE device_id LIKE :p", p=like) == len(rows)
        assert db.scalar("SELECT count(*) FROM telemetry WHERE device_id LIKE :p", p=like) == len(rows) + 2
    finally:
        db.cleanup()
        run(engine.dispose())
