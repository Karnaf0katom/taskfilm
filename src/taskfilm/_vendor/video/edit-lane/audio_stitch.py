"Trim, normalize and join narration chunks with FFmpeg."

from __future__ import annotations

import subprocess

from dataclasses import asdict, dataclass

from typing import Sequence

import analyze  # edit-lane sibling — reuse its ffmpeg silence/loudness pass, don't re-implement

DEFAULT_GAP_MS = 250          # natural pause dropped between two sentences/chunks

DEFAULT_TRIM_DB = -38.0       # anything quieter than this at a clip edge is dead air

DEFAULT_KEEP_MS = 60          # keep this much of the edge silence so joins breathe (no hard cut)

DEFAULT_LUFS = -16.0          # one integrated loudness for the whole stitched track

SR = 44100                    # unify sample rate before concat (concat needs matching format)

class AudioStitchError(RuntimeError):
    """ffmpeg failed or inputs were unusable (carries the ffmpeg stderr tail)."""

@dataclass
class ClipLook:
    """What the 'look at the sound' pass sees for one clip — the trim/join decision inputs."""
    path: str
    duration: float
    lead_silence: float      # dead air at the head (s)
    trail_silence: float     # dead air at the tail (s)
    speech_estimate: float   # duration minus head+tail dead air (s)
    loudness_lufs: float | None

def _probe_duration(path: str) -> float:
    """Seconds, via ffprobe. Raises AudioStitchError if the file is undecodable."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        raise AudioStitchError(f"ffprobe could not read a duration from {path!r}: {proc.stderr[-300:]}")

def _run_ffmpeg(args: list[str]) -> None:
    """Run an ffmpeg encode; raise with the stderr tail on non-zero (never silently 'succeed')."""
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioStitchError(f"ffmpeg failed (rc={proc.returncode}): {(proc.stderr or '')[-500:]}")

def _codec_for(out_path: str) -> list[str]:
    ext = out_path.rsplit(".", 1)[-1].lower()
    if ext == "wav":
        return ["-c:a", "pcm_s16le"]
    if ext in ("mp3",):
        return ["-c:a", "libmp3lame", "-q:a", "2"]
    if ext in ("m4a", "aac", "mp4"):
        return ["-c:a", "aac", "-b:a", "192k"]
    return ["-c:a", "libmp3lame", "-q:a", "2"]  # sane default

def analyze_clip(path: str) -> ClipLook:
    """Silence + loudness read of one clip → the head/tail dead-air the stitcher will trim."""
    duration = _probe_duration(path)
    silences = analyze.run_silences(path)          # [{"start","end"}, ...] via silencedetect
    lead = 0.0
    trail = 0.0
    for seg in silences:
        if seg["start"] <= 0.05:                   # silence that starts at the very head
            lead = max(lead, float(seg["end"]))
    for seg in silences:
        if seg["end"] >= duration - 0.05:          # silence that runs to the very tail
            trail = max(trail, duration - float(seg["start"]))
    try:
        loud = analyze.run_loudness(path).get("input_i")
        loud = float(loud) if loud is not None else None
    except Exception:
        loud = None
    speech = max(0.0, duration - lead - trail)
    return ClipLook(path=path, duration=round(duration, 3), lead_silence=round(lead, 3),
                    trail_silence=round(trail, 3), speech_estimate=round(speech, 3),
                    loudness_lufs=loud)

def _trim_chain(idx: int, threshold_db: float, keep_ms: int, gap_s: float, is_last: bool) -> str:
    """Per-clip filtergraph: unify format -> trim head+tail silence -> pad an inter-clip gap.

    Both-ends trim is the reliable areverse sandwich: silenceremove only trims the *head*, so we
    trim, reverse (tail becomes head), trim again, reverse back.
    """
    keep = max(0.0, keep_ms / 1000.0)
    sr = (f"[{idx}:a]aresample={SR},aformat=sample_fmts=fltp:channel_layouts=mono")
    trim = (f"silenceremove=start_periods=1:start_threshold={threshold_db}dB:start_silence={keep:.3f}:detection=peak")
    pad = "" if is_last else f",apad=pad_dur={gap_s:.3f}"
    return f"{sr},{trim},areverse,{trim},areverse{pad}[a{idx}]"

def stitch(clip_paths: Sequence[str], out_path: str, *, gap_ms: int = DEFAULT_GAP_MS,
           threshold_db: float = DEFAULT_TRIM_DB, keep_ms: int = DEFAULT_KEEP_MS,
           target_lufs: float | None = DEFAULT_LUFS) -> dict:
    """Trim + normalize + join short clips into ONE file. Returns a receipt (durations + per-clip look)."""
    clips = [str(p) for p in clip_paths]
    if not clips:
        raise AudioStitchError("stitch needs at least one clip")
    looks = [analyze_clip(p) for p in clips]       # the 'look at the sound' pass (reused analyze.py)
    gap_s = max(0.0, gap_ms / 1000.0)

    if len(clips) == 1 and target_lufs is None:
        # single clip, no normalize -> a plain trim so the op is still meaningful
        graph = _trim_chain(0, threshold_db, keep_ms, gap_s, is_last=True)
        tail = f"[a0]"
    else:
        chains = [_trim_chain(i, threshold_db, keep_ms, gap_s, is_last=(i == len(clips) - 1))
                  for i in range(len(clips))]
        joined = "".join(f"[a{i}]" for i in range(len(clips)))
        concat = f"{joined}concat=n={len(clips)}:v=0:a=1[cat]"
        chains.append(concat)
        graph = ";".join(chains)
        tail = "[cat]"
        if target_lufs is not None:
            graph += f";{tail}loudnorm=I={target_lufs}:TP=-1.5:LRA=11[out]"
            tail = "[out]"

    args = ["ffmpeg", "-y", "-loglevel", "error", "-nostdin"]
    for p in clips:
        args += ["-i", p]
    args += ["-filter_complex", graph, "-map", tail, *_codec_for(out_path), out_path]
    _run_ffmpeg(args)

    out_dur = _probe_duration(out_path)
    return {
        "out": out_path,
        "out_duration": round(out_dur, 3),
        "n_clips": len(clips),
        "input_total": round(sum(l.duration for l in looks), 3),
        "speech_total": round(sum(l.speech_estimate for l in looks), 3),
        "gap_ms": gap_ms,
        "target_lufs": target_lufs,
        "clips": [asdict(l) for l in looks],
    }
