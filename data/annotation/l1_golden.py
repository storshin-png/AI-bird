"""Заготовка и проверка golden set для орнитолога.

    python data/annotation/l1_golden.py pick --manifest data/manifest_fragments.csv
    python data/annotation/l1_golden.py check --manifest data/manifest_fragments.csv

Golden set размечает только орнитолог (`doc_v2/Структура разметки датасета.md` §6.2).
Скрипт меток не ставит.

`pick` выбирает около 5% фрагментов манифеста и пишет `golden_candidates.csv`
с пустыми `label` и `fragment_type`. Туда же идут фрагменты, решённые
в `arbitration_L1.csv` (§6.3: спорные случаи добавляются в golden set) —
с решением орнитолога как подсказкой в `note`, метку она ставит сама.
Орнитолог прослушивает, ставит метки и сохраняет файл как `golden_set.csv`.

`check` проверяет `golden_set.csv`: метки `bird` / `no_bird`, тип для `bird`,
фрагменты есть в манифесте, повторов нет, размер около 5%.
"""

import argparse
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from l1_common import TYPES, read_manifest  # noqa: E402

HERE = Path(__file__).resolve().parent
COLUMNS = ("fragment_id", "label", "fragment_type", "note")


def read_arbitrated(path: Path) -> dict[str, str]:
    """fragment_id → решение орнитолога из файла арбитража."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {(r.get("fragment_id") or "").strip(): (r.get("label") or "").strip()
                for r in csv.DictReader(f)
                if (r.get("fragment_id") or "").strip() and (r.get("label") or "").strip() in ("bird", "no_bird")}


def pick(rows, arbitrated, share=0.05, seed=0, existing=()):
    rng = random.Random(seed)
    ids = [r["fragment_id"] for r in rows]
    skip = set(existing)
    out = [{"fragment_id": fid, "label": "", "fragment_type": "", "note": f"арбитраж: {arbitrated[fid]}"}
           for fid in ids if fid in arbitrated and fid not in skip]
    taken = skip | {r["fragment_id"] for r in out}
    target = max(1, round(len(ids) * share)) if ids else 0
    pool = [fid for fid in ids if fid not in taken]
    need = max(0, target - len(taken))
    out += [{"fragment_id": fid, "label": "", "fragment_type": "", "note": ""}
            for fid in sorted(rng.sample(pool, min(need, len(pool))))]
    return out


def check(golden_rows, manifest_ids, share=0.05):
    problems, notes, seen = [], [], set()
    for n, r in enumerate(golden_rows, start=2):
        fid = (r.get("fragment_id") or "").strip()
        label = (r.get("label") or "").strip()
        ftype = (r.get("fragment_type") or "").strip()
        if not fid:
            problems.append(f"строка {n}: нет fragment_id")
            continue
        if fid in seen:
            problems.append(f"строка {n}: {fid} уже встречался")
        seen.add(fid)
        if fid not in manifest_ids:
            problems.append(f"строка {n}: {fid} нет в манифесте")
        if label not in ("bird", "no_bird"):
            problems.append(f"строка {n}: {fid} — метка {label!r}, нужна bird или no_bird")
        elif label == "bird" and ftype not in TYPES:
            problems.append(f"строка {n}: {fid} — для bird нужен fragment_type: {', '.join(TYPES)}")
        elif label == "no_bird" and ftype:
            problems.append(f"строка {n}: {fid} — у no_bird fragment_type должен быть пуст")
    target = round(len(manifest_ids) * share)
    if len(seen) < target:
        notes.append(f"в эталоне {len(seen)} фрагментов, для {share:.0%} манифеста нужно около {target}")
    return problems, notes


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Golden set: заготовка и проверка")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("pick", "check"):
        s = sub.add_parser(name)
        s.add_argument("--manifest", type=Path, required=True)
        s.add_argument("--golden", type=Path, default=HERE / "golden_set.csv")
        s.add_argument("--share", type=float, default=0.05, help="доля эталона, по умолчанию 5%%")
    pk = sub.choices["pick"]
    pk.add_argument("--arbitration", type=Path, default=HERE / "arbitration_L1.csv")
    pk.add_argument("--out", type=Path, default=HERE / "golden_candidates.csv")
    pk.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    _, rows = read_manifest(args.manifest)
    if args.cmd == "pick":
        existing = []
        if args.golden.exists():
            with args.golden.open(encoding="utf-8", newline="") as f:
                existing = [(r.get("fragment_id") or "").strip() for r in csv.DictReader(f)]
        cand = pick(rows, read_arbitrated(args.arbitration), args.share, args.seed, existing)
        with args.out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(cand)
        print(f"Кандидатов в эталон: {len(cand)}. Файл: {args.out}")
        print("Метки ставит орнитолог; готовый файл сохранить как golden_set.csv (колонку note можно оставить).")
        return 0

    if not args.golden.exists():
        print(f"{args.golden.name} ещё нет: эталон заполняет орнитолог.")
        return 1
    with args.golden.open(encoding="utf-8", newline="") as f:
        golden_rows = list(csv.DictReader(f))
    problems, notes = check(golden_rows, {r["fragment_id"] for r in rows}, args.share)
    for x in problems:
        print(f"  - {x}")
    for x in notes:
        print(f"  · {x}")
    print(f"Эталон: {len(golden_rows)} строк, ошибок {len(problems)}.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
