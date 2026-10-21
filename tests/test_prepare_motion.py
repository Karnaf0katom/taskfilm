"""Validate the portable Taskboard motion-geometry binder without a browser."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest


def load_helper():
    source = Path(__file__).parents[1] / "release/prepare_motion.py"
    if not source.is_file():
        from taskfilm.cli import HERE
        source = HERE / "examples/prepare-motion.py"
    spec = importlib.util.spec_from_file_location("taskfilm_prepare_motion_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPER = load_helper()
GEOMETRY = {
    "input": {"x": 300.5, "y": 1200.25, "width": 1400.0, "height": 180.0},
    "row": {"x": 300.0, "y": 1650.0, "width": 3200.0, "height": 310.0},
    "nav": {"x": 250.0, "y": 1450.0, "width": 3300.0, "height": 160.0},
}


def retained_taskboard(tmp_path: Path) -> tuple[Path, Path]:
    sample = tmp_path / "sample"
    take = tmp_path / "take"
    sample.mkdir()
    take.mkdir()
    source_spec = Path(__file__).parents[1] / "examples/motion-spec.json"
    if source_spec.is_file():
        motion_spec = json.loads(source_spec.read_text())
    else:
        motion_spec = {
            "schema": "product-motion/v1", "expect": {"clicks": 4, "keys": 13},
            "edit": {"act1": {"click": 0, "submit_click": 1, "keys": [0, 13]},
                     "act2": {"click": 2}, "act3": {"click": 3}},
        }
    (sample / "motion-spec.json").write_text(json.dumps(motion_spec))
    session = {
        "t0_wallclock": 1000.0, "duration_s": 12.0,
        "screen": {"width": 3840, "height": 2160},
        "steps": {"total": 8, "ok": 8, "failures": [], "setup_problems": []},
        "streams": {
            "screen": {"status": "ok", "path": "screen.mp4", "frames": 180, "dropped": 0},
            "input": {"status": "ok", "path": "input.jsonl"},
        },
    }
    (take / "session.json").write_text(json.dumps(session))
    (take / "screen.mp4").write_bytes(b"retained source video")
    events = [{"device": "mouse", "type": "click", "pressed": True, "ts": 1001.0}]
    events.extend({"device": "keyboard", "type": "press", "ts": 1001.2 + index * .05}
                  for index in range(13))
    events.extend({"device": "mouse", "type": "click", "pressed": True, "ts": timestamp}
                  for timestamp in (1002.2, 1005.0, 1008.0))
    events.sort(key=lambda row: row["ts"])
    (take / "input.jsonl").write_text("".join(json.dumps(row) + "\n" for row in events))
    return sample, take


def test_prepare_binds_measured_geometry_to_retained_event_anchors(tmp_path):
    sample, take = retained_taskboard(tmp_path)

    async def measured(url):
        assert url == "http://127.0.0.1:8765/"
        return GEOMETRY

    result = asyncio.run(HELPER.prepare(sample, take, "http://127.0.0.1:8765/", measured))
    spec = json.loads((sample / "spec.json").read_text())
    geometry = json.loads((sample / "sample-geometry.json").read_text())

    assert result["geometry"] == geometry == GEOMETRY
    assert spec["take"] == "../take"
    assert spec["expect"] == {"clicks": 4, "keys": 13}
    assert spec["edit"]["act1"]["type_window"] == pytest.approx([.9, 2.08])
    assert spec["edit"]["act2"]["result_after"] == pytest.approx(4.85)
    assert spec["edit"]["act3"]["result_after"] == pytest.approx(7.85)
    assert spec["edit"]["act2"]["result_region"] == [300, 1650, 3500, 1960]
    assert spec["edit"]["act3"]["result_region"] == [250, 1450, 3550, 1610]


def test_cli_rejects_malformed_capture_before_measurement_or_output(tmp_path, monkeypatch, capsys):
    sample, take = retained_taskboard(tmp_path)
    session_path = take / "session.json"
    session = json.loads(session_path.read_text())
    session["streams"]["screen"]["dropped"] = 1
    session_path.write_text(json.dumps(session))

    async def must_not_measure(_url):
        raise AssertionError("invalid capture must be rejected before browser measurement")

    monkeypatch.setattr(HELPER, "measure", must_not_measure)
    with pytest.raises(SystemExit) as raised:
        HELPER.main(["--sample", str(sample), "--take", str(take), "--url", "http://invalid.test/"])

    assert raised.value.code == 2
    assert "zero dropped frames" in capsys.readouterr().err
    assert not (sample / "spec.json").exists()
    assert not (sample / "sample-geometry.json").exists()
