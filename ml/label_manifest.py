# label_manifest.py
import json
import pandas as pd
import urllib.parse
from pathlib import Path

# Пути
JSON_PATH = "D:/bird_audio/label_studio_export.json"
MANIFEST_PATH = "D:/bird_audio/manifest_fragments.csv"

print("Загрузка манифеста...")
df = pd.read_csv(MANIFEST_PATH)

# ⚠️ КРИТИЧНО: приводим колонки к строковому типу ДО записи
df["label"] = df["label"].fillna("").astype(str)
df["fragment_type"] = df["fragment_type"].fillna("").astype(str)

print("Загрузка экспорта Label Studio...")
with open(JSON_PATH, "r", encoding="utf-8") as f:
    ls_data = json.load(f)

updates = {}
parsed_count = 0

for item in ls_data:
    # 1. Извлекаем имя файла из URL
    audio_url = item.get("data", {}).get("audio", "")
    if not audio_url:
        continue
    
    decoded_url = urllib.parse.unquote(audio_url)
    if "?d=" in decoded_url:
        file_path = decoded_url.split("?d=")[1]
    else:
        file_path = decoded_url
    
    fragment_id = Path(file_path).name
    
    # 2. Извлекаем аннотации (финальная разметка, не drafts)
    annotations = item.get("annotations", [])
    if not annotations:
        continue
    
    result = annotations[0].get("result", [])
    
    label = ""
    fragment_type = ""
    
    for r in result:
        from_name = r.get("from_name")
        choices = r.get("value", {}).get("choices", [])
        if choices:
            choice_val = choices[0]
            if from_name == "bird_label":
                label = choice_val
            elif from_name == "fragment_type":
                fragment_type = choice_val
    
    updates[fragment_id] = {"label": label, "fragment_type": fragment_type}
    parsed_count += 1

# 3. Обновляем DataFrame через .loc (надёжнее, чем .at)
updated_count = 0
for frag_id, values in updates.items():
    mask = df["fragment_id"] == frag_id
    if mask.any():
        df.loc[mask, "label"] = values["label"]
        if values["fragment_type"]:
            df.loc[mask, "fragment_type"] = values["fragment_type"]
        updated_count += 1

# 4. Сохраняем
df.to_csv(MANIFEST_PATH, index=False)

# 5. Статистика
print("\n" + "="*50)
print("СТАТИСТИКА ОБНОВЛЕНИЯ")
print("="*50)
print(f"Всего задач в JSON: {len(ls_data)}")
print(f"Успешно распарсено: {parsed_count}")
print(f"Обновлено строк в манифесте: {updated_count}")

labeled_df = df[df["label"].isin(["bird", "no_bird", "unsure"])]
print(f"\nВсего размечено фрагментов: {len(labeled_df)}")
print(f"  bird:    {(labeled_df['label'] == 'bird').sum()}")
print(f"  no_bird: {(labeled_df['label'] == 'no_bird').sum()}")
print(f"  unsure:  {(labeled_df['label'] == 'unsure').sum()}")

bird_df = labeled_df[labeled_df["label"] == "bird"]
print(f"\nРаспределение типов позитивов (bird):")
print(f"  dense:      {(bird_df['fragment_type'] == 'dense').sum()}")
print(f"  sparse:     {(bird_df['fragment_type'] == 'sparse').sum()}")
print(f"  truncated:  {(bird_df['fragment_type'] == 'truncated').sum()}")
print(f"  не указан:  {(bird_df['fragment_type'] == '').sum()}")
print("="*50)
print(f"✅ Манифест обновлён: {MANIFEST_PATH}")