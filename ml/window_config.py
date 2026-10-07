"""Чтение config/window_config.yaml.

Цифры окна в коде не хранятся: длина фрагмента, sample rate, FFT, hop,
оконная функция и представление берутся из файла.
"""

from pathlib import Path


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "window_config.yaml"


def _cast(value: str):
    try:
        number = float(value)
    except ValueError:
        return value
    if "." in value:
        return number
    return int(number)


def load_window_config(path: Path | None = None) -> dict:
    config_path = Path(path) if path else default_config_path()
    if not config_path.is_file():
        raise FileNotFoundError(f"нет файла {config_path}")

    parsed: dict = {}
    for raw in config_path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = _cast(value.strip().strip('"').strip("'"))

    required = (
        "window_length_sec",
        "sample_rate",
        "n_fft",
        "hop_length",
        "window_function",
        "freq_max",
        "representation",
    )
    missing = [key for key in required if key not in parsed]
    if missing:
        raise KeyError(f"в {config_path} нет ключей: {', '.join(missing)}")
    return parsed
