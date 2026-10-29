"""Строки здесь тестовые, в таблицы стенда они не попадают."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_stand as cs  # noqa: E402


def write(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def rays(sid, lengths):
    return [{"session_id": sid, "ray": r, "free_length_m": str(lengths.get(r, 60)), "skip_reason": ""}
            for r in cs.RAYS]


def marks(sid, plan, quality="good"):
    rows = []
    for ray, dists in plan.items():
        for d in dists:
            rows.append({"session_id": sid, "device_id": "sensor-001", "file": f"{sid}_{ray}_{d}.wav",
                         "azimuth_deg": str(cs.RAYS[ray]), "sector": ray, "distance_m": str(d),
                         "num_sources": "1", "bearing_quality": quality, "notes": ""})
    return rows


def run(tmp_path, ray_rows, session_rows, extra=()):
    r, s = tmp_path / "r.csv", tmp_path / "s.csv"
    write(r, cs.RAY_COLUMNS, ray_rows)
    write(s, cs.SESSION_COLUMNS, session_rows)
    return cs.main(["--rays", str(r), "--session", str(s), *extra])


def test_repo_tables_are_headers_only():
    for name, cols in (("stand_rays.csv", cs.RAY_COLUMNS), ("stand_session.csv", cs.SESSION_COLUMNS)):
        lines = Path(cs.__file__).with_name(name).read_text(encoding="utf-8").splitlines()
        assert lines == [",".join(cols)]
    assert cs.main([]) == 0


def test_sector_of_matches_stand_table():
    assert [cs.sector_of(a) for a in (0, 22.4, 22.5, 90, 157.5, 337.4, 337.5, 359.9)] == \
        ["N", "N", "NE", "E", "S", "NW", "N", "N"]
    assert cs.required_marks(4.9) == () and cs.required_marks(12) == (5, 10) and cs.required_marks(50) == (5, 10, 20, 50)


def test_full_session_and_ml_table(tmp_path, capsys):
    lengths = {"W": 3, "S": 15}
    plan = {r: cs.required_marks(lengths.get(r, 60)) for r in cs.RAYS}
    out = tmp_path / "l5.csv"
    assert run(tmp_path, rays("s1", lengths), marks("s1", plan), ["--ml-csv", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Сессия s1: снята как стенд" in text
    ml = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(ml) == 6 * 4 + 2 and set(ml[0]) == set(cs.ML_COLUMNS)


def test_problems(tmp_path, capsys):
    plan = {r: (5, 10, 20, 50) for r in cs.RAYS}
    rows = marks("s2", plan)
    rows = [x for x in rows if x["file"] != "s2_E_10.wav"]           # пропущена ближняя отметка
    rows[0]["sector"] = "NE"                                          # сектор не тот
    rows[1]["distance_m"] = "15"                                      # не отметка стенда
    rows[2]["bearing_quality"] = "great"
    rows.append({**rows[3], "file": rows[3]["file"]})                 # повтор файла
    rows.append({**rows[4], "file": "odd.wav", "azimuth_deg": "30", "sector": "NE", "bearing_quality": "good"})
    ray_rows = rays("s2", {"N": 8})
    assert run(tmp_path, ray_rows, rows) == 1
    text = capsys.readouterr().out
    for t in ("не совпадает с азимутом", "только 5, 10, 20, 50", "bearing_quality 'great'", "уже встречался",
              "good для отметки не на луче", "луч E (свободен 60 м): не снято 10 м",
              "луч N свободен на 8 м, а отметка 20 м"):
        assert t in text, t


def test_not_a_stand_and_pending_quality(tmp_path, capsys):
    rows = marks("s3", {"N": (10,)}, quality="")
    assert run(tmp_path, rays("s3", {}), rows) == 1
    text = capsys.readouterr().out
    assert "не сессия стенда" in text and "ждут орнитолога" in text
    assert "нет лучей" not in text


def test_missing_rays_and_columns(tmp_path, capsys):
    assert run(tmp_path, rays("s4", {})[:6], marks("s4", {"N": (5,)})) == 1
    assert "нет лучей: W, NW" in capsys.readouterr().out
    bad = tmp_path / "bad.csv"
    bad.write_text("session_id\n", encoding="utf-8")
    assert cs.main(["--rays", str(bad), "--session", str(bad)]) == 2
