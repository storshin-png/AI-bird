"""Проверка config/window_config.yaml на рамку MVP.

Цифры совпадают с ARCHITECTURE.md §2, MVP_SPEC.md §2.1 и AI_AGENTS_SPEC.md §7.1.
Скрипт без сторонних библиотек: так его запускает GitHub Actions.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "window_config.yaml"

EXPECTED = {
    "window_length_sec": "2.5",
    "sample_rate": "44100",
    "n_fft": "1024",
    "hop_length": "512",
    "window_function": "hann",
    "freq_max": "22050",
    "representation": "log_mel",
    "hop_inference_base_sec": "1.0",
    "hop_inference_adaptive_sec": "2.0",
    "hop_inference_high_sensitivity_sec": "0.5",
    "pre_roll_sec": "2.0",
    "event_wav_sec": "10",
}


def load_flat_yaml(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    if not CONFIG_PATH.is_file():
        print(f"нет файла {CONFIG_PATH}")
        return 1
    found = load_flat_yaml(CONFIG_PATH)
    errors = []
    for key, expected in EXPECTED.items():
        actual = found.get(key)
        if actual is None:
            errors.append(f"нет ключа {key}")
        elif actual != expected:
            errors.append(f"{key}: ожидается {expected}, в файле {actual}")
    if errors:
        print("window_config.yaml расходится с рамкой MVP:")
        for item in errors:
            print(f"- {item}")
        return 1
    print("window_config.yaml совпадает с рамкой MVP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
