#!/usr/bin/env python3
"""Bind the original sample's measured DOM geometry to its retained real take."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
from typing import Awaitable, Callable


CAPTURE_SIZE = (3840, 2160)
EXPECTED_CLICKS = 4


async def measure(url: str) -> dict:
    # Keep the exported helper importable for validation and unit tests without Playwright.
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=os.environ.get("CAPTURE_LANE_BROWSER_PATH"),
                                           args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 3840, "height": 2160})
        await page.goto(url)
        await page.evaluate("document.documentElement.style.zoom='3'")
        input_box = await page.locator("#task-title").bounding_box()
        await page.locator("#task-title").fill("Ship the demo")
        await page.locator("button[type=submit]").click()
        row_box = await page.locator("#tasks li").bounding_box()
        nav_box = await page.locator("nav").bounding_box()
        await browser.close()
    return {"input": input_box, "row": row_box, "nav": nav_box}


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label} at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} at {path} must contain a JSON object")
    return value


def _read_events(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read retained input at {path}: {exc}") from exc
    if not events or any(not isinstance(row, dict) for row in events):
        raise ValueError(f"retained input at {path} must contain JSON event objects")
    return events


def _number(value, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")
    return float(value)


def _validate_take(take: Path, session: dict, events: list[dict], spec: dict) -> tuple[list[float], list[float]]:
    if (session.get("screen", {}).get("width"), session.get("screen", {}).get("height")) != CAPTURE_SIZE:
        raise ValueError("retained capture must be completed at 3840x2160")
    steps = session.get("steps", {})
    total = steps.get("total")
    if (not isinstance(total, int) or isinstance(total, bool) or total <= 0
            or steps.get("ok") != total or steps.get("failures") or steps.get("setup_problems")):
        raise ValueError("retained capture steps are incomplete")
    streams = session.get("streams", {})
    screen = streams.get("screen", {})
    if (screen.get("status") != "ok" or not isinstance(screen.get("frames"), int)
            or isinstance(screen.get("frames"), bool) or screen["frames"] <= 0
            or screen.get("dropped") != 0):
        raise ValueError("retained screen capture must be complete with frames and zero dropped frames")
    if streams.get("input", {}).get("status") != "ok":
        raise ValueError("retained input stream is not complete")

    video_name = screen.get("path")
    if not isinstance(video_name, str) or not video_name:
        raise ValueError("retained screen capture has no source video path")
    video = (take / video_name).resolve()
    try:
        if not video.is_relative_to(take.resolve()) or not video.is_file() or video.stat().st_size <= 0:
            raise ValueError("retained source video is missing or empty")
    except OSError as exc:
        raise ValueError(f"cannot inspect retained source video: {exc}") from exc

    t0 = _number(session.get("t0_wallclock"), "session t0_wallclock")
    duration = _number(session.get("duration_s"), "session duration_s", positive=True)
    expected = spec.get("expect", {})
    expected_keys = expected.get("keys")
    if expected.get("clicks") != EXPECTED_CLICKS or not isinstance(expected_keys, int) \
            or isinstance(expected_keys, bool) or expected_keys <= 0:
        raise ValueError("motion spec must expect the Taskboard workflow's four clicks and typing run")

    def relative_times(rows: list[dict], label: str) -> list[float]:
        times = [_number(row.get("ts"), f"{label} timestamp") - t0 for row in rows]
        if any(value < 0 or value > duration for value in times) or times != sorted(times):
            raise ValueError(f"retained {label} timestamps must be ordered within the capture")
        return times

    click_rows = [row for row in events
                  if row.get("device") == "mouse" and row.get("type") == "click" and row.get("pressed") is True]
    key_rows = [row for row in events
                if row.get("device") == "keyboard" and row.get("type") == "press"]
    if len(click_rows) != EXPECTED_CLICKS or len(key_rows) != expected_keys:
        raise ValueError(
            f"retained input does not match Taskboard motion workflow: expected 4 clicks and "
            f"{expected_keys} key presses, found {len(click_rows)} and {len(key_rows)}")
    clicks = relative_times(click_rows, "click")
    keys = relative_times(key_rows, "key")
    if not (clicks[0] <= keys[0] <= keys[-1] <= clicks[1] < clicks[2] < clicks[3]):
        raise ValueError("retained input does not contain the expected click, typing, and result order")

    edit = spec.get("edit", {})
    try:
        anchors = (edit["act1"]["click"], edit["act1"]["submit_click"],
                   edit["act2"]["click"], edit["act3"]["click"], edit["act1"]["keys"])
    except (KeyError, TypeError) as exc:
        raise ValueError("motion spec is missing its Taskboard click/key anchors") from exc
    if anchors != (0, 1, 2, 3, [0, expected_keys]):
        raise ValueError("motion spec click/key anchors do not match the Taskboard workflow")
    return clicks, keys


def _validate_geometry(geometry: dict) -> dict:
    if not isinstance(geometry, dict):
        raise ValueError("measured geometry must be a JSON object")
    width, height = CAPTURE_SIZE
    checked = {}
    for name in ("input", "row", "nav"):
        box = geometry.get(name)
        if not isinstance(box, dict):
            raise ValueError(f"measured geometry is missing the {name} box")
        values = {key: _number(box.get(key), f"geometry {name}.{key}", positive=key in {"width", "height"})
                  for key in ("x", "y", "width", "height")}
        if values["x"] < 0 or values["y"] < 0 \
                or values["x"] + values["width"] > width \
                or values["y"] + values["height"] > height:
            raise ValueError(f"measured geometry {name} box is outside the 3840x2160 capture")
        checked[name] = values
    return checked


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValueError(f"cannot write {path}: {exc}") from exc


async def prepare(sample: Path, take: Path, url: str,
                  measurer: Callable[[str], Awaitable[dict]] | None = None) -> dict:
    spec = _read_json(sample / "motion-spec.json", "motion spec")
    session = _read_json(take / "session.json", "capture session")
    events = _read_events(take / "input.jsonl")
    clicks, keys = _validate_take(take, session, events, spec)
    geometry = _validate_geometry(await (measurer or measure)(url))

    def xywh(box):
        return [math.floor(box[key]) for key in ("x", "y", "width", "height")]

    def region(box):
        x, y, w, h = xywh(box)
        return [x, y, x + w, y + h]

    spec["take"] = os.path.relpath(take.resolve(), sample.resolve())
    spec["expect"] = {"clicks": len(clicks), "keys": len(keys)}
    a1, a2, a3 = (spec["edit"][f"act{i}"] for i in (1, 2, 3))
    inp = geometry["input"]
    a1.update(keys=[0, len(keys)],
              type_region=[int(inp["x"] + 40), int(inp["y"] + 20),
                           int(inp["x"] + 1250), int(inp["y"] + inp["height"] - 20)],
              type_window=[keys[0] - .3, clicks[1] - .12])
    a2.update(result_region=region(geometry["row"]), lift_region=xywh(geometry["row"]),
              result_window=[clicks[2] - .4, clicks[2] + 1.5], result_after=clicks[2] - .15)
    a3.update(result_region=region(geometry["nav"]), track_region=xywh(geometry["row"]),
              result_window=[clicks[3] - .4, clicks[3] + 1.5], result_after=clicks[3] - .15)
    row = geometry["row"]
    spec["edit"]["recap"] = [
        ["type_end", .15, inp["x"] - 20, inp["y"] - 60, 1800],
        ["saved_visible", .2, row["x"] - 20, row["y"] - 100, 1800],
        ["filtered", .3, row["x"] - 20, row["y"] - 100, 1800],
    ]
    # Write the independently valid measurement first and the consumer spec last.
    _write_json(sample / "sample-geometry.json", geometry)
    _write_json(sample / "spec.json", spec)
    return {"film": str(sample), "take": str(take), "geometry": geometry}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--take", type=Path, required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(prepare(args.sample, args.take, args.url))
    except Exception as exc:  # argparse owns a concise exit-2 boundary for CLI/setup failures.
        parser.error(f"could not prepare Taskboard motion: {exc}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
