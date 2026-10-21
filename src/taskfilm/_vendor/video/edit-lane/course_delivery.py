"Course media validation and delivery using supplied recordings and voiceovers."

from __future__ import annotations

from contextlib import contextmanager

import json

import math

import os

from pathlib import Path

import subprocess

import tempfile

def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                             "-of", "json", str(path)], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError("Cannot read the recording. Check the file with a video player.")
    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("The recording has no usable duration.")
    return {"duration": duration, "video": any(s["codec_type"] == "video" for s in data["streams"]),
            "audio": any(s["codec_type"] == "audio" for s in data["streams"])}

@contextmanager
def one_key(key: str):
    names = ("ELEVENLABS_API_KEY", "ELEVENLABS_API_KEYS")
    previous = {name: os.environ.get(name) for name in names}
    os.environ.update(ELEVENLABS_API_KEY=key, ELEVENLABS_API_KEYS="")
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

def deliver(source: Path, output: Path, *, voice: Path | None = None) -> dict:
    """Keep demonstration timing and full frame; replace sound only when requested."""
    if output.exists():
        raise ValueError("Choose a new output; existing lessons are kept.")
    media = probe(source)
    if not media["video"]:
        raise ValueError("Choose a screen recording containing video.")
    if voice and probe(voice)["duration"] > media["duration"] + .1:
        raise ValueError("The narration is longer than the demonstration. Shorten the text or record a longer take.")
    args = ["ffmpeg", "-v", "error", "-nostdin", "-n", "-i", str(source)]
    if voice:
        args += ["-i", str(voice), "-map", "0:v:0", "-map", "1:a:0", "-af", "apad",
                 "-t", str(media["duration"])]
    else:
        args += ["-map", "0:v:0", "-map", "0:a:0?"]
    with tempfile.TemporaryDirectory(prefix=".course-export-", dir=output.parent) as scratch:
        temporary = Path(scratch) / "lesson.mp4"
        args += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-threads", "1",
                 "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
                 "-movflags", "+faststart", str(temporary)]
        result = subprocess.run(args, capture_output=True, timeout=1800)
        if result.returncode:
            raise ValueError("Video export failed. The original recording is retained.")
        probe(temporary)
        temporary.replace(output)
    receipt = {"source": str(source), "output": str(output), "duration_s": media["duration"],
               "narration": str(voice) if voice else None, "speed": 1,
               "workflow_accuracy": "teacher_review_required", "audio_action_sync": "teacher_review_required"}
    output.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
