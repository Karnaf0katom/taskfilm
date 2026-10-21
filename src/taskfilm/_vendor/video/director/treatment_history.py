"""Record a caller's explicit review acknowledgement, never infer human review."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time

from creative_treatments import CATALOG, HISTORY_SCHEMA, SCHEMA, fingerprint, validate_history

try:
    import fcntl
except ImportError:  # Allow help/import on platforms without POSIX file locking.
    fcntl = None


def _hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _shape(treatment: object, shape: object) -> dict:
    row = next((row for row in CATALOG if row["id"] == treatment), None)
    if row is None:
        raise ValueError("unknown treatment (showreels cannot be recorded as one treatment)")
    expected = fingerprint(row)
    if shape != expected:
        raise ValueError("treatment fingerprint contradicts the treatment catalog")
    return expected


def _plan(raw: bytes) -> tuple[str, dict]:
    plan = json.loads(raw)
    if not isinstance(plan, dict) or plan.get("schema") != "taskfilm-animation/v1":
        raise ValueError("project needs an actual taskfilm-animation/v1 ANIMATION-PLAN.json")
    config, selection = plan.get("config"), plan.get("selection")
    if not isinstance(config, dict) or not isinstance(selection, dict) or selection.get("schema") != SCHEMA:
        raise ValueError("animation plan needs config and treatment selection")
    treatment = config.get("treatment")
    if treatment not in {row["id"] for row in CATALOG}:
        raise ValueError("unknown treatment (showreels cannot be recorded as one treatment)")
    if selection.get("selected") != treatment:
        raise ValueError("animation config contradicts selected treatment")
    candidates = selection.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("animation selection needs candidates")
    selected = [row for row in candidates if isinstance(row, dict) and row.get("id") == treatment]
    if len(selected) != 1:
        raise ValueError("animation selection needs exactly one selected candidate")
    shape = _shape(treatment, selected[0].get("fingerprint"))
    # Reject contradictory structure fields as well as the supplied fingerprint.
    if fingerprint(selected[0]) != shape:
        raise ValueError("candidate structure contradicts its fingerprint")
    return treatment, shape


def _probe(movie: Path) -> dict:
    if not movie.is_file() or movie.stat().st_size == 0:
        raise ValueError("movie must be a nonempty video file")
    try:
        probe = subprocess.run(["ffprobe", "-v", "error", "-threads", "1", "-select_streams", "v:0",
                                "-show_entries", "stream=codec_type,width,height,duration:format=duration",
                                "-of", "json", str(movie)], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"ffprobe could not validate movie: {exc}") from exc
    if probe.returncode:
        raise ValueError("ffprobe rejected movie")
    try:
        report = json.loads(probe.stdout)
        stream = report["streams"][0]
        duration = float(stream.get("duration") or report["format"]["duration"])
        if stream.get("codec_type") != "video" or stream["width"] <= 0 or stream["height"] <= 0 or not math.isfinite(duration) or duration <= 0:
            raise ValueError("invalid video properties")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("movie must contain a video stream with positive dimensions and duration") from exc
    return {"width": stream["width"], "height": stream["height"], "duration_seconds": duration}


@contextmanager
def _lock(path: Path):
    # Keep the sidecar inode: deleting it after unlock would split concurrent locks.
    with path.open("a+b") as handle:
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError("history is busy; no update performed")
                time.sleep(.05)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def record_review(project: Path, *, movie: Path, history: Path, reviewer: str,
                  confirm_reviewed: bool = False) -> dict:
    if fcntl is None:
        raise ValueError("record-review requires POSIX file locking; this release is tested on Linux")
    if confirm_reviewed is not True:
        raise ValueError("--confirm-reviewed is required: technical checks cannot confirm a human watched")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 200 or any(ord(c) < 32 for c in reviewer):
        raise ValueError("reviewer must contain 1–200 printable characters")
    project, movie, history = Path(project).resolve(), Path(movie).resolve(), Path(history).absolute()
    if history.is_symlink():
        raise ValueError("history must not be a symlink")
    plan_path = project / "ANIMATION-PLAN.json"
    if history.resolve() in {movie, plan_path}:
        raise ValueError("history cannot overwrite the movie or animation plan")
    raw_plan = plan_path.read_bytes()
    try:
        treatment, shape = _plan(raw_plan)
    except KeyError as exc:
        raise ValueError("animation candidate needs a complete structural fingerprint") from exc
    movie_hash = _hash(movie)
    video = _probe(movie)
    if movie_hash != _hash(movie) or raw_plan != plan_path.read_bytes():
        raise ValueError("movie or plan changed during validation; no update performed")
    event = {"status": "reviewed", "treatment_id": treatment, "fingerprint": shape,
             "movie_sha256": movie_hash, "plan_sha256": hashlib.sha256(raw_plan).hexdigest(),
             "reviewer": reviewer.strip(), "reviewed_at": datetime.now(timezone.utc).isoformat(),
             "review_acknowledgement": "caller_confirmed_reviewed", "video": video}
    with _lock(history.with_name(history.name + ".lock")):
        if history.is_symlink():
            raise ValueError("history must not be a symlink")
        original = history.read_bytes() if history.exists() else None
        document = json.loads(original) if original is not None else {"schema": HISTORY_SCHEMA, "events": []}
        if not isinstance(document, dict):
            raise ValueError(f"history must use {HISTORY_SCHEMA}")
        validate_history(document)
        for row in document["events"]:
            if row.get("status") == "reviewed":
                _shape(row["treatment_id"], row["fingerprint"])
        for row in document["events"]:
            if row.get("status") == "reviewed":
                if row["movie_sha256"] == movie_hash:
                    if row["treatment_id"] != treatment or row["fingerprint"] != shape or row.get("plan_sha256", event["plan_sha256"]) != event["plan_sha256"]:
                        raise ValueError("same movie already recorded with contradictory plan or treatment")
                    return {"recorded": False, "reason": "movie already recorded", "event": row}
        document["events"].append(event)
        validate_history(document)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=history.parent,
                                             prefix="." + history.name + ".", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(document, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if (history.read_bytes() if history.exists() else None) != original:
                raise ValueError("history changed during update; no update performed")
            os.replace(temporary, history)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {"recorded": True, "history": str(history), "event": event}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--movie", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--confirm-reviewed", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(record_review(**vars(args)), indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"record-review: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
