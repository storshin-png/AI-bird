"""Синтетический 4-канальный WAV события: фон + птичья трель после pre-roll.

Без сторонних библиотек: wave и array из стандартной библиотеки.
Формат — как у датчика по MVP_SPEC.md §2.1: 16 бит, 4 канала, частота
и длина из config/window_config.yaml.
"""

import math
import random
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from .geometry import CHANNELS, channel_response

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "window_config.yaml"


@dataclass(frozen=True)
class WavFormat:
    sample_rate: int
    seconds: float
    pre_roll_sec: float

    @property
    def frames(self) -> int:
        return int(round(self.sample_rate * self.seconds))


def load_format(path: Path = CONFIG_PATH) -> WavFormat:
    """Читает sample_rate, event_wav_sec и pre_roll_sec из window_config.yaml."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    try:
        return WavFormat(
            sample_rate=int(values["sample_rate"]),
            seconds=float(values["event_wav_sec"]),
            pre_roll_sec=float(values["pre_roll_sec"]),
        )
    except KeyError as exc:
        raise ValueError(f"в {path} нет ключа {exc.args[0]}") from exc


def _call(fmt: WavFormat, rng: random.Random) -> list[float]:
    """Моно-сигнал птицы: 3–6 слогов с частотной модуляцией 2.5–7 кГц."""
    out = [0.0] * fmt.frames
    sr = fmt.sample_rate
    t = fmt.pre_roll_sec
    for _ in range(rng.randint(3, 6)):
        length = rng.uniform(0.08, 0.25)
        f0, f1 = rng.uniform(2500, 4500), rng.uniform(4500, 7000)
        if rng.random() < 0.5:
            f0, f1 = f1, f0
        start, n = int(t * sr), int(length * sr)
        phase = 0.0
        for i in range(n):
            if start + i >= fmt.frames:
                break
            x = i / n
            freq = f0 + (f1 - f0) * x
            phase += 2 * math.pi * freq / sr
            envelope = math.sin(math.pi * x) ** 2
            out[start + i] = envelope * math.sin(phase)
        t += length + rng.uniform(0.04, 0.15)
    return out


def synthesize(path: Path, azimuth_device_deg: float, fmt: WavFormat, seed: int,
               snr_db: float = 14.0, radius_m: float = 0.03) -> None:
    """Пишет WAV: канал, обращённый к источнику, громче и раньше остальных."""
    rng = random.Random(seed)
    call = _call(fmt, rng)
    response = channel_response(azimuth_device_deg, radius_m, fmt.sample_rate)
    signal_amp = 0.5
    noise_amp = signal_amp / (10 ** (snr_db / 20)) * 0.7
    frames = fmt.frames
    channels: list[list[float]] = []
    for ch in CHANNELS:
        gain, delay = response[ch]
        noise_state = 0.0
        data = [0.0] * frames
        for i in range(frames):
            # Фон: шум, сглаженный однополюсным фильтром (ветер, листва).
            noise_state = 0.97 * noise_state + 0.03 * rng.uniform(-1, 1) * 6
            j = i - delay
            s = call[j] if 0 <= j < frames else 0.0
            data[i] = signal_amp * gain * s + noise_amp * noise_state
        channels.append(data)
    pcm = array("h", bytes(2 * 4 * frames))
    k = 0
    for i in range(frames):
        for data in channels:
            v = data[i]
            pcm[k] = max(-32767, min(32767, int(v * 32767)))
            k += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(len(CHANNELS))
        w.setsampwidth(2)
        w.setframerate(fmt.sample_rate)
        w.writeframes(pcm.tobytes())
