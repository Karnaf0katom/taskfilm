"""Portable, offline choice of original, authorable motion treatments.

Director owns the choice; HyperFrames owns authoring and rendering. Selection
never calls a model, renders a movie, or adds a delivered-history event.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "taskfilm-treatments/v1"
HISTORY_SCHEMA = "taskfilm-treatment-history/v1"
STRUCTURE = ("visual_family", "story_device", "opening", "camera_pattern",
             "transition_pattern", "layout", "sound_pacing", "ending")
SOURCE = {"creator": "Tejas Makwana", "repository": "https://github.com/Tejashmakwana/motionmaxxing",
          "commit": "8c8ec0f2a6f6c9a0da15cd24f7b1298ab298368c",
          "use": "craft reference; original Taskfilm recipes, no source films or runtime copied"}
CATALOG = (
    {"id": "type-sculpture", "name": "Type sculpture",
     "visual_family": "kinetic_type", "story_device": "words become physical objects",
     "opening": "oversized word landing", "camera_pattern": "frontal then rotating close-up",
     "transition_pattern": "mask cut and typographic wipe", "layout": "full-frame type",
     "sound_pacing": "percussive half-second grid", "ending": "type resolves to wordmark",
     "keywords": ["type", "words", "message", "headline", "launch", "bold"],
     "concept": "Give the headline weight: whole words land, rotate and become the wipe into the next thought.",
     "scene_roles": ["statement", "type-as-object", "reframing", "signature"]},
    {"id": "orbit-story", "name": "Orbit story",
     "visual_family": "spatial_diagram", "story_device": "one idea gathers a world",
     "opening": "single illuminated sphere", "camera_pattern": "orbital perspective journey",
     "transition_pattern": "match on sphere and iris", "layout": "depth-sorted central object",
     "sound_pacing": "slower six-tenths grid", "ending": "world contracts to signature",
     "keywords": ["connect", "system", "space", "idea", "workflow", "journey"],
     "concept": "Follow one illuminated idea through an orbital system; the world assembles around it.",
     "scene_roles": ["origin", "gathering", "convergence", "signature"]},
    {"id": "signal-field", "name": "Signal field",
     "visual_family": "generative_art", "story_device": "a signal finds its rhythm",
     "opening": "travelling ribbon field", "camera_pattern": "field to knot to wide reveal",
     "transition_pattern": "continuous deformation and aperture", "layout": "procedural line sculpture",
     "sound_pacing": "four-tenths rhythmic grid", "ending": "signal opens the signature",
     "keywords": ["rhythm", "signal", "music", "flow", "data", "creative", "motion"],
     "concept": "Turn an evolving wave into a rotating line sculpture and then a clear message.",
     "scene_roles": ["signal", "sculpture", "resolution", "signature"]},
)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def fingerprint(row: dict) -> dict:
    return {key: row[key] for key in STRUCTURE}


def validate_history(history: dict | None) -> list[dict]:
    if history is None:
        return []
    if not isinstance(history, dict) or history.get("schema") != HISTORY_SCHEMA:
        raise ValueError(f"history must use {HISTORY_SCHEMA}")
    rows = history.get("events")
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("history.events must contain at most 200 events")
    reviewed = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status") not in {"planned", "failed", "reviewed"}:
            raise ValueError("each history event needs status planned, failed or reviewed")
        if row["status"] != "reviewed":
            continue
        if not isinstance(row.get("treatment_id"), str) or not row["treatment_id"]:
            raise ValueError("reviewed history needs treatment_id")
        if not isinstance(row.get("movie_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["movie_sha256"]):
            raise ValueError("reviewed history needs the actual movie_sha256")
        shape = row.get("fingerprint")
        if not isinstance(shape, dict) or set(shape) != set(STRUCTURE) or any(
                not isinstance(value, str) or not value for value in shape.values()):
            raise ValueError("reviewed history needs a complete structural fingerprint")
        reviewed.append(row)
    # Landscape and portrait deliveries of one plan count once, even if both
    # movie hashes were retained. Most recent occurrence owns its position.
    unique, seen = [], set()
    for row in reversed(reviewed):
        key = (row["treatment_id"], digest(row["fingerprint"]))
        if key not in seen:
            unique.append(row)
            seen.add(key)
    return list(reversed(unique[:5]))


def select(brief: str, *, format: str = "landscape", seed: int = 41,
           history: dict | None = None, treatment: str | None = None,
           allow_repeat: bool = False) -> dict:
    if not isinstance(brief, str) or not brief.strip() or len(brief) > 2000:
        raise ValueError("brief must contain 1–2000 characters")
    if format not in {"landscape", "portrait"}:
        raise ValueError("format must be landscape or portrait")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer between 0 and 4294967295")
    if treatment is not None and treatment not in {row["id"] for row in CATALOG}:
        raise ValueError("unknown treatment; choose type-sculpture, orbit-story or signal-field")
    recent = validate_history(history)
    text = set(re.findall(r"\w+", brief.casefold()))
    candidates, excluded = [], []
    for source in CATALOG:
        row = copy.deepcopy(source)
        shape = fingerprint(row)
        changes = min((sum(shape[k] != event["fingerprint"][k] for k in STRUCTURE)
                       for event in recent), default=len(STRUCTURE))
        repeated = any(shape == event["fingerprint"] for event in recent)
        if repeated and not allow_repeat:
            excluded.append({"id": row["id"], "reason": "same structure in the last five reviewed treatments"})
            continue
        if treatment and row["id"] != treatment:
            continue
        matches = sorted(text.intersection(row.pop("keywords")))
        row.update(fingerprint=shape, structural_changes=changes,
                   fit_keywords=matches, support="authorable",
                   author_entry="hyperframes-lane/motion-studies/build.py",
                   render_command="taskfilm render PROJECT --output FILM.mp4",
                   formats=["landscape", "portrait"],
                   reason="Fits text-led original motion; " + ("matches " + ", ".join(matches) if matches
                          else "no more specific keyword preference") + f"; {changes} structural dimensions differ from recent work.")
        row["_order"] = (-len(matches), digest({"seed": seed, "id": row["id"]}))
        candidates.append(row)
    candidates.sort(key=lambda row: row["_order"])
    for row in candidates:
        row.pop("_order")
    return {"schema": SCHEMA, "phase": "preproduction", "brief": brief.strip(),
            "format": format, "seed": seed, "selected": candidates[0]["id"] if candidates else None,
            "candidates": candidates, "excluded": excluded,
            "catalog_sha256": digest(CATALOG), "history_sha256": digest(history),
            "allow_repeat": allow_repeat, "source": SOURCE,
            "scope": "Original text/geometry animation; no captured product action or generated footage is implied.",
            "history_update": "none; append only after encoded and visual review",
            "exhaustion": None if candidates else "No unused compatible treatment. Supply shorter history or explicitly allow a repeat."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", required=True)
    parser.add_argument("--format", choices=("landscape", "portrait"), default="landscape")
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--treatment", choices=[row["id"] for row in CATALOG])
    parser.add_argument("--allow-repeat", action="store_true", help="intentional series reuse")
    parser.add_argument("--out", type=Path, help="optional new JSON file; never modifies history")
    args = parser.parse_args(argv)
    try:
        history = json.loads(args.history.read_text()) if args.history else None
        result = select(args.brief, format=args.format, seed=args.seed, history=history,
                        treatment=args.treatment, allow_repeat=args.allow_repeat)
        content = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            with args.out.open("x", encoding="utf-8") as handle:
                handle.write(content)
        print(content, end="")
        return 0 if result["selected"] else 3
    except (ValueError, OSError) as exc:
        parser.exit(2, f"treatments: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
