"""Очередь разметки L1 для Label Studio из манифеста фрагментов.

    python data/annotation/l1_queue.py --manifest data/manifest_fragments.csv --out data/annotation/queue_L1.json

В очередь идут фрагменты без метки. Около 10% из них идут дважды
(проход 2) — для Cohen's Kappa. Фрагменты golden set подмешиваются как
контроль: разметчик их не отличает, а выгрузка сравнивает его ответ с
эталоном орнитолога и в манифест его не пишет.
Правила — `doc_v2/Структура разметки датасета.md` §6.
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from l1_common import read_golden, read_manifest  # noqa: E402

DEFAULT_PREFIX = "/data/local-files/?d=data/fragments/"


def build_queue(rows, golden, prefix=DEFAULT_PREFIX, double_share=0.10, golden_share=0.05,
                limit=None, seed=0):
    rng = random.Random(seed)
    todo = [r["fragment_id"] for r in rows if not r["label"] and r["fragment_id"] not in golden]
    rng.shuffle(todo)
    if limit is not None:
        todo = todo[:limit]
    tasks = [{"fragment_id": fid, "pass": 1, "control": False} for fid in todo]
    n_double = round(len(todo) * double_share)
    tasks += [{"fragment_id": fid, "pass": 2, "control": False} for fid in rng.sample(todo, n_double)]
    known = {r["fragment_id"] for r in rows}
    controls = sorted(fid for fid in golden if fid in known)
    n_control = min(len(controls), round(len(todo) * golden_share)) if todo else 0
    tasks += [{"fragment_id": fid, "pass": 1, "control": True} for fid in rng.sample(controls, n_control)]
    rng.shuffle(tasks)
    return [
        {"data": {"audio": prefix + t["fragment_id"], "fragment_id": t["fragment_id"],
                  "pass": t["pass"], "control": t["control"]}}
        for t in tasks
    ]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Очередь L1 для Label Studio")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True, help="JSON для импорта в Label Studio")
    p.add_argument("--golden", type=Path, default=Path(__file__).resolve().parent / "golden_set.csv")
    p.add_argument("--audio-prefix", default=DEFAULT_PREFIX,
                   help="начало адреса аудио в Label Studio, к нему дописывается fragment_id")
    p.add_argument("--double-share", type=float, default=0.10, help="доля второго прохода, по умолчанию 10%%")
    p.add_argument("--golden-share", type=float, default=0.05, help="доля контроля golden set, по умолчанию 5%%")
    p.add_argument("--limit", type=int, help="сколько новых фрагментов взять в эту очередь")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    _, rows = read_manifest(args.manifest)
    golden = read_golden(args.golden)
    tasks = build_queue(rows, golden, args.audio_prefix, args.double_share, args.golden_share, args.limit, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    passes = sum(1 for t in tasks if t["data"]["pass"] == 2)
    controls = sum(1 for t in tasks if t["data"]["control"])
    print(f"Задач: {len(tasks)} — новых {len(tasks) - passes - controls}, второй проход {passes}, "
          f"контроль golden {controls}. Файл: {args.out}")
    if not golden:
        print("Golden set пуст: контроль точности разметчиков не войдёт в очередь.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
