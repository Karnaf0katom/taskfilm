"""Review acknowledgement and real video validation; no claim of human observation."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

director = Path(__file__).resolve().parents[2] / "director"
if not director.is_dir():
    spec = importlib.util.find_spec("taskfilm")
    assert spec is not None and spec.origin is not None, "install taskfilm before running exported tests"
    director = Path(spec.origin).parent / "_vendor/video/director"
sys.path.insert(0, str(director))
from creative_treatments import HISTORY_SCHEMA, select
from treatment_history import main, record_review
import treatment_history


@pytest.fixture
def fixture(tmp_path):
    choice = select("A bold headline launch", seed=9)
    project = tmp_path / "project"
    project.mkdir()
    plan = {"schema": "taskfilm-animation/v1", "config": {"treatment": choice["selected"]}, "selection": choice}
    (project / "ANIMATION-PLAN.json").write_text(json.dumps(plan))
    movie = tmp_path / "original.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                    "color=c=0x164b52:s=64x48:r=10:d=0.3", "-threads", "1",
                    "-filter_threads", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(movie)],
                   check=True, capture_output=True, timeout=20)
    return project, movie, tmp_path / "history.json", plan


def record(fixture, **options):
    project, movie, history, _ = fixture
    return record_review(project, movie=movie, history=history, reviewer="Test Reviewer",
                         **{"confirm_reviewed": True, **options})


def test_actual_hashes_selector_avoidance_and_byte_idempotence(fixture):
    project, movie, history, plan = fixture
    result = record(fixture)
    assert result["recorded"] is True
    event = result["event"]
    assert event["movie_sha256"] == hashlib.sha256(movie.read_bytes()).hexdigest()
    assert event["plan_sha256"] == hashlib.sha256((project / "ANIMATION-PLAN.json").read_bytes()).hexdigest()
    assert event["reviewer"] == "Test Reviewer"
    assert event["review_acknowledgement"] == "caller_confirmed_reviewed"
    assert event["video"]["width"] == 64
    before = history.read_bytes()
    assert select("A bold headline launch", seed=9, history=json.loads(before))["selected"] != plan["config"]["treatment"]
    assert record(fixture)["recorded"] is False
    assert history.read_bytes() == before


@pytest.mark.parametrize("change", ["ack", "reviewer", "empty", "invalid", "missing", "plan-schema", "unknown", "showreel", "selected", "fingerprint", "structure"])
def test_refusals_preserve_history(fixture, change):
    project, movie, history, plan = fixture
    history.write_text(json.dumps({"schema": HISTORY_SCHEMA, "events": [{"status": "planned"}]}))
    before = history.read_bytes()
    options = {}
    if change == "ack":
        options["confirm_reviewed"] = False
    elif change == "reviewer":
        with pytest.raises(ValueError, match="reviewer"):
            record_review(project, movie=movie, history=history, reviewer=" ", confirm_reviewed=True)
        assert history.read_bytes() == before
        return
    elif change == "empty":
        movie.write_bytes(b"")
    elif change == "invalid":
        movie.write_bytes(b"not a movie")
    elif change == "missing":
        movie.unlink()
    else:
        if change == "plan-schema":
            plan["schema"] = "other"
        elif change in {"unknown", "showreel"}:
            plan["config"]["treatment"] = change
            plan["selection"]["selected"] = change
        elif change == "selected":
            plan["selection"]["selected"] = "orbit-story"
        elif change == "fingerprint":
            plan["selection"]["candidates"][0]["fingerprint"]["opening"] = "wrong"
        elif change == "structure":
            plan["selection"]["candidates"][0]["opening"] = "wrong"
        (project / "ANIMATION-PLAN.json").write_text(json.dumps(plan))
    with pytest.raises((ValueError, OSError)):
        record(fixture, **options)
    assert history.read_bytes() == before


@pytest.mark.parametrize("raw", [b"{oops", b'[]', b'null', b'{"schema":"wrong","events":[]}',
                                 b'{"schema":"taskfilm-treatment-history/v1","events":[{"status":"reviewed"}]}'])
def test_malformed_history_is_preserved(fixture, raw):
    history = fixture[2]
    history.write_bytes(raw)
    with pytest.raises(ValueError):
        record(fixture)
    assert history.read_bytes() == raw


def test_concurrent_duplicate_record_has_one_event(fixture):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: record(fixture), range(2)))
    assert sorted(result["recorded"] for result in results) == [False, True]
    assert len(json.loads(fixture[2].read_text())["events"]) == 1


def test_concurrent_distinct_movies_preserve_prior_events(fixture):
    project, movie, history, _ = fixture
    other = movie.with_name("other.mp4")
    # An MP4 permits trailing padding; both files still contain the same valid
    # original video stream, but have distinct byte identities.
    other.write_bytes(movie.read_bytes() + b"\0" * 16)
    history.write_text(json.dumps({"schema": HISTORY_SCHEMA, "events": [{"status": "planned", "note": "keep"}]}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda path: record_review(project, movie=path, history=history,
                                  reviewer="Test Reviewer", confirm_reviewed=True), [movie, other]))
    assert all(result["recorded"] for result in results)
    events = json.loads(history.read_text())["events"]
    assert len(events) == 3 and events[0] == {"status": "planned", "note": "keep"}
    assert len({event["movie_sha256"] for event in events[1:]}) == 2


def test_cli_requires_ack_and_reports_record(fixture, capsys):
    project, movie, history, _ = fixture
    args = [str(project), "--movie", str(movie), "--history", str(history), "--reviewer", "Test Reviewer"]
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2 and not history.exists()
    assert main(args + ["--confirm-reviewed"]) == 0
    assert json.loads(capsys.readouterr().out)["recorded"] is True


def test_same_movie_with_different_plan_refused(fixture):
    project, _, history, plan = fixture
    record(fixture)
    before = history.read_bytes()
    plan["config"]["headline"] = "changed"
    (project / "ANIMATION-PLAN.json").write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="contradictory"):
        record(fixture)
    assert history.read_bytes() == before


def test_unknown_history_treatment_refused(fixture):
    record(fixture)
    history = fixture[2]
    document = json.loads(history.read_text())
    document["events"][0]["treatment_id"] = "unknown"
    history.write_text(json.dumps(document))
    before = history.read_bytes()
    with pytest.raises(ValueError, match="unknown"):
        record(fixture)
    assert history.read_bytes() == before


def test_unsupported_platform_fails_without_mutation(fixture, monkeypatch):
    monkeypatch.setattr(treatment_history, "fcntl", None)
    with pytest.raises(ValueError, match="POSIX"):
        record(fixture)
    assert not fixture[2].exists()
    assert not fixture[2].with_suffix(".json.lock").exists()


def test_full_history_refused_without_truncation(fixture):
    history = fixture[2]
    history.write_text(json.dumps({"schema": HISTORY_SCHEMA,
                                  "events": [{"status": "planned"}] * 200}))
    before = history.read_bytes()
    with pytest.raises(ValueError, match="200"):
        record(fixture)
    assert history.read_bytes() == before
