"""
Валидация датасета по критериям DATASET_STRATEGY v2.1.
Проверяет:
- единый конфиг окна анализа;
- баланс классов NN1;
- распределение типов позитивов (плотный/разреженный/обрезанный);
- сплиты (test set = только полевые данные);
- наличие и размеры спектрограмм;
- критерии готовности датасета (раздел 13).
"""

import json
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter


# ============================================================
# ЕДИНЫЙ КОНФИГ ОКНА АНАЛИЗА (из DATASET_STRATEGY / ARCHITECTURE / MVP_SPEC)
# ============================================================
EXPECTED_CONFIG = {
    "window_sec": 2.5,
    "sr": 44100,
    "n_fft": 1024,
    "hop_spectro": 512,
    "window_fn": "hann",
    "fmax": 22050,
    "repr": "log_mel",
    "n_mels": 128,
}

# Целевое распределение позитивов (DATASET_STRATEGY, раздел 3)
TARGET_DISTRIBUTION = {
    "dense": 0.40,
    "sparse": 0.40,
    "truncated": 0.20,
}

# Допустимый баланс (раздел 13)
BALANCE_MIN = 0.8
BALANCE_MAX = 1.2

# Целевая согласованность разметки
KAPPA_TARGET = 0.85


def print_header(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def validate(manifest_path: str, spectro_dir: str):
    manifest_path = Path(manifest_path)
    spectro_dir = Path(spectro_dir)

    print_header("ВАЛИДАЦИЯ ДАТАСЕТА (DATASET_STRATEGY v2.1)")

    # --- Проверка существования файлов ---
    if not manifest_path.exists():
        print(f"[FAIL] Манифест не найден: {manifest_path}")
        return
    if not spectro_dir.exists():
        print(f"[FAIL] Папка спектрограмм не найдена: {spectro_dir}")
        return

    df = pd.read_csv(manifest_path)
    total = len(df)
    print(f"Всего фрагментов в манифесте: {total}")

    results = {"pass": 0, "warn": 0, "fail": 0}

    # --------------------------------------------------------
    # 1. Проверка единого конфига окна анализа
    # --------------------------------------------------------
    print_header("1. ЕДИНЫЙ КОНФИГ ОКНА АНАЛИЗА")
    config_path = spectro_dir / "window_config.json"

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        mismatches = []
        for key, expected in EXPECTED_CONFIG.items():
            actual = config.get(key)
            if actual != expected:
                mismatches.append((key, expected, actual))
            print(f"  {key:15s}: {actual} (ожидается {expected})")

        if mismatches:
            print(f"[FAIL] Конфиг не совпадает с единым конфигом!")
            results["fail"] += 1
        else:
            print(f"[OK] Конфиг совпадает с единым конфигом окна анализа")
            results["pass"] += 1
    else:
        print(f"[FAIL] window_config.json не найден в {spectro_dir}")
        print(f"       Сгенерируйте спектрограммы через generate_spectrograms.py")
        results["fail"] += 1

    # --------------------------------------------------------
    # 2. Баланс классов NN1
    # --------------------------------------------------------
    print_header("2. БАЛАНС КЛАССОВ NN1")
    if "label" in df.columns:
        labeled = df[df["label"].notna() & (df["label"] != "")]
        counts = Counter(labeled["label"])
        bird_count = counts.get("bird", 0)
        no_bird_count = counts.get("no_bird", 0)
        unsure_count = counts.get("unsure", 0)

        print(f"  bird:    {bird_count}")
        print(f"  no_bird: {no_bird_count}")
        print(f"  unsure:  {unsure_count}")
        print(f"  размечено: {len(labeled)} / {total}")

        if bird_count > 0 and no_bird_count > 0:
            ratio = no_bird_count / bird_count
            print(f"  Баланс (no_bird/bird): {ratio:.2f}")
            if BALANCE_MIN <= ratio <= BALANCE_MAX:
                print(f"[OK] Баланс в пределах {BALANCE_MIN}:{BALANCE_MAX}")
                results["pass"] += 1
            else:
                print(f"[WARN] Баланс вне диапазона {BALANCE_MIN}:{BALANCE_MAX}")
                results["warn"] += 1
        else:
            print(f"[WARN] Недостаточно размеченных данных для оценки баланса")
            results["warn"] += 1
    else:
        print(f"[FAIL] Колонка 'label' не найдена в манифесте")
        results["fail"] += 1

    # --------------------------------------------------------
    # 3. Распределение типов позитивов
    # --------------------------------------------------------
    print_header("3. РАСПРЕДЕЛЕНИЕ ТИПОВ ПОЗИТИВОВ")
    if "fragment_type" in df.columns and "label" in df.columns:
        positives = df[(df["label"] == "bird") & df["fragment_type"].notna()]
        type_counts = Counter(positives["fragment_type"])
        total_pos = len(positives)

        if total_pos > 0:
            for ftype, target in TARGET_DISTRIBUTION.items():
                cnt = type_counts.get(ftype, 0)
                pct = cnt / total_pos
                status = "OK" if abs(pct - target) <= 0.10 else "WARN"
                print(f"  {ftype:10s}: {cnt:5d} ({pct*100:5.1f}%) | цель {target*100:.0f}% | [{status}]")

            print(f"  Всего позитивов: {total_pos}")
        else:
            print(f"[WARN] Нет размеченных позитивов с указанием типа")
            results["warn"] += 1
    else:
        print(f"[WARN] Колонка 'fragment_type' не найдена или нет позитивов")
        results["warn"] += 1

    # --------------------------------------------------------
    # 4. Сплиты
    # --------------------------------------------------------
    print_header("4. СПЛИТЫ (TRAIN / VAL / TEST)")
    if "split" in df.columns:
        split_counts = Counter(df["split"].fillna("unassigned"))
        for split_name in ["train", "val", "test", "unassigned"]:
            cnt = split_counts.get(split_name, 0)
            pct = cnt / total * 100 if total > 0 else 0
            print(f"  {split_name:10s}: {cnt:6d} ({pct:5.1f}%)")

        # Проверка: test set = только полевые данные
        test_df = df[df["split"] == "test"]
        if len(test_df) > 0 and "source_file" in df.columns:
            field_in_test = test_df["source_file"].str.contains("field", na=False).sum()
            non_field_in_test = len(test_df) - field_in_test
            print(f"\n  Test set: полевых {field_in_test}, неполевых {non_field_in_test}")
            if non_field_in_test == 0:
                print(f"[OK] Test set содержит только полевые данные")
                results["pass"] += 1
            else:
                print(f"[WARN] В test set есть {non_field_in_test} неполевых фрагментов")
                results["warn"] += 1
    else:
        print(f"[WARN] Колонка 'split' не найдена — запустите split_dataset.py")
        results["warn"] += 1

    # --------------------------------------------------------
    # 5. Спектрограммы
    # --------------------------------------------------------
    print_header("5. СПЕКТРОГРАММЫ")
    spec_files = list(spectro_dir.glob("*.npy"))
    print(f"  Файлов .npy: {len(spec_files)}")
    print(f"  Фрагментов в манифесте: {total}")

    if len(spec_files) == total:
        print(f"[OK] Количество спектрограмм совпадает с манифестом")
        results["pass"] += 1
    elif len(spec_files) > 0:
        print(f"[WARN] Количество спектрограмм не совпадает с манифестом")
        results["warn"] += 1
    else:
        print(f"[FAIL] Спектрограммы не найдены")
        results["fail"] += 1

    # Проверка размера спектрограмм
    if spec_files:
        sample = np.load(spec_files[0])
        n_mels = EXPECTED_CONFIG["n_mels"]
        expected_frames = int(EXPECTED_CONFIG["window_sec"] * EXPECTED_CONFIG["sr"]
                              / EXPECTED_CONFIG["hop_spectro"]) + 1
        print(f"\n  Ожидаемый размер: ({n_mels}, ~{expected_frames})")
        print(f"  Фактический размер: {sample.shape}")

        if sample.shape[0] == n_mels and abs(sample.shape[1] - expected_frames) <= 2:
            print(f"[OK] Размер спектрограмм соответствует единому конфигу")
            results["pass"] += 1
        else:
            print(f"[FAIL] Размер спектрограмм не соответствует конфигу!")
            results["fail"] += 1

    # --------------------------------------------------------
    # 6. Критерии готовности датасета (раздел 13)
    # --------------------------------------------------------
    print_header("6. КРИТЕРИИ ГОТОВНОСТИ ДАТАСЕТА (раздел 13)")

    criteria = []

    # Баланс NN1
    if "label" in df.columns:
        labeled = df[df["label"].notna() & (df["label"] != "")]
        counts = Counter(labeled["label"])
        bird = counts.get("bird", 0)
        no_bird = counts.get("no_bird", 0)
        if bird > 0 and no_bird > 0:
            ratio = no_bird / bird
            criteria.append(("Баланс NN1 в пределах 0.8:1–1.2:1",
                             BALANCE_MIN <= ratio <= BALANCE_MAX))

    # Длина окна
    if "duration_sec" in df.columns:
        all_2_5 = (df["duration_sec"] == EXPECTED_CONFIG["window_sec"]).all()
        criteria.append(("Все фрагменты равны длине окна анализа (2.5 с)", bool(all_2_5)))

    # Версионирование
    criteria.append(("Датасет версионирован (DVC)", False))  # Ручная проверка
    criteria.append(("Лицензии проверены", False))  # Ручная проверка

    for desc, passed in criteria:
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} {desc}")
        if passed:
            results["pass"] += 1
        else:
            results["fail"] += 1

    # --------------------------------------------------------
    # Итог
    # --------------------------------------------------------
    print_header("ИТОГ ВАЛИДАЦИИ")
    print(f"  Пройдено:  {results['pass']}")
    print(f"  Предупреждений: {results['warn']}")
    print(f"  Ошибок:    {results['fail']}")

    if results["fail"] == 0:
        print(f"\n  [OK] Датасет готов к обучению")
    else:
        print(f"\n  [FAIL] Исправьте ошибки перед обучением")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Валидация датасета по критериям DATASET_STRATEGY v2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Пример запуска:
  python validate_dataset.py --manifest "D:\\bird_audio\\manifest_fragments.csv" --spectro "D:\\bird_audio\\spectrograms"

Или с путями по умолчанию (если файлы в текущей директории):
  python validate_dataset.py
        """
    )
    parser.add_argument(
        "--manifest",
        default="manifest_fragments.csv",
        help="Путь к CSV манифесту (по умолчанию: manifest_fragments.csv)"
    )
    parser.add_argument(
        "--spectro",
        default="spectrograms",
        help="Папка со спектрограммами .npy (по умолчанию: spectrograms)"
    )
    args = parser.parse_args()

    validate(args.manifest, args.spectro)