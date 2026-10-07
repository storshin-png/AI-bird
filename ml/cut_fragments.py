"""
Нарезка аудио на фрагменты по config/window_config.yaml.
Вход: папка с mp3/wav
Выход: папка с фрагментами wav + CSV-манифест
"""

import json
import argparse
import librosa
import soundfile as sf
import numpy as np
import pandas as pd
from pathlib import Path
from tqdm import tqdm

from audio_channels import arrange_channels
from window_config import load_window_config


def load_audio(path: str, sample_rate: int, mix_channels: bool) -> np.ndarray:
    audio, _sr = librosa.load(path, sr=sample_rate, mono=False)
    return arrange_channels(audio, mix_channels)


def cut_into_fragments(
    audio: np.ndarray,
    source_name: str,
    output_dir: Path,
    cfg: dict,
    cut_hop_sec: float,
):
    """Нарезка скользящим окном. Длина фрагмента берётся из конфига."""
    sample_rate = cfg["sample_rate"]
    window_sec = cfg["window_length_sec"]
    window_samples = int(window_sec * sample_rate)
    hop_samples = int(cut_hop_sec * sample_rate)
    records = []

    start = 0
    idx = 0
    while start + window_samples <= len(audio):
        fragment = audio[start : start + window_samples]

        rms = np.sqrt(np.mean(np.asarray(fragment, dtype=np.float64) ** 2))
        if rms < 1e-4:
            start += hop_samples
            continue

        pos_ms = int(start / sample_rate * 1000)
        frag_name = f"{source_name}_{idx:04d}_{pos_ms}ms.wav"
        frag_path = output_dir / frag_name

        sf.write(frag_path, fragment, sample_rate)

        records.append({
            "fragment_id": frag_name,
            "source_file": source_name,
            "start_ms": pos_ms,
            "duration_sec": window_sec,
            "rms": round(float(rms), 6),
            "label": "",
            "fragment_type": "",
            "split": "",
            "window_config": json.dumps(cfg, ensure_ascii=False),
        })

        start += hop_samples
        idx += 1

    return records


def main():
    parser = argparse.ArgumentParser(
        description="Нарезка аудио на фрагменты по config/window_config.yaml"
    )
    parser.add_argument("--input", required=True, help="Папка с исходными mp3/wav")
    parser.add_argument("--output", required=True, help="Папка для фрагментов")
    parser.add_argument(
        "--window-config",
        default=None,
        help="Путь к window_config.yaml (по умолчанию config/window_config.yaml репозитория)",
    )
    parser.add_argument(
        "--cut-hop-sec",
        type=float,
        default=2.0,
        help="Шаг скользящей нарезки, секунды. Не длиннее окна анализа.",
    )
    parser.add_argument(
        "--mix-channels",
        action="store_true",
        help="Свести каналы в моно. Без флага файл с 4 каналами сохраняет каналы.",
    )
    args = parser.parse_args()

    cfg = load_window_config(Path(args.window_config) if args.window_config else None)
    if args.cut_hop_sec <= 0 or args.cut_hop_sec > cfg["window_length_sec"]:
        parser.error("шаг нарезки должен быть > 0 и не длиннее окна анализа")

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_files = sorted(
        [f for f in input_dir.rglob("*") if f.suffix.lower() in (".mp3", ".wav")]
    )
    print(f"Найдено файлов: {len(audio_files)}")
    print(f"Окно: {cfg['window_length_sec']} с, {cfg['sample_rate']} Гц")

    all_records = []
    for f in tqdm(audio_files, desc="Нарезка"):
        audio = load_audio(str(f), cfg["sample_rate"], args.mix_channels)
        records = cut_into_fragments(audio, f.stem, output_dir, cfg, args.cut_hop_sec)
        all_records.extend(records)

    df = pd.DataFrame(all_records)
    manifest_path = output_dir.parent / "manifest_fragments.csv"
    df.to_csv(manifest_path, index=False)
    print(f"\nВсего фрагментов: {len(df)}")
    print(f"Манифест: {manifest_path}")


if __name__ == "__main__":
    main()
