"""ffmpeg / ffprobe helpers (argument lists only — no shell), audio mixing and EBU R128 loudness normalisation."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

import numpy as np

SR = 48000
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


class MediaError(RuntimeError):
    pass


def run(args: list[str], timeout: float = 120.0, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        res = subprocess.run(args, input=input_bytes, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{Path(args[0]).name} timed out after {timeout}s") from exc
    if res.returncode != 0:
        raise MediaError(f"{Path(args[0]).name} failed ({res.returncode}): {res.stderr.decode(errors='replace')[-600:]}")
    return res


def probe(path: str | Path) -> dict[str, Any]:
    res = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=30)
    data = json.loads(res.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return {
        "duration": float(data["format"].get("duration", 0)),
        "size_bytes": int(data["format"].get("size", 0)),
        "format": data["format"].get("format_name"),
        "video": None if not video else {"codec": video["codec_name"], "width": video["width"], "height": video["height"], "fps": _fps(video.get("avg_frame_rate", "0/1")), "pix_fmt": video.get("pix_fmt"), "profile": video.get("profile")},
        "audio": None if not audio else {"codec": audio["codec_name"], "sample_rate": int(audio.get("sample_rate", 0)), "channels": audio.get("channels")},
    }


def _fps(r: str) -> float:
    n, _, d = r.partition("/")
    return round(float(n) / float(d or 1), 3) if float(d or 1) else 0.0


def decode_audio(data: bytes, suffix_hint: str = "") -> np.ndarray:
    """Any audio bytes -> float32 stereo array at 48 kHz (shape [n, 2])."""
    res = run([FFMPEG, "-v", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "2", "-ar", str(SR), "pipe:1"], timeout=60, input_bytes=data)
    arr = np.frombuffer(res.stdout, dtype=np.float32)
    return arr.reshape(-1, 2).copy()


def write_wav(path: str | Path, audio: np.ndarray, sr: int = SR) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def audio_duration(data: bytes) -> float:
    return len(decode_audio(data)) / SR


def _db(x: float) -> float:
    return 10 ** (x / 20.0)


def mix_timeline(
    vo: list[tuple[float, np.ndarray]],
    music: np.ndarray | None,
    total_s: float,
    music_gain_db: float = -19.0,
    duck_db: float = -11.0,
    fade_in: float = 0.5,
    fade_out: float = 1.4,
) -> tuple[np.ndarray, np.ndarray]:
    """Voice bus + ducked music bed -> (mix, duck_envelope). Music ducks under every VO segment (smooth ramps)."""
    n = round(total_s * SR)
    voice = np.zeros((n, 2), dtype=np.float32)
    env = np.ones(n, dtype=np.float32)
    for start, seg in vo:
        i0 = int(start * SR)
        i1 = min(n, i0 + len(seg))
        if i0 >= n:
            continue
        voice[i0:i1] += seg[: i1 - i0]
        a = max(0, i0 - int(0.18 * SR))
        b = min(n, i1 + int(0.35 * SR))
        env[a:b] = np.minimum(env[a:b], _db(duck_db))
    k = int(0.15 * SR)
    kernel = np.hanning(k * 2 + 1).astype(np.float32)
    kernel /= kernel.sum()
    env = np.convolve(np.pad(env, (k, k), mode="edge"), kernel, mode="valid")[:n]
    mix = voice.copy()
    if music is not None:
        m = np.zeros((n, 2), dtype=np.float32)
        take = min(n, len(music))
        m[:take] = music[:take]
        g = np.ones(n, dtype=np.float32)
        fi, fo = int(fade_in * SR), int(fade_out * SR)
        if fi:
            g[:fi] = np.linspace(0, 1, fi)
        if fo:
            g[-fo:] = np.minimum(g[-fo:], np.linspace(1, 0, fo))
        mix += m * (_db(music_gain_db) * env * g)[:, None]
    return mix, env


_JSON = re.compile(r"\{[^{}]*\}", re.DOTALL)


def loudnorm_two_pass(src_wav: Path, dst_wav: Path, target_lufs: float = -16.0, true_peak: float = -1.5, lra: float = 11.0) -> dict[str, float]:
    """EBU R128 two-pass normalisation (linear mode) — returns the measured input stats."""
    af1 = f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:print_format=json"
    res = run([FFMPEG, "-hide_banner", "-nostats", "-i", str(src_wav), "-af", af1, "-f", "null", "-"], timeout=120)
    m = _JSON.findall(res.stderr.decode(errors="replace"))
    if not m:
        raise MediaError("loudnorm measurement produced no JSON")
    st = json.loads(m[-1])
    af2 = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:measured_I={st['input_i']}:measured_TP={st['input_tp']}:"
        f"measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}:offset={st['target_offset']}:linear=true:print_format=summary"
    )
    run([FFMPEG, "-y", "-hide_banner", "-nostats", "-i", str(src_wav), "-af", af2, "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(dst_wav)], timeout=120)
    return {"input_i": float(st["input_i"]), "input_tp": float(st["input_tp"]), "input_lra": float(st["input_lra"])}


def measure_loudness(path: str | Path) -> dict[str, float]:
    """Independent EBU R128 measurement (ebur128 filter) of a file's audio: integrated LUFS, LRA, true peak."""
    res = run([FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], timeout=120)
    text = res.stderr.decode(errors="replace")
    summary = text[text.rfind("Summary:") :] if "Summary:" in text else text
    i = re.search(r"I:\s+(-?\d+\.\d+)\s+LUFS", summary)
    lra = re.search(r"LRA:\s+(-?\d+\.\d+)\s+LU", summary)
    peak = re.search(r"Peak:\s+(-?\d+\.\d+)\s+dBFS", summary)
    if not i:
        raise MediaError("could not parse ebur128 output")
    return {"integrated_lufs": float(i.group(1)), "lra": float(lra.group(1)) if lra else 0.0, "true_peak_dbfs": float(peak.group(1)) if peak else 0.0}


def extract_frame(video: str | Path, t: float) -> bytes:
    res = run([FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"], timeout=60)
    return res.stdout
