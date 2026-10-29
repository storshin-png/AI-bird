"""Выгрузка разметки L1 из Label Studio в колонки манифеста.

    python data/annotation/l1_export.py --export export.json --manifest data/manifest_fragments.csv \\
        --output data/manifest_fragments.csv --version v0.1

Пишет `label`, `fragment_type`, `label_confidence`, `annotator_id`,
`annotation_version`, `qa_status` (`doc_v2/Структура разметки датасета.md`
§1.2, §1.5) и отчёты для орнитолога:

- `arbitration_L1.csv` — все `unsure` и расхождения двух проходов. Решение
  принимает орнитолог, скрипт его не угадывает;
- Cohen's Kappa по фрагментам с двумя проходами (цель ≥ 0.85, §6.1);
- точность каждого разметчика на golden set (порог отстранения — больше
  15% расхождений, §6.2).

Решения орнитолога: если в `arbitration_L1.csv` вписаны `label` и (для
`bird`) `fragment_type`, выгрузка переносит их в манифест со статусом
`arbitrated` и больше эти фрагменты не трогает. Решённые строки в файле
сохраняются. Golden set тоже не трогается.

qa_status:
- `approved` — два прохода совпали по метке;
- `pending` — один проход, `unsure` или расхождение (метка тогда пустая);
- `arbitrated` — решение орнитолога.
"""

import argparse
import csv
import json
import sys
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from l1_common import LABELS, TYPES, read_golden, read_manifest, write_manifest  # noqa: E402

KAPPA_TARGET = 0.85
GOLDEN_MAX_DISAGREEMENT = 0.15


@dataclass(frozen=True)
class Answer:
    fragment_id: str
    pass_no: int
    control: bool
    annotator: str
    label: str
    fragment_type: str
    confidence: float | None


def _fragment_id(data: dict) -> str:
    if data.get("fragment_id"):
        return str(data["fragment_id"])
    url = urllib.parse.unquote(str(data.get("audio", "")))
    return Path(url.split("?d=")[-1]).name


def _annotator(ann: dict) -> str:
    who = ann.get("completed_by")
    if isinstance(who, dict):
        return str(who.get("email") or who.get("id") or "unknown")
    return str(who) if who is not None else "unknown"


def parse_export(items: list) -> tuple[list[Answer], list[str]]:
    answers, problems = [], []
    for item in items:
        data = item.get("data", {})
        fid = _fragment_id(data)
        for ann in item.get("annotations", []):
            if ann.get("was_cancelled"):
                continue
            label = ftype = ""
            conf = None
            for res in ann.get("result", []):
                value = res.get("value", {})
                if res.get("from_name") == "bird_label" and value.get("choices"):
                    label = value["choices"][0]
                elif res.get("from_name") == "fragment_type" and value.get("choices"):
                    ftype = value["choices"][0]
                elif res.get("from_name") == "label_confidence" and value.get("rating"):
                    conf = round(float(value["rating"]) / 3, 2)
            if label not in LABELS:
                problems.append(f"{fid}: нет метки или неизвестная метка {label!r}")
                continue
            if label != "bird":
                ftype = ""
            elif ftype not in TYPES:
                problems.append(f"{fid}: bird без типа позитива")
                ftype = ""
            answers.append(Answer(fid, int(data.get("pass", 1)), bool(data.get("control", False)),
                                  _annotator(ann), label, ftype, conf))
    return answers, problems


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[c] * right[c] for c in set(left) | set(right)) / (n * n)
    if expected == 1:
        return 1.0
    return round((observed - expected) / (1 - expected), 3)


def apply(answers, rows, golden, version):
    by_id = {r["fragment_id"]: r for r in rows}
    grouped: dict[str, list[Answer]] = defaultdict(list)
    golden_scores: dict[str, list[bool]] = defaultdict(list)
    arbitration, pairs = [], []
    stats = Counter()
    for a in answers:
        if a.control or a.fragment_id in golden:
            if a.fragment_id in golden:
                golden_scores[a.annotator].append(a.label == golden[a.fragment_id]["label"])
            continue
        grouped[a.fragment_id].append(a)

    for fid, items in grouped.items():
        row = by_id.get(fid)
        if row is None:
            stats["not_in_manifest"] += 1
            continue
        if row["qa_status"] == "arbitrated":
            stats["kept_arbitrated"] += 1
            continue
        items.sort(key=lambda a: a.pass_no)
        labels = [a.label for a in items]
        first = items[0]
        if len(items) >= 2:
            pairs.append((items[0].label, items[1].label))
        confs = [a.confidence for a in items if a.confidence is not None]
        row["annotator_id"] = "+".join(dict.fromkeys(a.annotator for a in items))
        row["annotation_version"] = version
        row["label_confidence"] = f"{sum(confs) / len(confs):.2f}" if confs else ""
        if len(set(labels)) > 1:
            row["label"], row["fragment_type"], row["qa_status"] = "", "", "pending"
            arbitration.append((fid, "conflict", items))
            stats["conflict"] += 1
            continue
        row["label"] = first.label
        types = [a.fragment_type for a in items if a.fragment_type]
        row["fragment_type"] = Counter(types).most_common(1)[0][0] if types else ""
        if first.label == "unsure":
            row["qa_status"] = "pending"
            arbitration.append((fid, "unsure", items))
            stats["unsure"] += 1
        else:
            row["qa_status"] = "approved" if len(items) >= 2 else "pending"
            stats[first.label] += 1
    return arbitration, cohen_kappa(pairs), len(pairs), golden_scores, stats


ARBITRATION_COLUMNS = ["fragment_id", "reason", "answers", "label", "fragment_type"]


def read_decisions(path: Path) -> list[dict[str, str]]:
    """Строки файла арбитража, где орнитолог уже вписал label."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [
            {k: (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(f)
            if (row.get("label") or "").strip()
        ]


def apply_decisions(decisions, rows) -> tuple[int, list[str]]:
    """Переносит решения орнитолога в манифест со статусом arbitrated."""
    by_id = {r["fragment_id"]: r for r in rows}
    applied, problems = 0, []
    for d in decisions:
        row = by_id.get(d["fragment_id"])
        if row is None:
            problems.append(f"арбитраж: {d['fragment_id']} нет в манифесте")
            continue
        if d["label"] not in ("bird", "no_bird"):
            problems.append(f"арбитраж: {d['fragment_id']} — решение должно быть bird или no_bird, а не {d['label']!r}")
            continue
        ftype = d.get("fragment_type", "") if d["label"] == "bird" else ""
        if d["label"] == "bird" and ftype not in TYPES:
            problems.append(f"арбитраж: {d['fragment_id']} — для bird нужен тип dense, sparse или truncated")
            continue
        row["label"], row["fragment_type"], row["qa_status"] = d["label"], ftype, "arbitrated"
        applied += 1
    return applied, problems


def write_arbitration(path: Path, arbitration, decisions) -> None:
    """Решённые строки сохраняются как были, ниже — новые на разбор."""
    path.parent.mkdir(parents=True, exist_ok=True)
    decided = {d["fragment_id"] for d in decisions}
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(ARBITRATION_COLUMNS)
        for d in decisions:
            w.writerow([d.get(c, "") for c in ARBITRATION_COLUMNS])
        for fid, reason, items in sorted(arbitration, key=lambda x: x[0]):
            if fid in decided:
                continue
            answers = "; ".join(f"{a.annotator}: {a.label}" + (f"/{a.fragment_type}" if a.fragment_type else "")
                                for a in items)
            # Последние две колонки заполняет орнитолог.
            w.writerow([fid, reason, answers, "", ""])


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="Выгрузка L1 из Label Studio в манифест")
    p.add_argument("--export", type=Path, required=True, help="JSON-экспорт Label Studio")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True, help="можно тот же файл, что --manifest")
    p.add_argument("--version", required=True, help="annotation_version, например v0.1")
    p.add_argument("--golden", type=Path, default=here / "golden_set.csv")
    p.add_argument("--arbitration", type=Path, default=here / "arbitration_L1.csv")
    args = p.parse_args(argv)

    columns, rows = read_manifest(args.manifest)
    golden = read_golden(args.golden)
    decisions = read_decisions(args.arbitration)
    applied, decision_problems = apply_decisions(decisions, rows)
    answers, problems = parse_export(json.loads(args.export.read_text(encoding="utf-8")))
    arbitration, kappa, n_pairs, golden_scores, stats = apply(answers, rows, golden, args.version)
    write_manifest(args.output, columns, rows)
    write_arbitration(args.arbitration, arbitration, decisions)
    problems = decision_problems + problems
    if decisions:
        print(f"Решения орнитолога из {args.arbitration.name} перенесены в манифест: {applied}.")

    print(f"Ответов: {len(answers)}. bird {stats['bird']}, no_bird {stats['no_bird']}, "
          f"unsure {stats['unsure']}, расхождений {stats['conflict']}.")
    if stats["kept_arbitrated"]:
        print(f"Не тронуто решений орнитолога (arbitrated): {stats['kept_arbitrated']}.")
    if stats["not_in_manifest"]:
        print(f"Нет в манифесте: {stats['not_in_manifest']} фрагментов — проверьте, тот ли манифест.")
    print(f"На арбитраж орнитологу: {len(arbitration)} → {args.arbitration}")
    if kappa is None:
        print("Cohen's Kappa: нет фрагментов с двумя проходами.")
    else:
        mark = "в норме" if kappa >= KAPPA_TARGET else f"ниже цели {KAPPA_TARGET}: пересмотреть инструкцию"
        print(f"Cohen's Kappa по {n_pairs} парам: {kappa} — {mark}.")
    for who, scores in sorted(golden_scores.items()):
        miss = 1 - sum(scores) / len(scores)
        flag = " — больше 15% расхождений с golden set" if miss > GOLDEN_MAX_DISAGREEMENT else ""
        print(f"Golden set, {who}: {sum(scores)}/{len(scores)} верно{flag}.")
    birds = [r["fragment_type"] for r in rows if r["label"] == "bird"]
    if birds:
        share = Counter(birds)
        parts = ", ".join(f"{t} {share[t] / len(birds):.0%}" for t in TYPES)
        print(f"Типы позитивов: {parts} (цель 40 / 40 / 20).")
    for msg in problems[:20]:
        print(f"Пропущено: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
