"""Public installed-distribution checks for variety and editable authoring."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import wave

import pytest


def invoke(cwd, *args):
    return subprocess.run([sys.executable, "-I", "-m", "taskfilm", *map(str, args)],
                          cwd=cwd, capture_output=True, text=True, timeout=60)


def plan(cwd, *args):
    result = invoke(cwd, "treatments", "--brief", "A motion study for one idea", *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def history_for(row):
    return {"schema": "taskfilm-treatment-history/v1", "events": [
        {"status": "reviewed", "treatment_id": row["id"], "fingerprint": row["fingerprint"],
         "movie_sha256": "a" * 64}]}


def test_same_inputs_replay_and_history_changes_structure(tmp_path):
    original = plan(tmp_path, "--seed", 9)
    assert plan(tmp_path, "--seed", 9) == original
    row = original["candidates"][0]
    history = tmp_path / "history.json"
    history.write_text(json.dumps(history_for(row)))
    before = history.read_bytes()
    next_plan = plan(tmp_path, "--seed", 9, "--history", history)
    assert next_plan["selected"] != original["selected"]
    assert next_plan["candidates"][0]["structural_changes"] >= 2
    assert history.read_bytes() == before
    assert all(c["support"] == "authorable" for c in next_plan["candidates"])


def test_failed_and_planned_runs_do_not_consume_variety(tmp_path):
    before = plan(tmp_path)
    file = tmp_path / "history.json"
    file.write_text(json.dumps({"schema": "taskfilm-treatment-history/v1",
                              "events": [{"status": "failed"}, {"status": "planned"}]}))
    after = plan(tmp_path, "--history", file)
    assert [c["id"] for c in after["candidates"]] == [c["id"] for c in before["candidates"]]


def test_exhaustion_is_explicit_and_series_override_works(tmp_path):
    before = plan(tmp_path)
    events = [history_for(row)["events"][0] for row in before["candidates"]]
    file = tmp_path / "history.json"
    file.write_text(json.dumps({"schema": "taskfilm-treatment-history/v1", "events": events}))
    result = invoke(tmp_path, "treatments", "--brief", "motion study", "--history", file)
    assert result.returncode == 3
    assert json.loads(result.stdout)["selected"] is None
    assert "No unused" in json.loads(result.stdout)["exhaustion"]
    assert plan(tmp_path, "--history", file, "--allow-repeat")["selected"]


@pytest.mark.parametrize("events", [None, ["bad"], [{"status": "reviewed"}], [{"status": "claimed"}]])
def test_malformed_history_is_not_silently_ignored(tmp_path, events):
    file = tmp_path / "history.json"
    file.write_text(json.dumps({"schema": "taskfilm-treatment-history/v1", "events": events}))
    result = invoke(tmp_path, "treatments", "--brief", "motion study", "--history", file)
    assert result.returncode == 2
    assert "history" in result.stderr


@pytest.mark.parametrize("treatment", ["type-sculpture", "orbit-story", "signal-field"])
@pytest.mark.parametrize("format,width,height", [("landscape", 1920, 1080), ("portrait", 1080, 1920)])
def test_every_treatment_authors_a_portable_project(tmp_path, treatment, format, width, height):
    destination = tmp_path / treatment
    result = invoke(tmp_path, "animate", destination, "--treatment", treatment, "--format", format,
                    "--headline", "One idea. Many directions.", "--silent")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    record = json.loads((destination / "ANIMATION-PLAN.json").read_text())
    assert report["rendered"] is False and record["history_updated"] is False
    assert record["config"]["treatment"] == treatment
    assert (record["config"]["width"], record["config"]["height"]) == (width, height)
    assert record["audio"] == "deliberate_silence"
    assert report["plan_sha256"] == hashlib.sha256((destination / "ANIMATION-PLAN.json").read_bytes()).hexdigest()
    for path in ("runtime.js", "assets/Manrope.ttf", "assets/Manrope-OFL.txt", "STORYBOARD.md", "NOTE.md", "hyperframes.json"):
        assert (destination / path).is_file()
    assert "hyperframes@0.8.134" in (destination / "package.json").read_text()
    assert 'data-composition-id="motion-study"' in (destination / "index.html").read_text()
    assert not (destination / "assets/mix.wav").exists()


def test_authoring_refuses_overwrite_and_html_injection(tmp_path):
    destination = tmp_path / "study"
    result = invoke(tmp_path, "animate", destination, "--headline", '</script><script>alert("x")</script>', "--silent")
    assert result.returncode == 0, result.stderr
    html = (destination / "index.html").read_text()
    assert '</script><script>alert("x")</script>' not in html
    assert "\\u003c/script" in html
    before = hashlib.sha256((destination / "index.html").read_bytes()).hexdigest()
    again = invoke(tmp_path, "animate", destination, "--silent")
    assert again.returncode == 2 and "new directory" in again.stderr
    assert hashlib.sha256((destination / "index.html").read_bytes()).hexdigest() == before


def test_brand_colors_stay_supplied_and_low_contrast_is_rejected(tmp_path):
    result = invoke(tmp_path, "animate", tmp_path / "custom", "--brand", "Fieldnotes",
                    "--ink", "#102120", "--paper", "#ffffff", "--accent", "#f47732", "--silent")
    assert result.returncode == 0, result.stderr
    record = json.loads((tmp_path / "custom/ANIMATION-PLAN.json").read_text())
    assert record["config"]["brand"] == "Fieldnotes"
    assert record["config"]["palette"] == {"ink": "#102120", "paper": "#ffffff", "accent": "#f47732"}
    rejected = invoke(tmp_path, "animate", tmp_path / "bad", "--ink", "#eeeeee", "--paper", "#ffffff", "--silent")
    assert rejected.returncode == 2 and "contrast" in rejected.stderr
    assert not (tmp_path / "bad").exists()


def test_original_score_has_a_discoverable_media_track_and_exact_duration(tmp_path):
    from html.parser import HTMLParser
    class Tracks(HTMLParser):
        def __init__(self):
            super().__init__()
            self.audio = []
        def handle_starttag(self, tag, attrs):
            if tag == 'audio':
                self.audio.append(dict(attrs))
    destination = tmp_path / 'scored'
    result = invoke(tmp_path, 'animate', destination, '--treatment', 'type-sculpture')
    assert result.returncode == 0, result.stderr
    parser = Tracks()
    parser.feed((destination / 'index.html').read_text())
    assert len(parser.audio) == 1 and parser.audio[0].get('id')
    assert parser.audio[0]['data-track-kind'] == 'audio'
    score = destination / parser.audio[0]['src']
    with wave.open(str(score)) as audio:
        assert audio.getnchannels() == 2 and audio.getframerate() == 48000
        assert audio.getnframes() / audio.getframerate() == 12
        assert len(set(audio.readframes(48000))) > 32
