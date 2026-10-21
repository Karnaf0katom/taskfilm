#!/usr/bin/env python3
"""Make a palette-optimized GIF from a finished movie with FFmpeg."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from polish import number, probe, sha256


def convert(source: Path, output: Path, *, width=960, fps=15, start=0, duration=None) -> dict:
    source, output = source.resolve(), output.absolute()
    if output.suffix.lower() != ".gif":
        raise ValueError("output must end in .gif")
    if output.exists() or output.is_symlink():
        raise ValueError("GIF output must be a new file")
    number(width, "width", 32, 1920)
    if not isinstance(width, int):
        raise ValueError("width must be an integer")
    number(fps, "fps", 1, 30)
    media = probe(source)
    number(start, "start", 0, media["duration"])
    duration = media["duration"]-start if duration is None else duration
    number(duration, "duration", .01, media["duration"]-start)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".taskfilm-gif-", dir=output.parent) as temp:
        target = Path(temp) / "preview.gif"
        filters = (f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];"
                   "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle")
        result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", str(start),
            "-t", str(duration), "-i", str(source), "-filter_complex_threads", "1",
            "-filter_complex", filters, "-threads", "1", "-loop", "0", str(target)],
            capture_output=True, text=True, timeout=600)
        if result.returncode or not target.is_file():
            raise ValueError("FFmpeg could not create the GIF: " + result.stderr[-1000:])
        # A hard link atomically refuses an output created by another writer.
        output.hardlink_to(target)
    return {"output": str(output), "sha256": sha256(output), "bytes": output.stat().st_size,
            "width": width, "fps": fps, "start": start, "duration": duration, "audio": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--width", default=960, type=int)
    parser.add_argument("--fps", default=15, type=int)
    parser.add_argument("--start", default=0, type=float)
    parser.add_argument("--duration", type=float)
    args = parser.parse_args()
    try:
        print(json.dumps(convert(args.source, args.output, width=args.width, fps=args.fps,
                                 start=args.start, duration=args.duration), indent=2))
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f"taskfilm gif: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
