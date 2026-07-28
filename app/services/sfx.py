from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from app.config import SFX_DIR, ensure_dirs

# Built-in SFX catalog (generated as WAV on first run)
SFX_CATALOG = [
    {"id": "whoosh", "label": "Whoosh", "color": "#e8a35a", "duration": 0.45, "cat": "chuyển cảnh"},
    {"id": "swoosh", "label": "Swoosh", "color": "#c9a0ff", "duration": 0.5, "cat": "chuyển cảnh"},
    {"id": "transition", "label": "Transition", "color": "#ff8f6b", "duration": 0.4, "cat": "chuyển cảnh"},
    {"id": "riser", "label": "Riser", "color": "#6ad0e0", "duration": 0.8, "cat": "kịch tính"},
    {"id": "impact", "label": "Impact", "color": "#e07a6a", "duration": 0.35, "cat": "kịch tính"},
    {"id": "boom", "label": "Boom", "color": "#c44", "duration": 0.55, "cat": "kịch tính"},
    {"id": "suspense", "label": "Suspense", "color": "#6a5acd", "duration": 1.2, "cat": "kịch tính"},
    {"id": "pop", "label": "Pop", "color": "#7dcea0", "duration": 0.18, "cat": "nhấn mạnh"},
    {"id": "click", "label": "Click", "color": "#8ab4f8", "duration": 0.08, "cat": "nhấn mạnh"},
    {"id": "ding", "label": "Ding", "color": "#f0c35a", "duration": 0.55, "cat": "nhấn mạnh"},
    {"id": "boing", "label": "Boing", "color": "#ff9f43", "duration": 0.4, "cat": "hài"},
    {"id": "laugh", "label": "Cười", "color": "#f368e0", "duration": 0.7, "cat": "hài"},
    {"id": "giggle", "label": "Khúc khích", "color": "#ee5a24", "duration": 0.55, "cat": "hài"},
    {"id": "honk", "label": "Honk", "color": "#10ac84", "duration": 0.35, "cat": "hài"},
    {"id": "drum", "label": "Trống", "color": "#576574", "duration": 0.45, "cat": "nhấn mạnh"},
    {"id": "sparkle", "label": "Lấp lánh", "color": "#54a0ff", "duration": 0.6, "cat": "nhấn mạnh"},
]


def _write_wav(path: Path, samples: np.ndarray, rate: int = 44100) -> None:
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767.0).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())


def _env(n: int, attack: float = 0.01, release: float = 0.08, rate: int = 44100) -> np.ndarray:
    a = max(1, int(attack * rate))
    r = max(1, int(release * rate))
    env = np.ones(n, dtype=np.float64)
    env[:a] = np.linspace(0, 1, a)
    if r < n:
        env[-r:] = np.linspace(1, 0, r)
    return env


def _gen_whoosh(rate: int = 44100, dur: float = 0.45) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    noise = np.random.default_rng(1).normal(0, 1, n)
    noise = np.diff(noise, prepend=noise[0])
    sweep = np.sin(2 * np.pi * (400 + 2200 * t / dur) * t) * 0.15
    return (noise * 0.22 + sweep) * _env(n, 0.02, 0.12, rate) * (0.3 + 0.7 * t / dur)


def _gen_pop(rate: int = 44100, dur: float = 0.18) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    freq = 520 * np.exp(-18 * t)
    return np.sin(2 * np.pi * freq * t) * _env(n, 0.002, 0.12, rate) * 0.9


def _gen_click(rate: int = 44100, dur: float = 0.08) -> np.ndarray:
    n = int(rate * dur)
    noise = np.random.default_rng(2).normal(0, 1, n)
    return noise * _env(n, 0.001, 0.05, rate) * 0.55


def _gen_ding(rate: int = 44100, dur: float = 0.55) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    sig = (
        0.6 * np.sin(2 * np.pi * 880 * t)
        + 0.3 * np.sin(2 * np.pi * 1320 * t)
        + 0.15 * np.sin(2 * np.pi * 1760 * t)
    )
    return sig * np.exp(-3.2 * t) * 0.85


def _gen_impact(rate: int = 44100, dur: float = 0.35) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    thump = np.sin(2 * np.pi * (90 * np.exp(-8 * t)) * t)
    noise = np.random.default_rng(3).normal(0, 1, n) * np.exp(-14 * t) * 0.35
    return (thump * 0.9 + noise) * _env(n, 0.001, 0.2, rate)


def _gen_swoosh(rate: int = 44100, dur: float = 0.5) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    noise = np.random.default_rng(4).normal(0, 1, n)
    noise = np.convolve(noise, np.ones(24) / 24, mode="same")
    pan = np.sin(np.pi * t / dur)
    return noise * pan * _env(n, 0.03, 0.15, rate) * 0.45


def _gen_riser(rate: int = 44100, dur: float = 0.8) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    freq = 120 + 900 * (t / dur) ** 2
    phase = 2 * np.pi * np.cumsum(freq) / rate
    noise = np.random.default_rng(5).normal(0, 1, n) * 0.12 * (t / dur)
    return (np.sin(phase) * 0.55 + noise) * (t / dur) * _env(n, 0.05, 0.05, rate)


def _gen_transition(rate: int = 44100, dur: float = 0.4) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    a = np.sin(2 * np.pi * (300 + 900 * t / dur) * t) * (1 - t / dur)
    b = np.sin(2 * np.pi * (1200 - 700 * t / dur) * t) * (t / dur)
    return (a + b) * _env(n, 0.01, 0.08, rate) * 0.55


def _gen_boom(rate: int = 44100, dur: float = 0.55) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    body = np.sin(2 * np.pi * (55 * np.exp(-6 * t)) * t)
    crack = np.random.default_rng(7).normal(0, 1, n) * np.exp(-20 * t)
    return (body * 0.95 + crack * 0.4) * _env(n, 0.001, 0.25, rate)


def _gen_suspense(rate: int = 44100, dur: float = 1.2) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    tone = 0.35 * np.sin(2 * np.pi * (180 + 40 * t) * t)
    pulse = 0.2 * np.sin(2 * np.pi * 2.5 * t)
    noise = np.random.default_rng(8).normal(0, 1, n) * 0.05 * (t / dur)
    return (tone * (0.6 + pulse) + noise) * _env(n, 0.08, 0.15, rate)


def _gen_boing(rate: int = 44100, dur: float = 0.4) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    freq = 700 * np.exp(-4 * t) + 120
    return np.sin(2 * np.pi * np.cumsum(freq) / rate) * np.exp(-3 * t) * 0.85


def _gen_laugh(rate: int = 44100, dur: float = 0.7) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    # rhythmic ha-ha-ha bursts
    bursts = np.zeros(n)
    rng = np.random.default_rng(9)
    for i, start in enumerate([0.02, 0.18, 0.34, 0.5]):
        f0 = 280 + i * 30
        for j in range(n):
            tt = t[j] - start
            if 0 <= tt < 0.12:
                bursts[j] += np.sin(2 * np.pi * f0 * tt) * np.sin(np.pi * tt / 0.12) * 0.55
                bursts[j] += rng.normal(0, 0.04)
    return bursts * _env(n, 0.01, 0.1, rate)


def _gen_giggle(rate: int = 44100, dur: float = 0.55) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    sig = np.zeros(n)
    for i, start in enumerate([0.02, 0.12, 0.22, 0.32, 0.42]):
        f0 = 420 + i * 25
        for j in range(n):
            tt = t[j] - start
            if 0 <= tt < 0.08:
                sig[j] += np.sin(2 * np.pi * f0 * tt) * np.sin(np.pi * tt / 0.08) * 0.45
    return sig * _env(n, 0.005, 0.08, rate)


def _gen_honk(rate: int = 44100, dur: float = 0.35) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    return (
        0.55 * np.sin(2 * np.pi * 220 * t)
        + 0.25 * np.sin(2 * np.pi * 440 * t)
    ) * _env(n, 0.01, 0.12, rate)


def _gen_drum(rate: int = 44100, dur: float = 0.45) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    kick = np.sin(2 * np.pi * (80 * np.exp(-10 * t)) * t) * np.exp(-6 * t)
    snare = np.random.default_rng(11).normal(0, 1, n) * np.exp(-25 * np.maximum(0, t - 0.12))
    snare *= (t > 0.12).astype(float)
    return (kick * 0.9 + snare * 0.35) * _env(n, 0.001, 0.15, rate)


def _gen_sparkle(rate: int = 44100, dur: float = 0.6) -> np.ndarray:
    n = int(rate * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    sig = np.zeros(n)
    for k, f in enumerate([1200, 1600, 2100, 2800]):
        sig += 0.22 * np.sin(2 * np.pi * f * t) * np.exp(-(3 + k) * t)
    return sig * _env(n, 0.005, 0.1, rate)


_GENERATORS = {
    "whoosh": _gen_whoosh,
    "pop": _gen_pop,
    "click": _gen_click,
    "ding": _gen_ding,
    "impact": _gen_impact,
    "swoosh": _gen_swoosh,
    "riser": _gen_riser,
    "transition": _gen_transition,
    "boom": _gen_boom,
    "suspense": _gen_suspense,
    "boing": _gen_boing,
    "laugh": _gen_laugh,
    "giggle": _gen_giggle,
    "honk": _gen_honk,
    "drum": _gen_drum,
    "sparkle": _gen_sparkle,
}


def ensure_sfx_library() -> list[dict]:
    ensure_dirs()
    items = []
    for meta in SFX_CATALOG:
        path = SFX_DIR / f"{meta['id']}.wav"
        if not path.exists():
            gen = _GENERATORS[meta["id"]]
            _write_wav(path, gen(dur=meta["duration"]))
        items.append({**meta, "path": path.name, "url": f"/sfx/{meta['id']}"})
    return items


def list_sfx() -> list[dict]:
    return ensure_sfx_library()


def sfx_path(sfx_id: str) -> Path:
    ensure_sfx_library()
    safe = Path(sfx_id).name
    path = SFX_DIR / f"{safe}.wav"
    if not path.exists():
        raise FileNotFoundError(safe)
    return path


def estimate_script_duration(script: str) -> float:
    text = (script or "").strip()
    if not text:
        return 12.0
    return max(4.0, len(text) / 12.5)
