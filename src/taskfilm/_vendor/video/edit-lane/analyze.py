"Measure narration silence and loudness with FFmpeg."

from __future__ import annotations

import re

import subprocess

SILENCEDETECT_FILTER = "silencedetect=d=0.35:n=-32dB"

LOUDNESS_FILTER = "ebur128"

_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")

_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")

def parse_silences(ffmpeg_stderr: str) -> list[dict]:
    """Parse ``silencedetect`` stderr into ``[{"start": float, "end": float}, ...]``.

    Pairs each ``silence_start`` with the next ``silence_end`` in document order. A
    trailing unmatched ``silence_start`` (silence that runs to EOF, which ffmpeg can omit
    the ``silence_end`` for) is dropped rather than guessed — the assembler only wants
    closed intervals. Negative starts (ffmpeg occasionally reports tiny negative values)
    are clamped to ``0.0``.
    """
    starts: list[float] = []
    ends: list[float] = []
    for line in ffmpeg_stderr.splitlines():
        m = _SILENCE_START_RE.search(line)
        if m:
            starts.append(max(0.0, float(m.group(1))))
            continue
        m = _SILENCE_END_RE.search(line)
        if m:
            ends.append(float(m.group(1)))

    segments: list[dict] = []
    for start, end in zip(starts, ends):
        segments.append({"start": start, "end": end})
    return segments

_NUM = r"(-?\d+(?:\.\d+)?)"

_INTEGRATED_RE = re.compile(r"^\s*I:\s*" + _NUM + r"\s*LUFS", re.MULTILINE)

_LRA_RE = re.compile(r"^\s*LRA:\s*" + _NUM + r"\s*LU\b", re.MULTILINE)

_LRA_LOW_RE = re.compile(r"^\s*LRA low:\s*" + _NUM + r"\s*LUFS", re.MULTILINE)

_LRA_HIGH_RE = re.compile(r"^\s*LRA high:\s*" + _NUM + r"\s*LUFS", re.MULTILINE)

_THRESHOLD_RE = re.compile(r"^\s*Threshold:\s*" + _NUM + r"\s*LUFS", re.MULTILINE)

def parse_loudness(ffmpeg_stderr: str) -> dict:
    """Parse the ``ebur128``/``loudnorm`` summary into a loudness dict.

    Returns ``{"integrated_lufs", "lra", "threshold_lufs", "lra_low_lufs",
    "lra_high_lufs"}`` — each value a float, or ``None`` when ffmpeg did not print it.
    ``integrated_lufs`` is the headline number (EBU R128 integrated loudness) used
    downstream to decide whether to normalize.
    """

    def _first(rx: re.Pattern[str]) -> float | None:
        m = rx.search(ffmpeg_stderr)
        return float(m.group(1)) if m else None

    return {
        "integrated_lufs": _first(_INTEGRATED_RE),
        "lra": _first(_LRA_RE),
        # First Threshold in the block belongs to "Integrated loudness:".
        "threshold_lufs": _first(_THRESHOLD_RE),
        "lra_low_lufs": _first(_LRA_LOW_RE),
        "lra_high_lufs": _first(_LRA_HIGH_RE),
    }

def _ffmpeg_capture(args: list[str]) -> str:
    """Run ffmpeg, return combined stderr (ffmpeg writes diagnostics to stderr)."""
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.stderr or ""

def run_silences(input_path: str) -> list[dict]:
    """Spawn ``ffmpeg -af silencedetect=... -f null -`` and parse the result."""
    stderr = _ffmpeg_capture(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", input_path, "-af", SILENCEDETECT_FILTER, "-f", "null", "-"]
    )
    return parse_silences(stderr)

def run_loudness(input_path: str) -> dict:
    """Spawn ``ffmpeg -af ebur128 -f null -`` and parse the Summary block."""
    stderr = _ffmpeg_capture(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", input_path, "-af", LOUDNESS_FILTER, "-f", "null", "-"]
    )
    return parse_loudness(stderr)
