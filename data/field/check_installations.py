"""Проверка `installations.csv` по правилу формы установки.

    python data/field/check_installations.py
    python data/field/check_installations.py --csv data/field/installations.csv --devices-json devices.json

Правило из `installation.md`: без ориентации и четырёх живых каналов
установка в пилот не закрывается. Скрипт ничего не дописывает в таблицу,
только сообщает, какие строки закрыты, а какие нет и почему.

`--devices-json` пишет тела запросов `POST /api/v1/devices` для закрытых
установок — чтобы карточка в облаке совпала с бумажной формой
(`doc_v2/roles/07_FIELD_OPS.md`, спринт 5). В сеть скрипт не ходит.
Только стандартная библиотека.
"""

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

COLUMNS = [
    "device_id", "gps_lat", "gps_lon", "install_height_m", "orientation_deg", "mic_layout", "install_date",
    "habitat_type", "field_notes", "photo_ref", "ch_n_live", "ch_e_live", "ch_s_live", "ch_w_live",
]
CHANNELS = ("ch_n_live", "ch_e_live", "ch_s_live", "ch_w_live")
YES = {"да", "yes", "true", "1"}
NO = {"нет", "no", "false", "0"}
# Значения habitat из `doc_v2/Структура разметки датасета.md` §1.3.
HABITATS = {"forest", "field", "wetland", "urban", "mixed"}
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _float(value: str, low: float, high: float, name: str, problems: list[str], high_open=False):
    try:
        x = float(value.replace(",", "."))
    except ValueError:
        problems.append(f"{name}: не число ({value!r})")
        return None
    if x < low or x > high or (high_open and x == high):
        problems.append(f"{name}: {x} вне {low}…{high}")
        return None
    return x


def check_row(row: dict[str, str]) -> tuple[list[str], list[str]]:
    """Возвращает (почему не закрыта, предупреждения)."""
    blockers, warnings = [], []
    v = {k: (row.get(k) or "").strip() for k in COLUMNS}
    if not DEVICE_ID_RE.match(v["device_id"]):
        blockers.append(f"device_id: {v['device_id']!r} — латиница, цифры, . _ -, до 64 символов")
    if not v["orientation_deg"]:
        blockers.append("orientation_deg пуст — без ориентации установка не закрывается")
    else:
        _float(v["orientation_deg"], 0, 360, "orientation_deg", blockers, high_open=True)
    for ch in CHANNELS:
        state = v[ch].lower()
        if state in NO:
            blockers.append(f"канал {ch[3].upper()} не живой — датчик на точке не оставляют")
        elif state not in YES:
            blockers.append(f"канал {ch[3].upper()}: не отмечен (да/нет)")
    if v["mic_layout"] != "N/E/S/W":
        blockers.append(f"mic_layout: {v['mic_layout']!r}, форма допускает только N/E/S/W")
    if not v["gps_lat"] or not v["gps_lon"]:
        blockers.append("нет gps_lat или gps_lon")
    else:
        _float(v["gps_lat"], -90, 90, "gps_lat", blockers)
        _float(v["gps_lon"], -180, 180, "gps_lon", blockers)
    if v["install_height_m"]:
        _float(v["install_height_m"], 0, 50, "install_height_m", warnings)
    else:
        warnings.append("install_height_m пуст")
    try:
        date.fromisoformat(v["install_date"])
    except ValueError:
        blockers.append(f"install_date: {v['install_date']!r}, нужна дата ГГГГ-ММ-ДД")
    if v["habitat_type"] and v["habitat_type"] not in HABITATS:
        warnings.append(f"habitat_type: {v['habitat_type']!r} — в манифесте разметки допустимы {', '.join(sorted(HABITATS))}")
    if not v["photo_ref"]:
        warnings.append("нет photo_ref")
    return blockers, warnings


def device_body(row: dict[str, str]) -> dict:
    notes = "; ".join(x for x in (row.get("habitat_type", "").strip(), row.get("field_notes", "").strip(),
                                   f"фото: {row['photo_ref'].strip()}" if row.get("photo_ref", "").strip() else "") if x)
    return {
        "device_id": row["device_id"].strip(),
        "latitude": float(row["gps_lat"].replace(",", ".")),
        "longitude": float(row["gps_lon"].replace(",", ".")),
        "orientation_deg": float(row["orientation_deg"].replace(",", ".")),
        "installed_at": f"{row['install_date'].strip()}T00:00:00Z",
        "status": "active",
        "notes": notes or None,
    }


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="Проверка таблицы установок")
    p.add_argument("--csv", type=Path, default=here / "installations.csv")
    p.add_argument("--devices-json", type=Path, help="куда записать тела POST /api/v1/devices для закрытых установок")
    args = p.parse_args(argv)

    with args.csv.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            print(f"В {args.csv.name} нет колонок: {', '.join(missing)}")
            return 2
        rows = list(reader)
    if not rows:
        print(f"{args.csv.name}: записей пока нет.")
        return 0

    closed, open_rows, seen = [], 0, set()
    for n, row in enumerate(rows, start=2):
        blockers, warnings = check_row(row)
        dev = (row.get("device_id") or "").strip()
        if dev in seen:
            blockers.append(f"device_id {dev} уже встречался выше: одна строка — одна установка")
        seen.add(dev)
        if blockers:
            open_rows += 1
            print(f"Строка {n}, {dev or '—'}: НЕ закрыта для пилота")
            for b in blockers:
                print(f"  - {b}")
        else:
            closed.append(row)
            print(f"Строка {n}, {dev}: закрыта")
        for w in warnings:
            print(f"  · {w}")
    print(f"Итого: закрыто {len(closed)}, не закрыто {open_rows}.")
    if args.devices_json:
        args.devices_json.write_text(json.dumps([device_body(r) for r in closed], ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        print(f"Тела запросов для облака: {args.devices_json}")
    return 1 if open_rows else 0


if __name__ == "__main__":
    sys.exit(main())
