"""Deterministic sound-design kit for the motion cut (no samples, no model calls).

Every sound is synthesized from NumPy/SciPy with fixed seeds, so the mix is reproducible
byte for byte. Each function returns a float32 stereo array (n, 2) at SR.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

SR = 48000


def pulse_bed(dur: float, period: float = 0.5) -> np.ndarray:
    """An original, deterministic demo score; no downloaded music or provider.

    Restrained minor arpeggio, four-on-the-floor kick and offbeat hats leave
    space for the kit's separate click, rise and impact sound design.
    """
    n = int(dur * SR)
    out = np.zeros((n, 2), dtype=np.float32)
    for i, at in enumerate(np.arange(0, dur, period / 2)):
        t = _t(min(period * 1.8, dur - at))
        note = (57, 60, 64, 67, 53, 57, 60, 64)[i % 8]
        hz = 440 * 2 ** ((note - 69) / 12)
        tone = (np.sin(2 * np.pi * hz * t) + 0.22 * np.sin(4 * np.pi * hz * t))
        tone *= np.minimum(t / 0.012, 1) * np.exp(-t / 0.15) * 0.08
        if i % 2 == 0:
            phase = 2 * np.pi * (44 * t + 8 * (1 - np.exp(-t / 0.028)))
            tone += np.sin(phase) * np.exp(-t / 0.07) * 0.18
        else:
            noise = _highpass(_rng(700 + i).standard_normal(len(t)), 8000)
            tone += noise * np.exp(-t / 0.017) * 0.018
        start = int(at * SR)
        sound = _stereo(tone, pan=(-0.25 if i % 2 else 0.25))
        count = min(len(sound), n - start)
        out[start:start + count] += sound[:count]
    fade = np.minimum(np.arange(n) / SR / 0.3, 1)
    fade *= np.clip((dur - np.arange(n) / SR) / 1.5, 0, 1)
    out *= fade[:, None]
    rms = float(np.sqrt(np.mean(np.square(out, dtype=np.float64))))
    if rms > 0:
        out *= 0.12 / rms
    return out


def _t(dur):
    return np.arange(int(dur * SR)) / SR


def _rng(seed):
    return np.random.default_rng(seed)


def _stereo(mono, pan=0.0):
    # Constant-power pan, -1 (left) .. 1 (right).
    a = (pan + 1) * np.pi / 4
    return np.stack([mono * np.cos(a), mono * np.sin(a)], axis=1).astype(np.float32)


def _bandpass(x, lo, hi, order=2):
    sos = signal.butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def _lowpass(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="low", fs=SR, output="sos"), x)


def _highpass(x, f, order=2):
    return signal.sosfilt(signal.butter(order, f, btype="high", fs=SR, output="sos"), x)


def _sweep_filter(noise, centers, q=1.4, block=256):
    """Band-pass noise whose centre frequency follows `centers` (one value per sample)."""
    out = np.zeros_like(noise)
    zi = None
    for start in range(0, len(noise), block):
        c = float(np.clip(centers[start], 60, SR * 0.45))
        bw = c / q
        lo, hi = max(30.0, c - bw / 2), min(SR * 0.49, c + bw / 2)
        sos = signal.butter(2, [lo, hi], btype="band", fs=SR, output="sos")
        if zi is None:
            zi = np.zeros((sos.shape[0], 2))
        out[start:start + block], zi = signal.sosfilt(sos, noise[start:start + block], zi=zi)
    return out


def _tail(x, seconds=1.2, seed=7, wet=0.25):
    """Cheap stereo reverb: convolve with two decorrelated exponential noise impulses."""
    rng = _rng(seed)
    n = int(seconds * SR)
    env = np.exp(-np.linspace(0, 7, n))
    irs = [_lowpass(rng.standard_normal(n) * env, 6000) for _ in range(2)]
    irs = [ir / np.sqrt(np.sum(ir ** 2)) for ir in irs]
    mono = x.mean(axis=1) if x.ndim == 2 else x
    size = len(mono) + n
    wet_l = np.pad(signal.fftconvolve(mono, irs[0]), (0, 1))[:size]
    wet_r = np.pad(signal.fftconvolve(mono, irs[1]), (0, 1))[:size]
    dry = np.zeros((size, 2))
    dry[: len(mono)] = x if x.ndim == 2 else np.stack([x, x], 1)
    dry[:, 0] += wet * wet_l
    dry[:, 1] += wet * wet_r
    return dry.astype(np.float32)


def _norm(x, peak=0.9):
    m = np.max(np.abs(x)) or 1.0
    return (x / m * peak).astype(np.float32)


def impact(size=1.0, seed=1):
    """Sub drop + transient snap + room. size 1 = the Save drop, 0.5 = a title slam."""
    dur = 0.35 + 0.9 * size
    t = _t(dur)
    f = 38 + (110 - 38) * np.exp(-t / (0.05 + 0.08 * size))
    phase = 2 * np.pi * np.cumsum(f) / SR
    sub = np.sin(phase) * np.exp(-t / (0.12 + 0.3 * size))
    rng = _rng(seed)
    snap = _bandpass(rng.standard_normal(len(t)), 900, 7000) * np.exp(-t / 0.018)
    body = _lowpass(rng.standard_normal(len(t)), 900) * np.exp(-t / (0.05 + 0.08 * size))
    click = np.zeros_like(t)
    click[: int(0.002 * SR)] = np.hanning(int(0.004 * SR))[: int(0.002 * SR)]
    mono = 1.0 * sub + 0.35 * snap + 0.5 * body + 0.3 * click
    out = _tail(_stereo(_norm(mono)), seconds=0.6 + 0.9 * size, seed=seed + 11, wet=0.18 + 0.12 * size)
    return _norm(out, 0.95)


def whoosh(dur=0.5, direction=1, seed=2, bright=1.0):
    """Air past the lens: swept band-passed noise with a moving stereo pan."""
    t = _t(dur)
    x = t / dur
    rng = _rng(seed)
    noise = rng.standard_normal(len(t))
    centers = 350 + (2600 * bright) * np.sin(np.pi * np.clip(x, 0, 1)) ** 1.6
    band = _sweep_filter(noise, centers, q=1.2)
    env = np.sin(np.pi * np.clip(x, 0, 1)) ** 1.8
    mono = _norm(band * env)
    pan = np.clip((x - 0.5) * 1.6 * direction, -1, 1)
    a = (pan + 1) * np.pi / 4
    st = np.stack([mono * np.cos(a), mono * np.sin(a)], axis=1)
    return _norm(st, 0.9)


def riser(dur=1.9, seed=3):
    """Tension into the drop: rising noise band + a tone climbing an octave, cut hard at the end."""
    t = _t(dur)
    x = t / dur
    rng = _rng(seed)
    centers = 220 * (6000 / 220) ** (x ** 1.4)
    band = _sweep_filter(rng.standard_normal(len(t)), centers, q=2.2)
    tone_f = 220 * 2 ** (x ** 1.8)
    tone = sum(np.sin(2 * np.pi * np.cumsum(tone_f * k) / SR) / k for k in (1, 2, 3))
    trem = 0.75 + 0.25 * np.sin(2 * np.pi * np.cumsum(4 + 20 * x ** 2) / SR)
    env = x ** 2.2
    mono = (0.8 * _norm(band) + 0.35 * _norm(tone) * trem) * env
    mono[-int(0.004 * SR):] *= np.linspace(1, 0, int(0.004 * SR))
    return _norm(_stereo(mono), 0.85)


def mouse_click(seed=4):
    t = _t(0.06)
    rng = _rng(seed)
    tick = _highpass(rng.standard_normal(len(t)), 2500) * np.exp(-t / 0.0025)
    thock = np.sin(2 * np.pi * 1900 * t) * np.exp(-t / 0.006)
    return _norm(_stereo(0.8 * tick + 0.4 * thock), 0.7)


def key(seed=5):
    """One keystroke; the seed varies pitch and level so a run of keys never machine-guns."""
    rng = _rng(seed)
    t = _t(0.07)
    f = 1100 + 900 * rng.random()
    tick = _highpass(rng.standard_normal(len(t)), 3000) * np.exp(-t / 0.0018)
    body = _bandpass(rng.standard_normal(len(t)), f * 0.7, f * 1.3) * np.exp(-t / 0.012)
    lvl = 0.55 + 0.35 * rng.random()
    return _norm(_stereo(0.6 * tick + body, pan=(rng.random() - 0.5) * 0.3), lvl)


def sparkle(dur=0.9, seed=6, n=16):
    """Glints for the particle burst: short high partials, staggered and panned."""
    rng = _rng(seed)
    out = np.zeros((int(dur * SR), 2))
    for i in range(n):
        start = int((rng.random() ** 1.6) * (dur - 0.25) * SR)
        f = 3000 + 5000 * rng.random()
        t = _t(0.25)
        ping = np.sin(2 * np.pi * f * t) * np.exp(-t / (0.03 + 0.05 * rng.random()))
        st = _stereo(ping * (0.4 + 0.6 * rng.random()), pan=rng.random() * 2 - 1)
        out[start:start + len(t)] += st[: len(out) - start]
    return _norm(out, 0.6)


def glitch(dur=0.32, seed=8):
    """Digital tear: sample-and-hold noise, crushed square chirps, hard gating."""
    rng = _rng(seed)
    t = _t(dur)
    hold = np.repeat(rng.standard_normal(len(t) // 64 + 1), 64)[: len(t)]
    chirp = signal.square(2 * np.pi * np.cumsum(180 + 2400 * rng.random(len(t)) ** 8) / SR)
    gate = (np.repeat(rng.random(len(t) // 480 + 1), 480)[: len(t)] > 0.35).astype(float)
    crushed = np.round((0.6 * hold + 0.4 * chirp) * 6) / 6
    mono = _bandpass(crushed * gate, 150, 9000) * (1 - t / dur) ** 0.5
    left = mono
    right = np.roll(mono, 90)
    return _norm(np.stack([left, right], 1), 0.75)


def pop(seed=9, base=620):
    t = _t(0.09)
    f = base * (1 + 1.2 * (1 - np.exp(-t / 0.012)))
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.028)
    return _norm(_stereo(tone), 0.6)


def swish(dur=0.24, seed=10):
    return _norm(whoosh(dur, direction=1, seed=seed, bright=1.8), 0.55)


def shine(dur=0.9, seed=12):
    """A soft metallic glint for the logo sweep."""
    rng = _rng(seed)
    t = _t(dur)
    x = t / dur
    gl = sum(np.sin(2 * np.pi * np.cumsum(f0 * (1 + 0.5 * x)) / SR) for f0 in (2400, 3150, 4700))
    air = _sweep_filter(rng.standard_normal(len(t)), 3000 + 5000 * x, q=3)
    env = np.sin(np.pi * x) ** 2
    return _norm(_tail(_stereo((0.4 * gl / 3 + 0.6 * _norm(air)) * env), 0.8, seed, 0.3), 0.5)


def scan(dur=0.75, seed=13):
    """HUD scan: a filtered saw sweep with two confirmation beeps."""
    t = _t(dur)
    x = t / dur
    saw = signal.sawtooth(2 * np.pi * np.cumsum(90 + 40 * x) / SR)
    sweep = _sweep_filter(saw, 400 + 3200 * x, q=4)
    env = np.minimum(1, x * 8) * (1 - x) ** 0.6
    beeps = np.zeros_like(t)
    for at in (0.52, 0.64):
        s = int(at * SR)
        b = _t(0.05)
        beeps[s:s + len(b)] += np.sin(2 * np.pi * 1850 * b) * np.hanning(len(b))
    return _norm(_stereo(0.7 * _norm(sweep) * env + 0.5 * beeps), 0.55)


def tick(seed=14):
    t = _t(0.04)
    return _norm(_stereo(np.sin(2 * np.pi * 2400 * t) * np.hanning(len(t))), 0.4)


def boom_tail(seed=15):
    """Final hit: a bigger impact with a long ring for the end card."""
    return impact(size=1.4, seed=seed)
