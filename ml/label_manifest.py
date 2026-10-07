"""Перенос разметки Label Studio в манифест фрагментов."""

import argparse
import json
import urllib.parse
from pathlib import Path

import pandas as pd


def apply_labels(export_path: Path, manifest_path: Path, output_path: Path) -> None:
    print("Загрузка манифеста...")
    df = pd.read_csv(manifest_path)

    df["label"] = df["label"].fillna("").astype(str)
    df["fragment_type"] = df["fragment_type"].fillna("").astype(str)

    print("Загрузка экспорта Label Studio...")
    with open(export_path, "r", encoding="utf-8") as f:
        ls_data = json.load(f)

    updates = {}
    parsed_count = 0

    for item in ls_data:
        audio_url = item.get("data", {}).get("audio", "")
        if not audio_url:
            continue

        decoded_url = urllib.parse.unquote(audio_url)
        if "?d=" in decoded_url:
            file_path = decoded_url.split("?d=")[1]
        else:
            file_path = decoded_url

        fragment_id = Path(file_path).name

        annotations = item.get("annotations", [])
        if not annotations:
            continue

        result = annotations[0].get("result", [])

        label = ""
        fragment_type = ""

        for row in result:
            from_name = row.get("from_name")
            choices = row.get("value", {}).get("choices", [])
            if choices:
                choice_val = choices[0]
                if from_name == "bird_label":
                    label = choice_val
                elif from_name == "fragment_type":
                    fragment_type = choice_val

        updates[fragment_id] = {"label": label, "fragment_type": fragment_type}
        parsed_count += 1

    updated_count = 0
    for frag_id, values in updates.items():
        mask = df["fragment_id"] == frag_id
        if mask.any():
            df.loc[mask, "label"] = values["label"]
            if values["fragment_type"]:
                df.loc[mask, "fragment_type"] = values["fragment_type"]
            updated_count += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    print("\n" + "=" * 50)
    print("СТАТИСТИКА ОБНОВЛЕНИЯ")
    print("=" * 50)
    print(f"Всего задач в JSON: {len(ls_data)}")
    print(f"Успешно распарсено: {parsed_count}")
    print(f"Обновлено строк в манифесте: {updated_count}")

    labeled_df = df[df["label"].isin(["bird", "no_bird", "unsure"])]
    print(f"\nВсего размечено фрагментов: {len(labeled_df)}")
    print(f"  bird:    {(labeled_df['label'] == 'bird').sum()}")
    print(f"  no_bird: {(labeled_df['label'] == 'no_bird').sum()}")
    print(f"  unsure:  {(labeled_df['label'] == 'unsure').sum()}")

    bird_df = labeled_df[labeled_df["label"] == "bird"]
    print("\nРаспределение типов позитивов (bird):")
    print(f"  dense:      {(bird_df['fragment_type'] == 'dense').sum()}")
    print(f"  sparse:     {(bird_df['fragment_type'] == 'sparse').sum()}")
    print(f"  truncated:  {(bird_df['fragment_type'] == 'truncated').sum()}")
    print(f"  не указан:  {(bird_df['fragment_type'] == '').sum()}")
    print("=" * 50)
    print(f"Манифест записан: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Перенос разметки Label Studio в CSV-манифест"
    )
    parser.add_argument("--export", required=True, help="JSON экспорта Label Studio")
    parser.add_argument("--manifest", required=True, help="Входной CSV манифест фрагментов")
    parser.add_argument("--output", required=True, help="Куда записать обновлённый манифест")
    args = parser.parse_args()
    apply_labels(Path(args.export), Path(args.manifest), Path(args.output))


if __name__ == "__main__":
    main()
