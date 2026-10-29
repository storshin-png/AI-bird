"""Проверка журнала стенда направления по чертежу `hardware/STAND.md`.

    python data/field/check_stand.py
    python data/field/check_stand.py --ml-csv l5.csv

Читает `stand_rays.csv` (свободная длина каждого луча) и `stand_session.csv`
(снятые отметки). Ничего не дописывает в таблицы, только сообщает:
снята ли сессия как стенд, каких отметок не хватает, какие строки
противоречат чертежу и где ещё нет `bearing_quality` от орнитолога.

`--ml-csv` пишет таблицу для ML: file, azimuth_deg, sector, distance_m,
bearing_quality — только для строк, где орнитолог уже поставил качество.
Только стандартная библиотека.
"""

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAYS = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
MARKS = (5, 10, 20, 50)
QUALITY = ("good", "medium", "poor", "ambiguous")
RAY_COLUMNS = ["session_id", "ray", "free_length_m", "skip_reason"]
SESSION_COLUMNS = ["session_id", "device_id", "file", "azimuth_deg", "sector", "distance_m", "num_sources",
                   "bearing_quality", "notes"]
ML_COLUMNS = ["file", "azimuth_deg", "sector", "distance_m", "bearing_quality"]


def sector_of(azimuth: float) -> str:
    """Сектор по азимуту — таблица «Сектор по азимуту» в STAND.md."""
    a = azimuth % 360
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return names[int(((a + 22.5) % 360) // 45)]


def required_marks(free_length: float) -> tuple[int, ...]:
    return tuple(m for m in MARKS if free_length >= m)


def _num(value: str):
    try:
        return float((value or "").strip().replace(",", "."))
    except ValueError:
        return None


def read_table(path: Path, columns: list[str]):
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        rows = [{k: (r.get(k) or "").strip() for k in columns} for r in reader]
    return missing, rows


def check(rays_rows, session_rows):
    """Возвращает {session_id: {"problems": [...], "notes": [...], "is_stand": bool}}."""
    out: dict[str, dict] = {}

    def entry(sid):
        return out.setdefault(sid, {"problems": [], "notes": [], "is_stand": False})

    free: dict[str, dict[str, float]] = {}
    for n, r in enumerate(rays_rows, start=2):
        sid, ray = r["session_id"], r["ray"].upper()
        e = entry(sid or "—")
        if not sid:
            e["problems"].append(f"stand_rays.csv строка {n}: нет session_id")
            continue
        if ray not in RAYS:
            e["problems"].append(f"stand_rays.csv строка {n}: луч {r['ray']!r}, нужен один из {', '.join(RAYS)}")
            continue
        length = _num(r["free_length_m"])
        if length is None or length < 0:
            e["problems"].append(f"stand_rays.csv строка {n}: луч {ray} — free_length_m {r['free_length_m']!r} не число")
            continue
        if ray in free.setdefault(sid, {}):
            e["problems"].append(f"stand_rays.csv строка {n}: луч {ray} уже записан в этой сессии")
        free[sid][ray] = length

    taken: dict[str, dict[str, set]] = {}
    files = set()
    for n, r in enumerate(session_rows, start=2):
        sid = r["session_id"]
        e = entry(sid or "—")
        where = f"stand_session.csv строка {n}"
        if not sid:
            e["problems"].append(f"{where}: нет session_id")
            continue
        if not r["device_id"]:
            e["problems"].append(f"{where}: нет device_id")
        if not r["file"]:
            e["problems"].append(f"{where}: нет file")
        elif r["file"] in files:
            e["problems"].append(f"{where}: файл {r['file']} уже встречался — одна запись, одна строка")
        files.add(r["file"])
        az = _num(r["azimuth_deg"])
        if az is None or not 0 <= az < 360:
            e["problems"].append(f"{where}: azimuth_deg {r['azimuth_deg']!r}, нужно 0…360")
            continue
        sector = r["sector"].upper()
        if sector != sector_of(az):
            e["problems"].append(f"{where}: sector {r['sector']!r} не совпадает с азимутом {az:g}° ({sector_of(az)})")
        dist = _num(r["distance_m"])
        if dist not in MARKS:
            e["problems"].append(f"{where}: distance_m {r['distance_m']!r}, на стенде только 5, 10, 20, 50")
            continue
        if r["num_sources"] and r["num_sources"] != "1":
            e["notes"].append(f"{where}: num_sources {r['num_sources']} — на стенде один источник, "
                              "качество такой записи — ambiguous")
        q = r["bearing_quality"]
        if q and q not in QUALITY:
            e["problems"].append(f"{where}: bearing_quality {q!r}, нужно {', '.join(QUALITY)}")
        on_ray = next((ray for ray, deg in RAYS.items() if deg == az), None)
        if on_ray is None:
            e["notes"].append(f"{where}: {az:g}° не на луче чертежа — для такой отметки качество не выше medium")
            if q == "good":
                e["problems"].append(f"{where}: good для отметки не на луче чертежа")
            continue
        rays = free.get(sid, {})
        if on_ray in rays and dist > rays[on_ray]:
            e["problems"].append(f"{where}: луч {on_ray} свободен на {rays[on_ray]:g} м, а отметка {dist:g} м")
        taken.setdefault(sid, {}).setdefault(on_ray, set()).add(dist)

    for sid, e in out.items():
        if sid == "—":
            continue
        rays = free.get(sid, {})
        missing_rays = [r for r in RAYS if r not in rays]
        if missing_rays:
            e["problems"].append(f"в stand_rays.csv нет лучей: {', '.join(missing_rays)}")
        for ray, length in rays.items():
            need = set(required_marks(length))
            have = taken.get(sid, {}).get(ray, set())
            lost = sorted(need - have)
            if lost:
                e["problems"].append(f"луч {ray} (свободен {length:g} м): не снято {', '.join(f'{m:g}' for m in lost)} м")
        e["is_stand"] = any(5 in marks for marks in taken.get(sid, {}).values())
        if not e["is_stand"]:
            e["problems"].append("ни один луч не снят на 5 м — это не сессия стенда")
        pending = sum(1 for r in session_rows if r["session_id"] == sid and not r["bearing_quality"])
        if pending:
            e["notes"].append(f"без bearing_quality: {pending} — ждут орнитолога")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Проверка журнала стенда направления")
    p.add_argument("--rays", type=Path, default=HERE / "stand_rays.csv")
    p.add_argument("--session", type=Path, default=HERE / "stand_session.csv")
    p.add_argument("--ml-csv", type=Path, help="куда записать таблицу L5 для ML")
    args = p.parse_args(argv)

    missing_r, rays_rows = read_table(args.rays, RAY_COLUMNS)
    missing_s, session_rows = read_table(args.session, SESSION_COLUMNS)
    if missing_r or missing_s:
        if missing_r:
            print(f"В {args.rays.name} нет колонок: {', '.join(missing_r)}")
        if missing_s:
            print(f"В {args.session.name} нет колонок: {', '.join(missing_s)}")
        return 2
    if not rays_rows and not session_rows:
        print("Сессий стенда пока нет.")
        return 0

    result = check(rays_rows, session_rows)
    bad = 0
    for sid in sorted(result):
        e = result[sid]
        status = "снята как стенд" if e["is_stand"] and not e["problems"] else "есть замечания"
        print(f"Сессия {sid}: {status}")
        for x in e["problems"]:
            print(f"  - {x}")
        for x in e["notes"]:
            print(f"  · {x}")
        bad += bool(e["problems"])
    ready = [r for r in session_rows if r["bearing_quality"] in QUALITY]
    print(f"Итого: сессий {len(result)}, с замечаниями {bad}; записей {len(session_rows)}, "
          f"с bearing_quality {len(ready)}.")
    if args.ml_csv:
        with args.ml_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=ML_COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(ready)
        print(f"Таблица для ML: {args.ml_csv}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
