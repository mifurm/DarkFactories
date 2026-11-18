"""Procedural royalty-free music beds (numpy additive synthesis) — registered as 'licensed library tracks' (CC0, generated)."""

from __future__ import annotations

import numpy as np

SR = 48000
NOTES = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}
MAJOR_PROG = [(0, "maj7"), (9, "min7"), (5, "maj7"), (7, "add9")]  # I  vi  IV  V
MINOR_PROG = [(0, "min7"), (8, "maj7"), (3, "maj7"), (10, "add9")]  # i  VI  III VII
CHORDS = {"maj7": [0, 4, 7, 11], "min7": [0, 3, 7, 10], "add9": [0, 4, 7, 14]}
MOODS = {
    "calm": {"arp": False, "pulse": False, "minor": False, "pad_gain": 1.0, "arp_gain": 0.0},
    "warm": {"arp": True, "pulse": False, "minor": False, "pad_gain": 0.85, "arp_gain": 0.45},
    "uplifting": {"arp": True, "pulse": True, "minor": False, "pad_gain": 0.7, "arp_gain": 0.6},
    "reflective": {"arp": True, "pulse": False, "minor": True, "pad_gain": 0.9, "arp_gain": 0.4},
}


def midi_freq(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12.0)


def _tone(freq: float, n: int, harmonics: int = 5, decay: float = 0.0) -> np.ndarray:
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for k in range(1, harmonics + 1):
        if freq * k > SR / 2.2:
            break
        sig += np.sin(2 * np.pi * freq * k * t) / (k**1.25)
    if decay:
        sig *= np.exp(-t * decay)
    return sig


def generate_track(mood: str = "calm", bpm: int = 72, key: str = "D", seed: int = 11, duration: float = 16.0) -> np.ndarray:
    """Deterministic stereo bed (float32, shape [n, 2], peak ~0.6). Same params => identical audio."""
    cfg = MOODS.get(mood, MOODS["calm"])
    rng = np.random.default_rng(seed)
    n = int(duration * SR)
    out = np.zeros((n, 2))
    root = 48 + NOTES.get(key.upper(), 2)
    prog = MINOR_PROG if cfg["minor"] else MAJOR_PROG
    beat = 60.0 / bpm
    bar = beat * 4
    n_bars = int(np.ceil(duration / bar))
    for b in range(n_bars):
        deg, qual = prog[b % len(prog)]
        chord = [root + deg + iv for iv in CHORDS[qual]]
        s0 = int(b * bar * SR)
        n_len = int((bar + 0.9) * SR)  # let the pad ring into the next bar
        n_len = min(n_len, n - s0)
        if n_len <= 0:
            break
        env = np.minimum(1.0, np.arange(n_len) / (0.55 * SR)) * np.minimum(1.0, (n_len - np.arange(n_len)) / (0.9 * SR))
        for _i, m in enumerate(chord):
            for det, pan in ((-0.07, 0.3), (0.07, 0.7)):
                f = midi_freq(m + det + rng.uniform(-0.02, 0.02))
                sig = _tone(f, n_len, 4) * env * 0.11 * cfg["pad_gain"]
                out[s0 : s0 + n_len, 0] += sig * (1 - pan)
                out[s0 : s0 + n_len, 1] += sig * pan
        bass = _tone(midi_freq(root + deg - 12), min(int(bar * SR), n - s0), 2, decay=1.1) * 0.2
        out[s0 : s0 + len(bass), :] += bass[:, None]
        if cfg["arp"]:
            step = beat / 2
            pattern = [0, 2, 1, 3, 2, 1, 3, 2]
            for k in range(8):
                ps = s0 + int(k * step * SR)
                if ps >= n:
                    break
                note = chord[pattern[k] % len(chord)] + 12
                ln = min(int(0.8 * SR), n - ps)
                pl = _tone(midi_freq(note), ln, 3, decay=5.5) * 0.12 * cfg["arp_gain"]
                pan = 0.3 + 0.4 * (k % 2)
                out[ps : ps + ln, 0] += pl * (1 - pan)
                out[ps : ps + ln, 1] += pl * pan
        if cfg["pulse"]:
            for k in range(4):
                ps = s0 + int(k * beat * SR)
                if ps >= n:
                    break
                ln = min(int(0.25 * SR), n - ps)
                tt = np.arange(ln) / SR
                kick = np.sin(2 * np.pi * (55 + 40 * np.exp(-tt * 28)) * tt) * np.exp(-tt * 14) * 0.22
                out[ps : ps + ln, :] += kick[:, None]
    air = np.diff(rng.normal(0, 1, n + 1)) * 0.0025
    out += air[:, None]
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.6).astype(np.float32)
