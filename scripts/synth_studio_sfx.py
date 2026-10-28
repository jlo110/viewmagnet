"""Procedurally synthesize transition SFX wav files (Week 6).

Run this once to (re)generate the SFX stinger files referenced by
``src/features/studio/transition_catalog.py`` and mirrored to the
frontend's public assets folder so the preview's ``useTransitionSfx``
hook can play them in the browser.

    python scripts/synth_studio_sfx.py

Each stinger is short (200-400ms), normalized to a peak around -3dBFS so
mixing with the source audio (via ``amix=normalize=0``) doesn't clip the
master. We use stereo 44.1kHz 16-bit PCM (.wav) because:
  - ffmpeg's ``adelay|`` syntax handles mono → stereo padding automatically
  - the browser <audio> element decodes wav without codec quirks
  - file size is fine for 200-400ms clips (~80-160KB each)

The design philosophy: each stinger has a distinct character that pairs
with its visual transition. Fade gets a soft swell; swipe a quick rising
sweep; zoom an upward pitch glide; glitch a quantized burst; flash a
crispy click; vhs a buzzy detuned tone; whoosh a filtered noise sweep.
"""
from __future__ import annotations

import math
import os
import struct
import wave
from typing import Callable, List, Tuple

SAMPLE_RATE = 44_100
CHANNELS = 2
BITS_PER_SAMPLE = 16

# ---------------------------------------------------------------------------
# Tiny DSP helpers — kept dependency-free so this script runs anywhere.
# ---------------------------------------------------------------------------


def _adsr(t: float, a: float, d: float, s_level: float, s_dur: float, r: float) -> float:
    """Attack-Decay-Sustain-Release envelope, returns 0..1 at time ``t`` (s)."""
    if t < 0:
        return 0.0
    if t < a:
        return t / a
    if t < a + d:
        return 1.0 - (1.0 - s_level) * ((t - a) / d)
    if t < a + d + s_dur:
        return s_level
    rel_t = t - (a + d + s_dur)
    if rel_t < r:
        return s_level * (1.0 - rel_t / r)
    return 0.0


def _smoothstep(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return 3 * p * p - 2 * p * p * p


def _white_noise(seed: int = 1234):
    state = seed & 0xFFFFFFFF
    while True:
        state = (1103515245 * state + 12345) & 0xFFFFFFFF
        yield (state >> 16) / 32768.0 - 1.0


def _one_pole_lowpass(samples: List[float], cutoff_hz: float) -> List[float]:
    rc = 1.0 / (2 * math.pi * cutoff_hz)
    dt = 1.0 / SAMPLE_RATE
    alpha = dt / (rc + dt)
    out: List[float] = []
    y = 0.0
    for x in samples:
        y = y + alpha * (x - y)
        out.append(y)
    return out


def _normalize(samples: List[float], peak: float = 0.85) -> List[float]:
    if not samples:
        return samples
    m = max(abs(min(samples)), abs(max(samples)))
    if m < 1e-6:
        return samples
    g = peak / m
    return [s * g for s in samples]


def _write_wav(path: str, mono_samples: List[float]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(BITS_PER_SAMPLE // 8)
        w.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for s in mono_samples:
            v = max(-1.0, min(1.0, s))
            i16 = int(v * 32767)
            frames += struct.pack("<hh", i16, i16)  # duplicate to stereo
        w.writeframes(bytes(frames))


def _render(duration_s: float, fn: Callable[[float], float]) -> List[float]:
    n = int(duration_s * SAMPLE_RATE)
    return [fn(i / SAMPLE_RATE) for i in range(n)]


# ---------------------------------------------------------------------------
# Per-stinger generators
# ---------------------------------------------------------------------------


def fade_wav() -> List[float]:
    """Soft 80Hz→200Hz swell, 400ms. Gentle bookend."""
    def f(t: float) -> float:
        env = _adsr(t, 0.05, 0.10, 0.5, 0.10, 0.15)
        freq = 80 + 120 * _smoothstep(t / 0.4)
        return env * 0.6 * math.sin(2 * math.pi * freq * t)
    return _normalize(_render(0.4, f))


def dissolve_wav() -> List[float]:
    """Two soft sine bells overlapping. 500ms. Reads as a longer fade."""
    def f(t: float) -> float:
        env1 = _adsr(t, 0.04, 0.10, 0.5, 0.10, 0.20)
        env2 = _adsr(max(0.0, t - 0.18), 0.04, 0.10, 0.4, 0.10, 0.20)
        s1 = math.sin(2 * math.pi * 220 * t)
        s2 = math.sin(2 * math.pi * 330 * t)
        return 0.6 * (env1 * s1 + env2 * s2)
    return _normalize(_render(0.5, f))


def swipe_wav() -> List[float]:
    """Quick rising sweep 300Hz→1200Hz, 250ms. Whip-pan feel."""
    def f(t: float) -> float:
        env = _adsr(t, 0.01, 0.04, 0.7, 0.08, 0.10)
        # Linear pitch sweep with extra harmonic for "whip" timbre
        freq = 300 + 900 * (t / 0.25)
        fundamental = math.sin(2 * math.pi * freq * t)
        harmonic = 0.3 * math.sin(2 * math.pi * 2 * freq * t)
        return env * 0.7 * (fundamental + harmonic)
    return _normalize(_render(0.25, f))


def zoom_wav() -> List[float]:
    """Upward pitch glide 200Hz→800Hz with vibrato, 350ms. 'Punch in' cue."""
    def f(t: float) -> float:
        env = _adsr(t, 0.02, 0.08, 0.7, 0.10, 0.15)
        # Exponential sweep — feels more "rushy" than linear for a punch-in
        freq = 200 * math.pow(4.0, t / 0.35)
        vibrato = 1.0 + 0.02 * math.sin(2 * math.pi * 12 * t)
        return env * 0.65 * math.sin(2 * math.pi * freq * vibrato * t)
    return _normalize(_render(0.35, f))


def glitch_wav() -> List[float]:
    """Bit-crushed burst — square wave + bitcrush + brief noise tail, 200ms."""
    rng = _white_noise(seed=7)
    out: List[float] = []
    n = int(0.20 * SAMPLE_RATE)
    for i in range(n):
        t = i / SAMPLE_RATE
        env = _adsr(t, 0.005, 0.04, 0.5, 0.06, 0.08)
        # Square at 660Hz (perfect fifth above 440 — distinctly "alarm-y")
        sq = 1.0 if math.sin(2 * math.pi * 660 * t) >= 0 else -1.0
        # 8-step quantize for that bit-crushed character
        sq_q = round(sq * 4) / 4
        noise = next(rng) * 0.3 * env
        out.append(env * 0.6 * sq_q + noise)
    return _normalize(out)


def vhs_wav() -> List[float]:
    """Detuned dual-saw buzz, 300ms. Retro tape head 'click-buzz'."""
    def saw(freq: float, t: float) -> float:
        return 2.0 * (t * freq - math.floor(0.5 + t * freq))

    def f(t: float) -> float:
        env = _adsr(t, 0.005, 0.06, 0.4, 0.10, 0.13)
        s1 = saw(180, t)
        s2 = saw(184, t)  # 4Hz beat → tape wobble feel
        return env * 0.45 * (s1 + s2)
    raw = _render(0.30, f)
    return _normalize(_one_pole_lowpass(raw, cutoff_hz=2500))


def flash_wav() -> List[float]:
    """Short bright click — filtered noise burst, 150ms. Camera-flash bulb."""
    rng = _white_noise(seed=42)
    out: List[float] = []
    n = int(0.15 * SAMPLE_RATE)
    for i in range(n):
        t = i / SAMPLE_RATE
        env = _adsr(t, 0.001, 0.02, 0.3, 0.04, 0.08)
        out.append(env * next(rng) * 0.9)
    # Hi-pass-ish — apply a bandpass by subtracting a low-passed copy
    lp = _one_pole_lowpass(out, cutoff_hz=1500)
    hp = [a - b for a, b in zip(out, lp)]
    return _normalize(hp)


def whoosh_wav() -> List[float]:
    """Filtered-noise sweep, 350ms. Pre-existing flavor — kept consistent."""
    rng = _white_noise(seed=99)
    raw = [next(rng) for _ in range(int(0.35 * SAMPLE_RATE))]
    # Envelope rises then falls — broad whoosh shape.
    out: List[float] = []
    for i, s in enumerate(raw):
        t = i / SAMPLE_RATE
        env = _adsr(t, 0.08, 0.10, 0.6, 0.10, 0.15)
        # Sweep cutoff via simple modulation: noise becomes lower-pitched
        # over time, simulating a swept band-pass.
        out.append(s * env)
    # Apply a moving low-pass that opens up then closes.
    smoothed: List[float] = []
    cutoff = 3000.0
    y = 0.0
    for i, x in enumerate(out):
        t = i / SAMPLE_RATE
        # Cutoff arcs: low at start, peaks mid, low at end.
        progress = t / 0.35
        cutoff = 800 + 2200 * math.sin(math.pi * progress)
        rc = 1.0 / (2 * math.pi * max(150.0, cutoff))
        dt = 1.0 / SAMPLE_RATE
        alpha = dt / (rc + dt)
        y = y + alpha * (x - y)
        smoothed.append(y)
    return _normalize(smoothed)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

GENERATORS = {
    "fade.wav": fade_wav,
    "dissolve.wav": dissolve_wav,
    "swipe.wav": swipe_wav,
    "zoom.wav": zoom_wav,
    "glitch.wav": glitch_wav,
    "vhs.wav": vhs_wav,
    "flash.wav": flash_wav,
    "whoosh.wav": whoosh_wav,
}

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(REPO_ROOT, "src", "assets", "sfx")
FRONTEND_DIR = os.path.join(REPO_ROOT, "frontend", "client", "public", "sfx")


def main() -> None:
    for filename, gen in GENERATORS.items():
        samples = gen()
        for target_dir in (BACKEND_DIR, FRONTEND_DIR):
            out = os.path.join(target_dir, filename)
            _write_wav(out, samples)
            size = os.path.getsize(out)
            print(f"wrote {out:80s} ({size // 1024} KB, {len(samples)} samples)")


if __name__ == "__main__":
    main()
