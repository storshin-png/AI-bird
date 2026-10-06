"""
Нарезка аудио на фрагменты 2.5 с по единому конфигу проекта.
Вход: папка с mp3/wav
Выход: папка с фрагментами wav 2.5 с + CSV-манифест
"""

import os
import json
import argparse
import librosa
import soundfile as sf
import numpy as np
import pandas as pd
from pathlib import Path
from tqdm import tqdm

# ============================================================
# ЕДИНЫЙ КОНФИГ ОКНА АНАЛИЗА (из DATASET_STRATEGY / ARCHITECTURE)
# ============================================================
CONFIG = {
    "window_sec": 2.5,          # Длина окна анализа
    "sr": 44100,                # Частота дискретизации
    "n_fft": 1024,              # FFT-окно (~23 мс)
    "hop_spectro": 512,         # Hop спектрограммы (~11.6 мс)
    "window_fn": "hann",        # Оконная функция
    "fmax": 22050,              # Частотный диапазон
    "repr": "log_mel",          # Представление
    "hop_inference_base": 1.0,  # Базовый hop инференса
}

# Шаг нарезки обучающих фрагментов (≤ длины окна для скользящей нарезки)
CUT_HOP_SEC = 2.0  # Перекрытие 0.5 с


def load_audio(path: str) -> np.ndarray:
    """Загрузка аудио (mp3 или wav) с ресемплингом до 44.1 кГц."""
    audio, sr = librosa.load(path, sr=CONFIG["sr"], mono=True)
    return audio


def cut_into_fragments(audio: np.ndarray, source_name: str, output_dir: Path):
    """Нарезка на фрагменты 2.5 с со скользящим шагом."""
    window_samples = int(CONFIG["window_sec"] * CONFIG["sr"])
    hop_samples = int(CUT_HOP_SEC * CONFIG["sr"])
    records = []

    start = 0
    idx = 0
    while start + window_samples <= len(audio):
        fragment = audio[start : start + window_samples]

        # Пропускаем тишину (RMS ниже порога)
        rms = np.sqrt(np.mean(fragment ** 2))
        if rms < 1e-4:
            start += hop_samples
            continue

        # Имя файла: исходник_номер_позиция_мс
        pos_ms = int(start / CONFIG["sr"] * 1000)
        frag_name = f"{source_name}_{idx:04d}_{pos_ms}ms.wav"
        frag_path = output_dir / frag_name

        sf.write(frag_path, fragment, CONFIG["sr"])

        records.append({
            "fragment_id": frag_name,
            "source_file": source_name,
            "start_ms": pos_ms,
            "duration_sec": CONFIG["window_sec"],
            "rms": round(float(rms), 6),
            "label": "",           # Заполняется при разметке
            "fragment_type": "",   # dense / sparse / truncated
            "split": "",           # train / val / test
            "window_config": json.dumps(CONFIG),
        })

        start += hop_samples
        idx += 1

    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Папка с исходными mp3/wav")
    parser.add_argument("--output", required=True, help="Папка для фрагментов")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_files = sorted(
        [f for f in input_dir.rglob("*") if f.suffix.lower() in (".mp3", ".wav")]
    )
    print(f"Найдено файлов: {len(audio_files)}")

    all_records = []
    for f in tqdm(audio_files, desc="Нарезка"):
        audio = load_audio(str(f))
        source_name = f.stem
        records = cut_into_fragments(audio, source_name, output_dir)
        all_records.extend(records)

    # Сохранение манифеста
    df = pd.DataFrame(all_records)
    manifest_path = output_dir.parent / "manifest_fragments.csv"
    df.to_csv(manifest_path, index=False)
    print(f"\nВсего фрагментов: {len(df)}")
    print(f"Манифест: {manifest_path}")


if __name__ == "__main__":
    main()