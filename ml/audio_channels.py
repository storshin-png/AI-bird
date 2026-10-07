"""Каналы при нарезке и спектрограмме.

Открытый архив (не 4 канала) можно свести в моно.
Файл с 4 каналами по умолчанию не смешивается: каналы сохраняются.
Смешение четырёх каналов — только при явном флаге.
"""

import numpy as np


def arrange_channels(audio: np.ndarray, mix_channels: bool) -> np.ndarray:
    """librosa отдаёт (samples,) или (channels, samples).

    Возврат: (samples,) для моно либо (samples, 4), если каналы сохранены.
    """
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 1:
        return audio
    if audio.shape[0] == 1:
        return np.ascontiguousarray(audio[0])
    if audio.shape[0] != 4 or mix_channels:
        return np.mean(audio, axis=0).astype(np.float32)
    return np.ascontiguousarray(audio.T)
