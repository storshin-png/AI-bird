"""Прогон нарезки и log-mel на записанном WAV. Плату не требует."""

import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

HOST = Path(__file__).resolve().parent
DSP = HOST.parent / "components" / "dsp"


def compile_host(exe: Path) -> None:
    compilers = [shutil.which(name) for name in ("gcc", "clang", "cc", "tcc")]
    tcc_root = Path(tempfile.gettempdir()) / "tcc"
    compilers.extend(str(path) for path in tcc_root.glob("**/tcc.exe"))
    compiler = next((item for item in compilers if item), None)
    if compiler is None:
        raise RuntimeError("нет gcc, clang или tcc")

    command = [
        compiler,
        "-std=c11",
        "-O2",
        "-o",
        str(exe),
        str(HOST / "spectrogram_host.c"),
        str(DSP / "log_mel.c"),
        str(DSP / "slice.c"),
        str(DSP / "store.c"),
        f"-I{DSP}",
    ]
    if Path(compiler).stem != "tcc":
        command.append("-lm")
    subprocess.run(command, check=True)


def write_tone(path: Path) -> np.ndarray:
    rate = 44100
    count = 6 * rate
    t = np.arange(count) / rate
    tone = 0.3 * np.sin(2 * np.pi * 1000 * t) + 0.15 * np.sin(2 * np.pi * 3500 * t)
    pcm = np.clip(np.round(tone * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return pcm


def read_lmel(path: Path) -> tuple[dict, np.ndarray]:
    blob = path.read_bytes()
    header = struct.unpack_from("<4sHHIIIIHHHHf", blob, 0)
    meta = {
        "magic": header[0],
        "version": header[1],
        "channels": header[2],
        "sample_rate": header[3],
        "window_samples": header[4],
        "hop_samples": header[5],
        "start_sample": header[6],
        "n_fft": header[7],
        "hop_length": header[8],
        "n_mels": header[9],
        "n_frames": header[10],
    }
    spec = np.frombuffer(blob, dtype="<f4", offset=36).reshape(meta["n_mels"], meta["n_frames"])
    return meta, spec


def main() -> int:
    import librosa

    check = subprocess.run([sys.executable, str(HOST / "check_contract.py")], check=False)
    if check.returncode != 0:
        return check.returncode

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        wav_path = tmp_path / "tone.wav"
        pcm = write_tone(wav_path)
        exe = tmp_path / "spectrogram_host.exe"
        compile_host(exe)
        subprocess.run([str(exe), str(wav_path), str(tmp_path / "out")], check=True)
        session = tmp_path / "out" / "0001"
        wavs = sorted(session.glob("w*.wav"))
        specs = sorted(session.glob("w*.lmel"))
        window = 110250
        hop = 44100
        expected = []
        start = 0
        while start + window <= len(pcm):
            expected.append(start)
            start += hop
        if len(wavs) != len(expected) or len(specs) != len(expected):
            print(f"окон {len(wavs)}, ожидалось {len(expected)}")
            return 1

        for path, start in zip(wavs, expected):
            with wave.open(str(path), "rb") as handle:
                got = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
            if handle_rate_mismatch(path):
                return 1
            if not np.array_equal(got, pcm[start : start + window]):
                print(f"нарезка не совпала: {path.name} start={start}")
                return 1

        worst = 0.0
        for path, start in zip(specs, expected):
            meta, got = read_lmel(path)
            if meta["magic"] != b"LMEL" or meta["n_mels"] != 128 or meta["n_frames"] != 216:
                print(f"заголовок {path.name}: {meta}")
                return 1
            if meta["start_sample"] != start or meta["hop_samples"] != hop:
                print(f"шаг окна {path.name}: {meta}")
                return 1
            audio = pcm[start : start + window].astype(np.float32) / np.float32(32768.0)
            mel = librosa.feature.melspectrogram(
                y=audio,
                sr=44100,
                n_fft=1024,
                hop_length=512,
                window="hann",
                fmax=22050,
                n_mels=128,
            )
            reference = librosa.power_to_db(mel, ref=np.max).astype(np.float32)
            delta = float(np.max(np.abs(got - reference)))
            worst = max(worst, delta)
        print(f"окон: {len(expected)}, максимальное расхождение log-mel: {worst:.4f} дБ")
        if worst > 0.25:
            print("спектрограмма разошлась с librosa")
            return 1
    return 0


def handle_rate_mismatch(path: Path) -> bool:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getframerate() != 44100 or handle.getsampwidth() != 2:
            print(f"формат wav {path.name} не 16 бит моно 44100")
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())
