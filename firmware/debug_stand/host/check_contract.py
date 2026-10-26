"""Сверяет цифры прошивки с config/window_config.yaml и MEL_BANDS."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HEADER = ROOT / "firmware" / "debug_stand" / "components" / "dsp" / "window_contract.h"
YAML = ROOT / "config" / "window_config.yaml"
MEL_SOURCE = ROOT / "ml" / "generate_spectrograms.py"


def parse_yaml(path: Path) -> dict:
    parsed: dict = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        if "." in value:
            parsed[key.strip()] = float(value)
        else:
            try:
                parsed[key.strip()] = int(value)
            except ValueError:
                parsed[key.strip()] = value
    return parsed


def parse_defines(text: str) -> dict:
    found: dict = {}
    for match in re.finditer(r"^#define\s+(\w+)\s+(\S+)", text, re.M):
        name, value = match.group(1), match.group(2)
        if value.startswith('"') and value.endswith('"'):
            found[name] = value[1:-1]
        elif re.fullmatch(r"-?\d+", value):
            found[name] = int(value)
    return found


def samples(seconds, rate: int) -> int:
    return int(seconds * rate)


def main() -> int:
    cfg = parse_yaml(YAML)
    defines = parse_defines(HEADER.read_text(encoding="utf-8"))
    rate = cfg["sample_rate"]
    expected = {
        "SAMPLE_RATE": rate,
        "N_FFT": cfg["n_fft"],
        "HOP_LENGTH": cfg["hop_length"],
        "FREQ_MAX": cfg["freq_max"],
        "WINDOW_SAMPLES": samples(cfg["window_length_sec"], rate),
        "HOP_INFERENCE_BASE_SAMPLES": samples(cfg["hop_inference_base_sec"], rate),
        "HOP_INFERENCE_ADAPTIVE_SAMPLES": samples(cfg["hop_inference_adaptive_sec"], rate),
        "HOP_INFERENCE_HIGH_SAMPLES": samples(cfg["hop_inference_high_sensitivity_sec"], rate),
        "WINDOW_FUNCTION_NAME": cfg["window_function"],
        "REPRESENTATION_NAME": cfg["representation"],
    }
    mel_match = re.search(r"^MEL_BANDS\s*=\s*(\d+)", MEL_SOURCE.read_text(encoding="utf-8"), re.M)
    if not mel_match:
        print("в generate_spectrograms.py нет MEL_BANDS")
        return 1
    expected["N_MELS"] = int(mel_match.group(1))

    failed = False
    for name, value in expected.items():
        got = defines.get(name)
        if got != value:
            print(f"{name}: прошивка {got!r}, контракт {value!r}")
            failed = True
    if defines.get("DEBUG_CHANNELS") != 1:
        print("DEBUG_CHANNELS должен быть 1: промежуточный стенд с одним микрофоном")
        failed = True
    if failed:
        return 1
    print("цифры окна совпали: 2.5 с, 44.1 кГц, FFT 1024, hop 512, Hann, log-mel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
