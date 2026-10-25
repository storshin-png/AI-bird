"""Сектора, азимуты и что слышит каждый из четырёх микрофонов.

Каналы WAV идут в порядке N, E, S, W (ARCHITECTURE.md §2). Микрофон
смотрит по своей оси корпуса: N — 0°, E — 90°, S — 180°, W — 270°
относительно корпуса. Корпус повёрнут на orientation_deg от севера.
"""

import math

CHANNELS = ("N", "E", "S", "W")
CHANNEL_AXIS_DEG = {"N": 0.0, "E": 90.0, "S": 180.0, "W": 270.0}
SPEED_OF_SOUND = 343.0

# Таблица из hardware/STAND.md: N — [337.5, 360) и [0, 22.5), далее по 45°.
_SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def norm(deg: float) -> float:
    value = deg % 360.0
    return 0.0 if value >= 360.0 else value


def sector(azimuth_deg: float) -> str:
    return _SECTORS[int(((norm(azimuth_deg) + 22.5) % 360.0) // 45.0)]


def device_azimuth(geo_deg: float, orientation_deg: float) -> float:
    """Азимут относительно корпуса из азимута относительно севера."""
    return norm(geo_deg - orientation_deg)


def channel_response(azimuth_device_deg: float, radius_m: float, sample_rate: int) -> dict[str, tuple[float, int]]:
    """Усиление и задержка в отсчётах для каждого канала.

    Модель простая: ближе к оси микрофона — громче (кардиоида), и звук
    приходит раньше на микрофон, обращённый к источнику. Задержки
    считаются от самого раннего канала, поэтому все >= 0.
    """
    raw = {}
    for ch in CHANNELS:
        delta = math.radians(azimuth_device_deg - CHANNEL_AXIS_DEG[ch])
        gain = 0.55 + 0.45 * math.cos(delta)
        delay_s = -radius_m * math.cos(delta) / SPEED_OF_SOUND
        raw[ch] = (gain, delay_s)
    earliest = min(d for _, d in raw.values())
    return {ch: (g, round((d - earliest) * sample_rate)) for ch, (g, d) in raw.items()}


def bearing_quality(confidence: float) -> str:
    if confidence >= 0.7:
        return "good"
    if confidence >= 0.5:
        return "medium"
    if confidence >= 0.3:
        return "poor"
    return "ambiguous"
