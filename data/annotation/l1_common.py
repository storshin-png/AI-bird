"""Общее для очереди и выгрузки L1: чтение и запись манифеста, golden set.

Только стандартная библиотека: скрипты запускаются на любой машине
разметчика без pandas.
"""

import csv
from pathlib import Path

LABELS = ("bird", "no_bird", "unsure")
TYPES = ("dense", "sparse", "truncated")
# Колонки L1 и служебные из `doc_v2/Структура разметки датасета.md` §1.2 и §1.5.
L1_COLUMNS = ("label", "fragment_type", "label_confidence", "annotator_id", "annotation_version", "qa_status")


def read_manifest(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    if "fragment_id" not in columns:
        raise ValueError(f"в {path} нет колонки fragment_id")
    for col in L1_COLUMNS:
        if col not in columns:
            columns.append(col)
    for row in rows:
        for col in columns:
            row[col] = (row.get(col) or "").strip()
    return columns, rows


def write_manifest(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def read_golden(path: Path | None) -> dict[str, dict[str, str]]:
    """Golden set — файл орнитолога: fragment_id,label,fragment_type.

    Его кладёт в репозиторий человек, не агент. Скрипты только читают.
    """
    if path is None or not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        out = {}
        for row in csv.DictReader(f):
            fid = (row.get("fragment_id") or "").strip()
            label = (row.get("label") or "").strip()
            if not fid:
                continue
            if label not in ("bird", "no_bird"):
                raise ValueError(f"golden set: у {fid} метка {label!r}, нужна bird или no_bird")
            out[fid] = {"label": label, "fragment_type": (row.get("fragment_type") or "").strip()}
        return out
