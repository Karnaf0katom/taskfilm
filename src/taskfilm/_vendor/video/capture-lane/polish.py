#!/usr/bin/env python3
"""Import a recording and author an editable screencast through hfcomp.

No provider, account, desktop agent or alternate renderer is started. Times
in edits.json always refer to the original clip, before trims and speed edits.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

import hfcomp
import plan as capture_plan
from screen_style import EASINGS, PRESETS, fields, number, style_config

SCHEMA = "taskfilm-polish/v1"
SPEC_FIELDS = {"schema", "preset", "style", "width", "height", "trim", "cuts", "speed", "zooms",
               "annotations", "cursor", "cursor_overlay", "cursor_smoothing", "auto_zoom", "audio"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(source: Path) -> dict:
    if not source.is_file():
        raise ValueError("source must be an existing recording file")
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                             "-of", "json", str(source)], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError("FFprobe could not read the recording: " + result.stderr.strip()[-1000:])
    data = json.loads(result.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if not video:
        raise ValueError("source must contain a video stream")
    duration = number(float(video.get("duration") or data.get("format", {}).get("duration") or 0),
                      "recording duration", .01, 86400)
    width, height = int(video["width"]), int(video["height"])
    rotation = next((row.get("rotation", 0) for row in video.get("side_data_list", [])
                     if "rotation" in row), video.get("tags", {}).get("rotate", 0))
    if abs(float(rotation)) % 180 == 90:
        width, height = height, width
    if width <= 0 or height <= 0:
        raise ValueError("recording dimensions are invalid")
    return {"width": width, "height": height, "duration": duration,
            "audio": any(s.get("codec_type") == "audio" for s in data["streams"])}


def span(row, label: str, duration: float, extra=()) -> dict:
    fields(row, {"start", "end", *extra}, label)
    if not {"start", "end"} <= row.keys():
        raise ValueError(f"{label} requires start and end")
    start = number(row["start"], f"{label}.start", 0, duration)
    end = number(row["end"], f"{label}.end", 0, duration)
    if end - start < .01:
        raise ValueError(f"{label} must last at least 0.01 seconds")
    return {**row, "start": start, "end": end}


def rows(value, label, limit=1000):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{label} must be a list with at most {limit} entries")
    return value


def no_overlap(items: list[dict], label: str):
    for prev, cur in zip(items, items[1:]):
        if cur["start"] < prev["end"]:
            raise ValueError(f"{label} ranges must not overlap")


def validate(spec: dict, media: dict, *, preset=None, width=None, height=None) -> dict:
    fields(spec, SPEC_FIELDS, "edit")
    if spec.get("schema", SCHEMA) != SCHEMA:
        raise ValueError(f"schema must be {SCHEMA}")
    duration = media["duration"]
    result = {**spec, "schema": SCHEMA}
    for key, override, default in (("width", width, 1920), ("height", height, 1080)):
        value = override if override is not None else spec.get(key, default)
        number(value, key, 240, 7680)
        if not isinstance(value, int) or value % 2:
            raise ValueError(f"{key} must be an even integer")
        result[key] = value
    result["preset"] = preset or spec.get("preset", "studio")
    result["style"] = style_config(result["preset"], spec.get("style", {}), result["width"], result["height"])
    result["trim"] = span(spec.get("trim", {"start": 0, "end": duration}), "trim", duration)
    for key in ("cuts", "speed", "zooms", "annotations"):
        extra = {"speed": ("rate",), "zooms": ("x", "y", "scale", "ease"),
                 "annotations": ("text", "x", "y")}.get(key, ())
        result[key] = sorted([span(row, key, duration, extra) for row in rows(spec.get(key, []), key)],
                             key=lambda row: row["start"])
        if key != "annotations":
            no_overlap(result[key], key)
    for row in result["speed"]:
        row["rate"] = number(row.get("rate"), "speed.rate", .25, 8)
    for row in [*result["zooms"], *result["annotations"]]:
        row["x"] = number(row.get("x", .5), "x", 0, 1)
        row["y"] = number(row.get("y", .5), "y", 0, 1)
    for row in result["zooms"]:
        row["scale"] = number(row.get("scale", 1.5), "zoom.scale", 1, 3)
        row["ease"] = row.get("ease", "gentle")
        if not isinstance(row["ease"], str) or row["ease"] not in EASINGS:
            raise ValueError(f"zoom.ease must be one of {', '.join(EASINGS)}")
    for row in result["annotations"]:
        if not isinstance(row.get("text"), str) or not row["text"].strip() or len(row["text"]) > 500:
            raise ValueError("annotation.text must be 1–500 characters")
    result["cursor"] = []
    for row in rows(spec.get("cursor", []), "cursor", 10000):
        fields(row, {"t", "x", "y", "click"}, "cursor")
        sample = {key: number(row.get(key), f"cursor.{key}", 0, duration if key == "t" else 1)
                  for key in ("t", "x", "y")}
        sample["click"] = row.get("click", False)
        if not isinstance(sample["click"], bool):
            raise ValueError("cursor.click must be true or false")
        if result["cursor"] and sample["t"] <= result["cursor"][-1]["t"]:
            raise ValueError("cursor samples must have strictly increasing times")
        result["cursor"].append(sample)
    for key in ("cursor_overlay", "auto_zoom"):
        result[key] = spec.get(key, False)
        if not isinstance(result[key], bool):
            raise ValueError(f"{key} must be true or false")
    result["cursor_smoothing"] = number(spec.get("cursor_smoothing", .06), "cursor_smoothing", 0, .5)
    result["audio"] = spec.get("audio", "keep")
    if not isinstance(result["audio"], str) or result["audio"] not in {"keep", "mute"}:
        raise ValueError("audio must be keep or mute")
    return result


def compile_edit(spec: dict, media: dict) -> tuple[list, dict, dict]:
    """Compile source-time edits to the compositor's continuous media clock."""
    lo, hi = spec["trim"]["start"], spec["trim"]["end"]
    edges = sorted({lo, hi, *(t for row in [*spec["cuts"], *spec["speed"]]
                              for t in (row["start"], row["end"]) if lo < t < hi)})
    segments = []
    for start, end in zip(edges, edges[1:]):
        mid = (start + end) / 2
        if any(row["start"] <= mid < row["end"] for row in spec["cuts"]):
            continue
        rate = next((row["rate"] for row in spec["speed"] if row["start"] <= mid < row["end"]), 1.0)
        segments.append((start, end, rate))
    if not segments:
        raise ValueError("the edit removes the entire recording")
    clock = hfcomp.time_map(segments)
    if clock.total < .1:
        raise ValueError("the edited recording must last at least 0.1 seconds")

    def mapped(row):
        start, end = clock(row["start"]), clock(row["end"])
        return {**row, "start": start, "end": end} if end - start >= .01 else None

    zooms = list(spec["zooms"])
    if spec["auto_zoom"]:
        clicks = [{"t": r["t"], "x": r["x"], "y": r["y"]} for r in spec["cursor"] if r["click"]]
        diagonal = math.hypot(1, media["height"] / media["width"])
        automatic = capture_plan.merge_zooms([capture_plan.cluster_to_zoom(c)
                                              for c in capture_plan.cluster_clicks(clicks, diagonal)])
        for auto in automatic:
            row = {**asdict(auto), "end": min(auto.end, media["duration"]), "ease": "gentle"}
            if not any(row["start"] < z["end"] and row["end"] > z["start"] for z in zooms):
                zooms.append(row)
    zooms = sorted([value for row in zooms if (value := mapped(row))], key=lambda row: row["start"])
    plan = {"duration_s": clock.total, "screen": {"width": media["width"], "height": media["height"]},
            "zooms": zooms}
    presentation = {"style": spec["style"], "source_width": media["width"], "source_height": media["height"],
                    "cursor_overlay": spec["cursor_overlay"], "cursor_segments": [], "clicks": [],
                    "annotations": [value for row in spec["annotations"] if (value := mapped(row))]}
    cursor, times = spec["cursor"], [row["t"] for row in spec["cursor"]]
    offset = 0.0
    for start, end, rate in segments:
        segment_end = offset + (end-start)/rate
        samples = [row.copy() for row in cursor if start <= row["t"] < end]
        prior = bisect_right(times, start) - 1
        if prior >= 0 and (not samples or samples[0]["t"] > start) and start-times[prior] <= 1.5:
            samples.insert(0, {**cursor[prior], "t": start, "click": False})
        smoothed, prev = [], None
        for row in samples:
            t = offset + (row["t"]-start)/rate
            if row["click"]:
                presentation["clicks"].append({**row, "t": t, "duration": min(.5, segment_end-t)})
            x, y = row["x"], row["y"]
            tau = spec["cursor_smoothing"]
            if prev and tau and not row["click"] and t-prev["t"] <= 1.5:
                gain = 1 - math.exp(-(t-prev["t"])/tau)
                x, y = prev["x"]+gain*(x-prev["x"]), prev["y"]+gain*(y-prev["y"])
            prev = {"t": t, "x": x, "y": y}
            smoothed.append(prev)
        presentation["cursor_segments"].append({"start": offset, "end": segment_end, "samples": smoothed})
        offset = segment_end
    return segments, plan, presentation


def create(source: Path, destination: Path, spec: dict, *, preset=None, width=None, height=None) -> dict:
    source, destination = source.resolve(), destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("polish destination must be a new directory")
    media = probe(source)
    spec = validate(spec, media, preset=preset, width=width, height=height)
    segments, plan, presentation = compile_edit(spec, media)
    source_hash = sha256(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".taskfilm-polish-", dir=destination.parent) as temp:
        stage = Path(temp) / "project"
        (stage / "original").mkdir(parents=True)
        (stage / "assets").mkdir()
        original = stage / "original" / ("recording" + source.suffix.lower())
        shutil.copy2(source, original)
        if sha256(original) != source_hash:
            raise ValueError("recording changed while importing; retry with a stable source file")
        keep_audio = media["audio"] and spec["audio"] == "keep"
        if not hfcomp.tighten(original, stage / "assets/screen.mp4", segments, preserve_audio=keep_audio, fps=30):
            raise ValueError("FFmpeg could not encode the edited recording")
        voice = []
        if keep_audio:
            result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(stage / "assets/screen.mp4"),
                                     "-map", "0:a:0", "-threads", "1", str(stage / "assets/source-audio.wav")],
                                    capture_output=True, text=True, timeout=600)
            if result.returncode:
                raise ValueError("FFmpeg could not retain source audio: " + result.stderr[-1000:])
            voice = [{"id": "source-audio", "file": "assets/source-audio.wav", "at": 0, "s": plan["duration_s"]}]
        moves = hfcomp.punches(plan, 3)
        for move, zoom in zip(moves, plan["zooms"]):
            # A speed edit may make the focus interval shorter than the normal
            # compositor minimum. Keep both transitions inside that interval.
            move["in_s"] = min(move["in_s"], (zoom["end"]-zoom["start"])*.35)
            move["out_s"] = min(move["out_s"], (zoom["end"]-zoom["start"])*.35)
            move["out_at"] = zoom["end"]-move["out_s"]
            move["ease_in"], move["ease_out"] = EASINGS[zoom["ease"]]
        plan["name"] = "Taskfilm screencast"
        font_asset = hfcomp.copy_font_asset(stage)
        (stage / "index.html").write_text(hfcomp.build_html(plan, "screen.mp4", [], moves,
            spec["width"], spec["height"], None, voice=voice, font_file=font_asset, presentation=presentation))
        (stage / "hyperframes.json").write_text(json.dumps({
            "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
            "paths": {"assets": "assets"}, "media": {"autoProxy": True}}, indent=2) + "\n")
        (stage / "package.json").write_text(json.dumps({"name": "taskfilm-screencast", "private": True,
            "type": "module", "scripts": {name: f"npx --yes hyperframes@{hfcomp.HYPERFRAMES_VERSION} {cmd}"
                for name, cmd in (("dev", "preview"), ("check", "check"), ("render", "render"))}}, indent=2) + "\n")
        (stage / "edits.json").write_text(json.dumps(spec, indent=2) + "\n")
        report = {"schema": SCHEMA, "source": {"file": str(original.relative_to(stage)), "sha256": source_hash},
                  "media": media, "duration": plan["duration_s"], "segments": segments,
                  "zooms": len(moves), "annotations": len(presentation["annotations"]),
                  "clicks": len(presentation["clicks"]), "audio_retained": bool(keep_audio),
                  "output": {"width": spec["width"], "height": spec["height"]},
                  "evidence": {"workflow_assertions": "not_performed", "final_video_review": "not_performed"}}
        (stage / "POLISH.json").write_text(json.dumps(report, indent=2) + "\n")
        if destination.exists() or destination.is_symlink():
            raise ValueError("polish destination appeared during import")
        # Reserve exclusively, even if another writer appeared during encode.
        destination.mkdir()
        for item in stage.iterdir():
            item.rename(destination / item.name)
    return {**report, "project": str(destination), "render": f"taskfilm render {destination} --output screencast.mp4"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="existing screen recording; the original stays in the project")
    parser.add_argument("destination", type=Path, help="new editable project directory")
    parser.add_argument("--spec", type=Path, help="source-time edits and optional normalized cursor samples in JSON")
    parser.add_argument("--preset", choices=PRESETS, help="frame style; overrides the spec preset")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    args = parser.parse_args()
    try:
        spec = json.loads(args.spec.read_text()) if args.spec else {}
        print(json.dumps(create(args.source, args.destination, spec, preset=args.preset,
                                width=args.width, height=args.height), indent=2))
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f"taskfilm polish: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
