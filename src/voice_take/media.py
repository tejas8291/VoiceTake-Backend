"""Encode downloads and adjust rendered speech with the local FFmpeg binary."""
import os
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

TEMPO = {"slow": 0.88, "normal": 1.0, "fast": 1.12}


def prepare_pcm(pcm: bytes, source_rate: int, target_rate: int, speed: str) -> bytes:
    if source_rate == target_rate and speed == "normal":
        return pcm
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error",
        "-f", "s16le", "-ar", str(source_rate), "-ac", "1", "-i", "pipe:0",
        *(["-af", f"atempo={TEMPO[speed]}"] if speed != "normal" else []),
        "-ar", str(target_rate), "-f", "s16le", "pipe:1",
    ]
    result = subprocess.run(command, input=pcm, capture_output=True, check=True, timeout=30)
    if not result.stdout or len(result.stdout) % 2:
        raise ValueError("Could not adjust the audio for this line.")
    return result.stdout


def encode_mp3(wav: Path) -> Path:
    target = wav.with_suffix(".mp3")
    if target.is_file():
        return target
    with tempfile.NamedTemporaryFile(dir=wav.parent, suffix=".mp3", delete=False) as temp:
        intermediate = Path(temp.name)
    try:
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(wav),
            "-codec:a", "libmp3lame", "-b:a", "96k", str(intermediate),
        ], check=True, capture_output=True, timeout=30)
        os.replace(intermediate, target)
    finally:
        intermediate.unlink(missing_ok=True)
    return target


def finish_dialogue(pcm: bytes, sample_rate: int, gain_db: float, *, trim_edges: bool, fade_edges: bool = False) -> bytes:
    """Match speech RMS, then cap the applied gain so samples retain headroom."""
    from array import array
    from math import sqrt
    from sys import byteorder

    frames = array("h", pcm)
    if byteorder != "little":
        frames.byteswap()
    if not frames:
        return pcm
    width = max(1, sample_rate // 100)
    spans = []
    for start in range(0, len(frames), width):
        block = frames[start:start + width]
        energy = sum(value * value for value in block)
        if energy >= len(block) * 104**2:
            spans.append((start, len(block), energy))
    if not spans:
        return pcm
    rms = sqrt(sum(span[2] for span in spans) / sum(span[1] for span in spans))
    if trim_edges:
        first, last = spans[0], spans[-1]
        margin = 3 * width
        frames = frames[max(0, first[0] - margin):last[0] + last[1] + margin]
    peak = max(abs(sample) for sample in frames)
    target_rms = 32767 * 10 ** (-20 / 20)
    gain = min(4.0, target_rms / rms) * 10 ** (gain_db / 20)
    gain = min(gain, (32767 * 10 ** (-2 / 20)) / peak)
    adjusted = array("h", (round(sample * gain) for sample in frames))
    if fade_edges:
        ramp = min(sample_rate // 250, len(adjusted) // 2)  # 4 ms, no added latency
        for index in range(ramp):
            factor = index / ramp
            adjusted[index] = round(adjusted[index] * factor)
            adjusted[-1 - index] = round(adjusted[-1 - index] * factor)
    if byteorder != "little":
        adjusted.byteswap()
    return adjusted.tobytes()
