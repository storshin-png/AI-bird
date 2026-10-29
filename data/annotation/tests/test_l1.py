import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import l1_export  # noqa: E402
import l1_queue  # noqa: E402
from l1_common import read_manifest  # noqa: E402

BASE = ["fragment_id", "source_file", "start_ms", "duration_sec", "rms", "window_config", "label", "fragment_type"]


def write_csv(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


@pytest.fixture
def files(tmp_path):
    manifest = tmp_path / "manifest_fragments.csv"
    rows = [[f"XC1_{i:04d}_{i * 2500}ms.wav", "XC1", i * 2500, 2.5, 0.1, "{}", "", ""] for i in range(40)]
    rows[0][6], rows[0][7] = "bird", "dense"  # уже размечен — в очередь не идёт
    write_csv(manifest, BASE, rows)
    golden = tmp_path / "golden_set.csv"
    write_csv(golden, ["fragment_id", "label", "fragment_type"],
              [["XC1_0001_2500ms.wav", "bird", "sparse"], ["XC1_0002_5000ms.wav", "no_bird", ""]])
    return tmp_path, manifest, golden


def test_queue(files):
    tmp, manifest, golden = files
    out = tmp / "queue.json"
    assert l1_queue.main(["--manifest", str(manifest), "--golden", str(golden), "--out", str(out),
                          "--golden-share", "0.1"]) == 0
    tasks = json.loads(out.read_text(encoding="utf-8"))
    data = [t["data"] for t in tasks]
    new = [d for d in data if d["pass"] == 1 and not d["control"]]
    assert len(new) == 37  # 40 − 1 размеченный − 2 golden
    assert "XC1_0000_0ms.wav" not in {d["fragment_id"] for d in data}
    second = [d for d in data if d["pass"] == 2]
    assert len(second) == 4 and {d["fragment_id"] for d in second} <= {d["fragment_id"] for d in new}
    controls = [d for d in data if d["control"]]
    assert {d["fragment_id"] for d in controls} <= {"XC1_0001_2500ms.wav", "XC1_0002_5000ms.wav"} and controls
    assert data[0]["audio"].startswith("/data/local-files/?d=data/fragments/")
    # Тот же seed — та же очередь.
    out2 = tmp / "queue2.json"
    l1_queue.main(["--manifest", str(manifest), "--golden", str(golden), "--out", str(out2), "--golden-share", "0.1"])
    assert out.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


def test_queue_limit_and_no_golden(files, capsys):
    tmp, manifest, _ = files
    out = tmp / "q.json"
    l1_queue.main(["--manifest", str(manifest), "--golden", str(tmp / "none.csv"), "--out", str(out),
                   "--limit", "10"])
    tasks = json.loads(out.read_text(encoding="utf-8"))
    assert len([t for t in tasks if t["data"]["pass"] == 1]) == 10
    assert "Golden set пуст" in capsys.readouterr().out


def task(fid, pass_no, annotator, label, ftype=None, rating=None, control=False, cancelled=False):
    result = [{"from_name": "bird_label", "type": "choices", "value": {"choices": [label]}}]
    if ftype:
        result.append({"from_name": "fragment_type", "type": "choices", "value": {"choices": [ftype]}})
    if rating:
        result.append({"from_name": "label_confidence", "type": "rating", "value": {"rating": rating}})
    return {"data": {"audio": f"/data/local-files/?d=data/fragments/{fid}", "fragment_id": fid,
                     "pass": pass_no, "control": control},
            "annotations": [{"completed_by": annotator, "result": result, "was_cancelled": cancelled}]}


def run_export(tmp, manifest, golden, items, *extra):
    export = tmp / "export.json"
    export.write_text(json.dumps(items), encoding="utf-8")
    arb = tmp / "arbitration_L1.csv"
    rc = l1_export.main(["--export", str(export), "--manifest", str(manifest), "--output", str(manifest),
                         "--version", "v0.1", "--golden", str(golden), "--arbitration", str(arb), *extra])
    assert rc == 0
    _, rows = read_manifest(manifest)
    return {r["fragment_id"]: r for r in rows}, arb


def test_export_rules(files, capsys):
    tmp, manifest, golden = files
    f = [f"XC1_{i:04d}_{i * 2500}ms.wav" for i in range(40)]
    items = [
        task(f[3], 1, 7, "bird", "dense", rating=3),                       # один проход
        task(f[4], 1, 7, "no_bird"), task(f[4], 2, 8, "no_bird"),            # два прохода совпали
        task(f[5], 1, 7, "bird", "sparse"), task(f[5], 2, 8, "no_bird"),     # расхождение
        task(f[6], 1, 7, "unsure"),                                          # сомнение
        task(f[1], 1, 7, "bird", "sparse", control=True),                    # golden: верно
        task(f[2], 1, 7, "bird", "dense", control=True),                     # golden: ошибка
        task(f[7], 1, {"email": "anna@x"}, "no_bird", "dense"),              # тип у no_bird отбрасывается
        task(f[8], 1, 7, "bird", cancelled=True),                            # отменено
        task("ghost.wav", 1, 7, "bird", "dense"),
    ]
    rows, arb = run_export(tmp, manifest, golden, items)
    assert (rows[f[3]]["label"], rows[f[3]]["fragment_type"], rows[f[3]]["qa_status"]) == ("bird", "dense", "pending")
    assert rows[f[3]]["label_confidence"] == "1.00" and rows[f[3]]["annotation_version"] == "v0.1"
    assert (rows[f[4]]["label"], rows[f[4]]["qa_status"], rows[f[4]]["annotator_id"]) == ("no_bird", "approved", "7+8")
    assert (rows[f[5]]["label"], rows[f[5]]["qa_status"]) == ("", "pending")
    assert (rows[f[6]]["label"], rows[f[6]]["qa_status"]) == ("unsure", "pending")
    assert rows[f[1]]["label"] == "" and rows[f[2]]["label"] == ""  # golden в манифест не пишется
    assert (rows[f[7]]["label"], rows[f[7]]["fragment_type"], rows[f[7]]["annotator_id"]) == ("no_bird", "", "anna@x")
    assert rows[f[8]]["label"] == ""
    with arb.open(encoding="utf-8") as fh:
        arb_rows = list(csv.DictReader(fh))
    assert {(r["fragment_id"], r["reason"]) for r in arb_rows} == {(f[5], "conflict"), (f[6], "unsure")}
    out = capsys.readouterr().out
    assert "Golden set, 7: 1/2 верно — больше 15% расхождений" in out
    assert "Cohen's Kappa по 2 парам" in out and "Нет в манифесте: 1" in out


def test_ornithologist_decisions_survive(files):
    tmp, manifest, golden = files
    f = [f"XC1_{i:04d}_{i * 2500}ms.wav" for i in range(40)]
    items = [task(f[6], 1, 7, "unsure"), task(f[9], 1, 7, "unsure")]
    _, arb = run_export(tmp, manifest, golden, items)
    # Орнитолог решила один фрагмент.
    with arb.open(encoding="utf-8") as fh:
        arb_rows = list(csv.DictReader(fh))
    for r in arb_rows:
        if r["fragment_id"] == f[6]:
            r["label"], r["fragment_type"] = "bird", "truncated"
    with arb.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=l1_export.ARBITRATION_COLUMNS)
        w.writeheader()
        w.writerows(arb_rows)
    rows, arb = run_export(tmp, manifest, golden, items)  # та же выгрузка ещё раз
    assert (rows[f[6]]["label"], rows[f[6]]["fragment_type"], rows[f[6]]["qa_status"]) == ("bird", "truncated", "arbitrated")
    assert rows[f[9]]["label"] == "unsure"
    with arb.open(encoding="utf-8") as fh:
        kept = {r["fragment_id"]: r for r in csv.DictReader(fh)}
    assert kept[f[6]]["label"] == "bird" and kept[f[9]]["label"] == ""


def test_bad_decisions_reported(files, capsys):
    tmp, manifest, golden = files
    arb = tmp / "arbitration_L1.csv"
    write_csv(arb, l1_export.ARBITRATION_COLUMNS, [["XC1_0006_15000ms.wav", "unsure", "7: unsure", "unsure", ""],
                                                   ["XC1_0007_17500ms.wav", "unsure", "7: unsure", "bird", ""],
                                                   ["nope.wav", "unsure", "", "bird", "dense"]])
    run_export(tmp, manifest, golden, [])
    out = capsys.readouterr().out
    assert "должно быть bird или no_bird" in out and "нужен тип" in out and "нет в манифесте" in out


def test_kappa():
    assert l1_export.cohen_kappa([]) is None
    assert l1_export.cohen_kappa([("bird", "bird"), ("no_bird", "no_bird")]) == 1.0
    assert l1_export.cohen_kappa([("bird", "bird")] * 3) == 1.0
    assert l1_export.cohen_kappa([("bird", "no_bird"), ("no_bird", "bird")]) == -1.0


def test_bad_golden_and_manifest(tmp_path):
    from l1_common import read_golden

    g = tmp_path / "g.csv"
    write_csv(g, ["fragment_id", "label"], [["a.wav", "unsure"]])
    with pytest.raises(ValueError, match="golden set"):
        read_golden(g)
    m = tmp_path / "m.csv"
    write_csv(m, ["name"], [["x"]])
    with pytest.raises(ValueError, match="fragment_id"):
        read_manifest(m)
