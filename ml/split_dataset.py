"""
Разделение датасета: 70% train / 15% val / 15% test.
ВАЖНО: test set должен содержать ТОЛЬКО полевые данные.

Логика:
1. Полевые данные (содержат подстроку --field-source) → ТОЛЬКО в test.
2. Неполевые данные → делятся на train и val.
3. Пропорция train/val рассчитывается так, чтобы итоговое
   соотношение было примерно 70/15/15 от общего объёма.
"""

import argparse
import pandas as pd
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Разделение датасета на train/val/test"
    )
    parser.add_argument("--manifest", required=True,
                        help="Путь к CSV манифесту фрагментов")
    parser.add_argument("--field-source", default="field_",
                        help="Подстрока в имени источника для полевых данных")
    args = parser.parse_args()

    df = pd.read_csv(args.manifest)
    total = len(df)
    print(f"Всего фрагментов: {total}")

    if args.field_source:
        # --- Разделяем полевые и неполевые ---
        field_mask = df["source_file"].str.contains(args.field_source, na=False)
        field_df = df[field_mask].copy()
        non_field_df = df[~field_mask].copy()

        print(f"\nПолевые фрагменты (→ test): {len(field_df)}")
        print(f"Неполевые фрагменты (→ train/val): {len(non_field_df)}")

        if len(non_field_df) == 0:
            print("[ОШИБКА] Нет неполевых данных для train/val!")
            return

        # --- Целевые доли от общего объёма ---
        # test = полевые (уже определены)
        # оставшиеся 85% (70% train + 15% val) — из неполевых
        test_ratio = len(field_df) / total if total > 0 else 0
        remaining_ratio = 1.0 - test_ratio  # доля неполевых в общем

        if remaining_ratio > 0:
            # Доля val от неполевых: 15% от общего / доля неполевых
            val_fraction = 0.15 / remaining_ratio
            # Ограничиваем, чтобы не превысить доступные данные
            val_fraction = min(val_fraction, 0.5)  # не более 50% неполевых
        else:
            val_fraction = 0.1765  # fallback

        print(f"\nЦелевое соотношение от общего: 70% train / 15% val / {test_ratio*100:.1f}% test")
        print(f"Доля val от неполевых: {val_fraction*100:.1f}%")

        # --- Разделение неполевых на train / val ---
        if val_fraction > 0 and len(non_field_df) > 1:
            val_size = max(1, int(len(non_field_df) * val_fraction))
            train_size = len(non_field_df) - val_size

            # Перемешиваем
            non_field_shuffled = non_field_df.sample(frac=1, random_state=42).reset_index(drop=True)

            val_df = non_field_shuffled.iloc[:val_size].copy()
            train_df = non_field_shuffled.iloc[val_size:].copy()
        else:
            train_df = non_field_df.copy()
            val_df = pd.DataFrame()

        # --- Присваиваем метки сплитов ---
        train_df["split"] = "train"
        val_df["split"] = "val"
        field_df["split"] = "test"

        # --- Объединяем ---
        result = pd.concat([train_df, val_df, field_df], ignore_index=True)

    else:
        # --- Без разделения на полевые/неполевые ---
        # Простое разделение 70/15/15
        df_shuffled = df.sample(frac=1, random_state=42).reset_index(drop=True)

        test_size = int(total * 0.15)
        val_size = int(total * 0.15)
        train_size = total - test_size - val_size

        train_df = df_shuffled.iloc[:train_size].copy()
        val_df = df_shuffled.iloc[train_size:train_size + val_size].copy()
        test_df = df_shuffled.iloc[train_size + val_size:].copy()

        train_df["split"] = "train"
        val_df["split"] = "val"
        test_df["split"] = "test"

        result = pd.concat([train_df, val_df, test_df], ignore_index=True)

    # --- Статистика ---
    print("\n" + "=" * 50)
    print("РЕЗУЛЬТАТ РАЗДЕЛЕНИЯ")
    print("=" * 50)
    split_counts = result["split"].value_counts()
    for split_name in ["train", "val", "test"]:
        cnt = split_counts.get(split_name, 0)
        pct = cnt / len(result) * 100 if len(result) > 0 else 0
        print(f"  {split_name:5s}: {cnt:6d} ({pct:5.1f}%)")
    print(f"  {'ВСЕГО':5s}: {len(result):6d}")

    # --- Проверка: в тесте только полевые ---
    if args.field_source:
        test_df_check = result[result["split"] == "test"]
        non_field_in_test = test_df_check[
            ~test_df_check["source_file"].str.contains(args.field_source, na=False)
        ]
        if len(non_field_in_test) > 0:
            print(f"\n[ВНИМАНИЕ] В test set есть {len(non_field_in_test)} неполевых фрагментов!")
        else:
            print(f"\n[OK] Test set содержит только полевые данные")

    # --- Сохранение ---
    result.to_csv(args.manifest, index=False)
    print(f"\nМанифест обновлён: {args.manifest}")


if __name__ == "__main__":
    main()