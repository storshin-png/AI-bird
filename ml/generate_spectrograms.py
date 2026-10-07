"""
Генерация спектрограмм по config/window_config.yaml.
Вход: папка с фрагментами wav
Выход: папка с .npy спектрограммами + снимок конфига окна
"""

import json
import argparse
import librosa
import numpy as np
import pandas as pd
from pathlib import Path
from tqdm import tqdm

from audio_channels import arrange_channels
from window_config import load_window_config

# Число mel-полос не входит в контракт окна анализа.
MEL_BANDS = 128


def wav_to_log_mel(wav_path: str, cfg: dict, mix_channels: bool) -> np.ndarray:
    """wav → спектрограмма. FFT, hop, окно и представление читаются из конфига."""
    if cfg["representation"] != "log_mel":
        raise ValueError(
            f"представление {cfg['representation']!r} этим скриптом не строится"
        )

    y, _sr = librosa.load(wav_path, sr=cfg["sample_rate"], mono=False)
    audio = arrange_channels(y, mix_channels)

    expected_samples = int(cfg["window_length_sec"] * cfg["sample_rate"])
    n_samples = audio.shape[0]
    if n_samples != expected_samples:
        raise ValueError(
            f"Длина {wav_path}: {n_samples} != {expected_samples}. "
            f"Фрагмент должен быть ровно {cfg['window_length_sec']} с."
        )

    if audio.ndim == 1:
        channel_list = [audio]
    else:
        channel_list = [audio[:, index] for index in range(audio.shape[1])]

    specs = [_log_mel_channel(channel, cfg) for channel in channel_list]
    if len(specs) == 1:
        return specs[0]
    return np.stack(specs, axis=0)


def _log_mel_channel(y: np.ndarray, cfg: dict) -> np.ndarray:
    mel = librosa.feature.melspectrogram(
        y=y,
        sr=cfg["sample_rate"],
        n_fft=cfg["n_fft"],
        hop_length=cfg["hop_length"],
        window=cfg["window_function"],
        fmax=cfg["freq_max"],
        n_mels=MEL_BANDS,
    )
    log_mel = librosa.power_to_db(mel, ref=np.max)
    return log_mel.astype(np.float32)


def main():
    parser = argparse.ArgumentParser(
        description="Спектрограммы по config/window_config.yaml"
    )
    parser.add_argument("--input", required=True, help="Папка с фрагментами wav")
    parser.add_argument("--output", required=True, help="Папка для спектрограмм .npy")
    parser.add_argument("--manifest", required=True, help="CSV манифест фрагментов")
    parser.add_argument(
        "--window-config",
        default=None,
        help="Путь к window_config.yaml (по умолчанию config/window_config.yaml репозитория)",
    )
    parser.add_argument(
        "--mix-channels",
        action="store_true",
        help="Свести каналы в моно перед спектрограммой. Без флага 4 канала остаются раздельными.",
    )
    args = parser.parse_args()

    cfg = load_window_config(Path(args.window_config) if args.window_config else None)
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.manifest)
    print(f"Фрагментов: {len(df)}")
    print("\nКонфиг окна анализа:")
    for key, value in cfg.items():
        print(f"  {key}: {value}")

    success = 0
    errors = []

    for _, row in tqdm(df.iterrows(), total=len(df), desc="Спектрограммы"):
        frag_name = row["fragment_id"]
        wav_path = input_dir / frag_name

        if not wav_path.exists():
            errors.append(f"Не найден: {frag_name}")
            continue

        try:
            log_mel = wav_to_log_mel(str(wav_path), cfg, args.mix_channels)
            npy_name = frag_name.replace(".wav", ".npy")
            np.save(output_dir / npy_name, log_mel)
            success += 1
        except Exception as e:
            errors.append(f"{frag_name}: {e}")

    print(f"\nУспешно: {success}")
    if errors:
        print(f"Ошибки: {len(errors)}")
        for item in errors[:10]:
            print(f"  {item}")

    config_path = output_dir / "window_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"Конфиг сохранён: {config_path}")


if __name__ == "__main__":
    main()
