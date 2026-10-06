"""
Генерация log-mel спектрограмм по единому конфигу.
Вход: папка с фрагментами wav 2.5 с
Выход: папка с .npy спектрограммами + обновлённый манифест
"""

import os
import json
import argparse
import librosa
import numpy as np
import pandas as pd
from pathlib import Path
from tqdm import tqdm

# ============================================================
# ЕДИНЫЙ КОНФИГ (идентичен cut_fragments.py)
# ============================================================
CONFIG = {
    "window_sec": 2.5,
    "sr": 44100,
    "n_fft": 1024,
    "hop_spectro": 512,
    "window_fn": "hann",
    "fmax": 22050,
    "repr": "log_mel",
    "n_mels": 128,  # Количество mel-фильтров
}


def wav_to_log_mel(wav_path: str) -> np.ndarray:
    """
    Преобразование wav → log-mel спектрограмма.
    Параметры строго из единого конфига.
    """
    y, sr = librosa.load(wav_path, sr=CONFIG["sr"], mono=True)

    # Проверка длины
    expected_samples = int(CONFIG["window_sec"] * CONFIG["sr"])
    if len(y) != expected_samples:
        raise ValueError(
            f"Длина {wav_path}: {len(y)} != {expected_samples}. "
            f"Фрагмент должен быть ровно {CONFIG['window_sec']} с."
        )

    # Mel-спектрограмма
    mel = librosa.feature.melspectrogram(
        y=y,
        sr=sr,
        n_fft=CONFIG["n_fft"],
        hop_length=CONFIG["hop_spectro"],
        window=CONFIG["window_fn"],
        fmax=CONFIG["fmax"],
        n_mels=CONFIG["n_mels"],
    )

    # Log-mel
    log_mel = librosa.power_to_db(mel, ref=np.max)

    return log_mel.astype(np.float32)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Папка с фрагментами wav")
    parser.add_argument("--output", required=True, help="Папка для спектрограмм .npy")
    parser.add_argument("--manifest", required=True, help="CSV манифест фрагментов")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.manifest)
    print(f"Фрагментов: {len(df)}")

    # Проверка единого конфига
    print(f"\nКонфиг окна анализа:")
    for k, v in CONFIG.items():
        print(f"  {k}: {v}")

    success = 0
    errors = []

    for _, row in tqdm(df.iterrows(), total=len(df), desc="Спектрограммы"):
        frag_name = row["fragment_id"]
        wav_path = input_dir / frag_name

        if not wav_path.exists():
            errors.append(f"Не найден: {frag_name}")
            continue

        try:
            log_mel = wav_to_log_mel(str(wav_path))
            npy_name = frag_name.replace(".wav", ".npy")
            np.save(output_dir / npy_name, log_mel)
            success += 1
        except Exception as e:
            errors.append(f"{frag_name}: {e}")

    print(f"\nУспешно: {success}")
    if errors:
        print(f"Ошибки: {len(errors)}")
        for e in errors[:10]:
            print(f"  {e}")

    # Сохранение конфига рядом со спектрограммами
    config_path = output_dir / "window_config.json"
    with open(config_path, "w") as f:
        json.dump(CONFIG, f, indent=2)
    print(f"Конфиг сохранён: {config_path}")


if __name__ == "__main__":
    main()