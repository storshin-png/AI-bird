"""Метки в этих тестах тестовые: эталон проекта ставит только орнитолог."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import l1_golden  # noqa: E402

HEADER = ["fragment_id", "label", "fragment_type"]


def write_csv(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def manifest(tmp_path, n=100):
    path = tmp_path / "m.csv"
    write_csv(path, ["fragment_id", "label", "fragment_type"], [[f"f{i:03d}", "", ""] for i in range(n)])
    return path


def test_pick_writes_empty_labels_and_arbitration_first(tmp_path):
    m = manifest(tmp_path)
    arb = tmp_path / "arb.csv"
    write_csv(arb, ["fragment_id", "reason", "answers", "label", "fragment_type"],
              [["f010", "unsure", "a:unsure", "bird", "sparse"], ["f011", "conflict", "a:bird;b:no_bird", "", ""]])
    out = tmp_path / "cand.csv"
    assert l1_golden.main(["pick", "--manifest", str(m), "--arbitration", str(arb), "--out", str(out),
                           "--golden", str(tmp_path / "none.csv")]) == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 5
    assert rows[0]["fragment_id"] == "f010" and rows[0]["note"] == "арбитраж: bird"
    assert all(r["label"] == "" and r["fragment_type"] == "" for r in rows)
    assert len({r["fragment_id"] for r in rows}) == 5


def test_pick_is_repeatable_and_skips_existing(tmp_path):
    m = manifest(tmp_path)
    golden = tmp_path / "g.csv"
    write_csv(golden, HEADER, [["f001", "bird", "dense"], ["f002", "no_bird", ""]])
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    for out in (a, b):
        l1_golden.main(["pick", "--manifest", str(m), "--golden", str(golden), "--out", str(out),
                        "--arbitration", str(tmp_path / "none.csv")])
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")
    ids = [r["fragment_id"] for r in csv.DictReader(a.open(encoding="utf-8"))]
    assert len(ids) == 3 and not {"f001", "f002"} & set(ids)


def test_check(tmp_path, capsys):
    m = manifest(tmp_path)
    golden = tmp_path / "g.csv"
    assert l1_golden.main(["check", "--manifest", str(m), "--golden", str(golden)]) == 1
    assert "заполняет орнитолог" in capsys.readouterr().out
    write_csv(golden, HEADER, [["f001", "bird", "dense"], ["f002", "no_bird", ""], ["f003", "bird", "dense"],
                               ["f004", "no_bird", ""], ["f005", "bird", "truncated"]])
    assert l1_golden.main(["check", "--manifest", str(m), "--golden", str(golden)]) == 0
    write_csv(golden, HEADER, [["f001", "unsure", ""], ["f002", "bird", ""], ["f002", "no_bird", "dense"],
                               ["zzz", "bird", "dense"]])
    assert l1_golden.main(["check", "--manifest", str(m), "--golden", str(golden)]) == 1
    out = capsys.readouterr().out
    for text in ("метка 'unsure'", "нужен fragment_type", "уже встречался", "должен быть пуст",
                 "нет в манифесте", "нужно около 5"):
        assert text in out, text
