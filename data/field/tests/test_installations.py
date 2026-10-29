"""Строки здесь — тестовые, в репозиторную таблицу они не попадают."""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_installations as ci  # noqa: E402

GOOD = {
    "device_id": "sensor-001", "gps_lat": "10.5", "gps_lon": "20,25", "install_height_m": "4",
    "orientation_deg": "12.5", "mic_layout": "N/E/S/W", "install_date": "2026-12-20", "habitat_type": "forest",
    "field_notes": "береза у опушки", "photo_ref": "IMG_0001", "ch_n_live": "да", "ch_e_live": "да",
    "ch_s_live": "yes", "ch_w_live": "1",
}


def write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ci.COLUMNS)
        w.writeheader()
        w.writerows(rows)


def test_repo_table_has_form_columns_and_no_records():
    table = Path(ci.__file__).with_name("installations.csv")
    with table.open(encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines == [",".join(ci.COLUMNS)]
    form = Path(ci.__file__).with_name("installation.md").read_text(encoding="utf-8")
    for col in ci.COLUMNS[:10]:
        assert f"`{col}`" in form


def test_empty_table(capsys):
    assert ci.main([]) == 0
    assert "записей пока нет" in capsys.readouterr().out


def test_good_row_closes(tmp_path, capsys):
    path = tmp_path / "i.csv"
    write(path, [GOOD])
    out_json = tmp_path / "devices.json"
    assert ci.main(["--csv", str(path), "--devices-json", str(out_json)]) == 0
    assert "sensor-001: закрыта" in capsys.readouterr().out
    body = json.loads(out_json.read_text(encoding="utf-8"))[0]
    assert body == {"device_id": "sensor-001", "latitude": 10.5, "longitude": 20.25, "orientation_deg": 12.5,
                    "installed_at": "2026-12-20T00:00:00Z", "status": "active",
                    "notes": "forest; береза у опушки; фото: IMG_0001"}


def test_blockers(tmp_path, capsys):
    rows = [
        {**GOOD, "device_id": "s-2", "orientation_deg": ""},
        {**GOOD, "device_id": "s-3", "ch_w_live": "нет"},
        {**GOOD, "device_id": "s-4", "ch_e_live": ""},
        {**GOOD, "device_id": "s-5", "mic_layout": "N/S/E/W", "orientation_deg": "360"},
        {**GOOD, "device_id": "s-6", "gps_lat": "", "install_date": "20.12.2026"},
        {**GOOD, "device_id": "s 7", "gps_lon": "abc", "gps_lat": "95"},
        {**GOOD},
        {**GOOD},
    ]
    path = tmp_path / "i.csv"
    write(path, rows)
    assert ci.main(["--csv", str(path)]) == 1
    out = capsys.readouterr().out
    for text in ("без ориентации", "канал W не живой", "канал E: не отмечен", "только N/E/S/W",
                 "orientation_deg: 360.0 вне", "нет gps_lat", "нужна дата", "device_id: 's 7'",
                 "gps_lon: не число", "gps_lat: 95.0 вне", "уже встречался"):
        assert text in out, text
    assert "Итого: закрыто 1, не закрыто 7." in out


def test_warnings_do_not_block(tmp_path, capsys):
    path = tmp_path / "i.csv"
    write(path, [{**GOOD, "habitat_type": "болото", "photo_ref": "", "install_height_m": ""}])
    assert ci.main(["--csv", str(path)]) == 0
    out = capsys.readouterr().out
    assert "habitat_type: 'болото'" in out and "нет photo_ref" in out and "install_height_m пуст" in out


def test_missing_columns(tmp_path, capsys):
    path = tmp_path / "i.csv"
    path.write_text("device_id,gps_lat\n", encoding="utf-8")
    assert ci.main(["--csv", str(path)]) == 2
    assert "нет колонок" in capsys.readouterr().out
