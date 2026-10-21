"""Check a complete encoded animation against its authored plan.

This is release verification, not a subjective quality verdict. Frame samples
and measured motion are retained for an owning-session visual review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def run(argv: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, capture_output=True, timeout=240)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace")[-3000:])
    return result


def verify(movie: Path, project: Path, out: Path) -> dict:
    from PIL import Image, ImageChops, ImageStat, ImageOps, ImageDraw
    plan = json.loads((project / "ANIMATION-PLAN.json").read_text())
    cfg = plan["config"]
    out.mkdir(parents=True, exist_ok=False)
    probe = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(movie)]).stdout)
    (out / "probe.json").write_text(json.dumps(probe, indent=2) + "\n")
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    a, b = map(int, video["avg_frame_rate"].split("/"))
    fps, duration = a / b, float(video["duration"])
    if (video["width"], video["height"]) != (cfg["width"], cfg["height"]):
        raise ValueError("encoded dimensions differ from authored dimensions")
    if abs(fps - cfg["fps"]) > .01 or abs(duration - cfg["duration"]) > 1 / cfg["fps"] + .002:
        raise ValueError("encoded FPS/duration differ from authored plan")
    decoded = run(["ffmpeg", "-v", "error", "-threads", "1", "-i", str(movie), "-f", "null", "-"])
    (out / "decode.log").write_bytes(decoded.stderr)
    scan_w = 160
    scan_h = int(scan_w * cfg["height"] / cfg["width"])
    frame_bytes = scan_w * scan_h
    decoded_pixels = run(["ffmpeg", "-v", "error", "-threads", "1", "-i", str(movie), "-an", "-vf",
        f"scale={scan_w}:{scan_h},format=gray", "-fps_mode", "passthrough", "-f", "rawvideo", "-"]).stdout
    if len(decoded_pixels) % frame_bytes:
        raise ValueError("incomplete decoded frame in motion audit")
    count = len(decoded_pixels) // frame_bytes
    if abs(count - cfg["duration"] * cfg["fps"]) > 1:
        raise ValueError("encoded frame count differs from plan")
    differences, mean_levels = [], []
    previous = None
    for index in range(count):
        image = Image.frombytes("L", (scan_w, scan_h), decoded_pixels[index*frame_bytes:(index+1)*frame_bytes])
        mean_levels.append(ImageStat.Stat(image).mean[0])
        if previous is not None:
            differences.append(ImageStat.Stat(ImageChops.difference(previous, image)).mean[0])
        previous = image
    # Threshold is an explicit technical signal at this scan resolution, not
    # a claim that every small movement is useful or readable.
    threshold = .02
    moving = sum(value > threshold for value in differences)
    end_flat = 0
    for value in reversed(differences):
        if value > threshold:
            break
        end_flat += 1
    max_flat, streak = 0, 0
    body = differences[:len(differences) - end_flat] if end_flat else differences
    for value in body:
        streak = streak + 1 if value <= threshold else 0
        max_flat = max(streak, max_flat)
    audio = next((stream for stream in probe["streams"] if stream["codec_type"] == "audio"), None)
    planned_audio = plan["audio"] != "deliberate_silence"
    if planned_audio != bool(audio):
        raise ValueError("encoded audio presence differs from authored plan")
    loudness = None
    if planned_audio:
        measured = run(["ffmpeg", "-hide_banner", "-threads", "1", "-i", str(movie), "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]).stderr.decode()
        loudness = json.loads(measured[measured.rindex("{"):measured.rindex("}")+1])
        (out / "loudness.json").write_text(json.dumps(loudness, indent=2)+"\n")
        if not -18 <= float(loudness["input_i"]) <= -14 or float(loudness["input_tp"]) > -1:
            raise ValueError(f"encoded audio outside delivery levels: {loudness}")
    times = [0, .4, 1.8, 2.6, 4, 6.8, 8.2, 10.8, 11.8] if cfg["duration"] == 12 else [0, .4, 1.8, 3.6, 5.4, 7.2, 9.6, 10.8, 12.6, 14.4, 16.2, 17.8]
    samples = []
    for index, at in enumerate(times):
        target = out / f"frame-{index:02d}.png"
        run(["ffmpeg", "-v", "error", "-threads", "1", "-ss", str(at), "-i", str(movie), "-frames:v", "1", str(target)])
        samples.append({"time": at, "file": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    thumb_w, thumb_h = (480, 270) if cfg["width"] > cfg["height"] else (270, 480)
    cols = 4 if cfg["duration"] == 18 else 3
    rows = (len(samples) + cols - 1) // cols
    sheet = Image.new("RGB", (thumb_w * cols, (thumb_h + 28) * rows), "#fff5e5")
    draw = ImageDraw.Draw(sheet)
    for index, sample in enumerate(samples):
        x, y = index % cols * thumb_w, index // cols * (thumb_h + 28)
        draw.text((x+8,y+5), f"{sample['time']:g}s", fill="#142124")
        with Image.open(out / sample["file"]) as picture:
            sheet.paste(ImageOps.contain(picture,(thumb_w,thumb_h)),(x,y+28))
    sheet.save(out / "contact-sheet.jpg", quality=94)
    source_hashes = {name: hashlib.sha256((project / name).read_bytes()).hexdigest()
                     for name in ("index.html", "runtime.js", "ANIMATION-PLAN.json")}
    gates = {"dimensions_fps_duration": True, "complete_decode": True,
             "nonblank": min(mean_levels) > 3, "picture_moves": moving > count * .5,
             "end_hold_at_most_1_4_seconds": end_flat / fps <= 1.4 + 1 / fps,
             "audio_matches_plan": True}
    report = {"schema": "taskfilm-encoded-animation-check/v1", "movie": movie.name,
              "movie_sha256": hashlib.sha256(movie.read_bytes()).hexdigest(), "source_hashes": source_hashes,
              "width": video["width"], "height": video["height"], "fps": fps, "duration": duration,
              "frames": count, "audio": bool(audio), "loudness": loudness,
              "motion_audit": {"scan_width": scan_w, "scan_height": scan_h, "threshold_mean_abs_gray": threshold,
                  "moving_differences": moving, "max_flat_run_before_ending": max_flat,
                  "end_flat_frames": end_flat, "end_hold_seconds": end_flat / fps},
              "gates": gates, "samples": samples, "visual_review": "pending owning-session inspection",
              "audio_listening": "pending" if audio else "not applicable: deliberate silence"}
    (out / "verification.json").write_text(json.dumps(report, indent=2)+"\n")
    if not all(gates.values()):
        raise ValueError(f"encoded check failed: {gates}; read {out / 'verification.json'}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--movie", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.movie,args.project,args.out),indent=2))
    except (ValueError, OSError, subprocess.TimeoutExpired, KeyError, StopIteration) as exc:
        parser.exit(2,f"animation check: {exc}\n")


if __name__ == "__main__":
    main()
