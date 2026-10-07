#!/usr/bin/env python3
"""provenance — deterministic receipts for capture-lane proof artifacts.

A receipt binds one immutable source pack to every cut produced from it. It reads the source,
voice and caption files it names and fails closed when any of them is missing or unreadable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactSpec:
    aspect: str
    width: int
    height: int
    duration_s: float
    path: str = ""
    artifact_id: str = ""
    kind: str = ""
    role: str = ""


@dataclass(frozen=True)
class FileProof:
    path: str
    sha256: str


ASPECTS = {"16:9", "9:16"}
VOICE_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".opus")


def _canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def stable_digest(value) -> str:
    """A stable sha256 over a JSON-compatible value."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def receipt_json_bytes(receipt: dict) -> bytes:
    """The byte-identical form used for disk receipts and reproducibility checks."""
    return json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"


def write_receipt(receipt: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(receipt_json_bytes(receipt))


def hash_file(path: Path, recorded_path: str | None = None) -> FileProof:
    """Hash a file that must exist. Missing/unreadable files raise instead of best-effort receipts."""
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return FileProof(path=recorded_path or str(path), sha256=digest.hexdigest())


def _proofs(paths: list[Path] | tuple[Path, ...], group: str) -> list[dict]:
    return [asdict(hash_file(Path(path), f"{group}/{Path(path).name}")) for path in paths]


def _voice_paths_from_plan(plan: dict, vo_dir: Path) -> list[Path]:
    beats = [b for b in plan.get("beats", []) if (b.get("vo") or "").strip()]
    paths: list[Path] = []
    for beat in beats:
        beat_id = beat.get("id") or f"beat-{len(paths) + 1}"
        found = next((vo_dir / f"{beat_id}{ext}" for ext in VOICE_EXTS
                      if (vo_dir / f"{beat_id}{ext}").exists()), None)
        if found is None:
            raise FileNotFoundError(f"missing voice file for beat {beat_id!r} in {vo_dir}")
        paths.append(found)
    return paths


def action_spine(plan: dict) -> dict:
    """The stable beat/action body a receipt proves, with renderer-only fields left out."""
    return {
        "beats": plan.get("beats", []),
        "zooms": plan.get("zooms", []),
        "chapters": plan.get("chapters", []),
        "typing": plan.get("typing", []),
        "cuts": plan.get("cuts", []),
        "retime": plan.get("retime", []),
        "selected": plan.get("selected", []),
        "dropped": plan.get("dropped", []),
    }


def _artifact_record(spec: ArtifactSpec, take_id: str, sources: list[dict], voice: list[dict],
                     captions: dict, actions_sha: str) -> dict:
    if spec.aspect not in ASPECTS:
        raise ValueError(f"aspect must be one of {sorted(ASPECTS)}, got {spec.aspect!r}")
    if spec.width <= 0 or spec.height <= 0:
        raise ValueError("artifact width and height must be positive")
    if float(spec.duration_s) < 0:
        raise ValueError("artifact duration must be non-negative")
    if not spec.path:
        raise FileNotFoundError("artifact path is required")
    artifact_id = spec.artifact_id or spec.aspect
    artifact = asdict(hash_file(Path(spec.path), f"artifacts/{artifact_id}/{Path(spec.path).name}"))
    return {
        "artifact_id": artifact_id,
        "path": artifact["path"],
        "sha256": artifact["sha256"],
        "take_id": take_id,
        "kind": spec.kind or "unspecified",
        "role": spec.role or "unspecified",
        "rendered_deliverable": False,
        "dimensions_role": "target_intent",
        "target": {
            "aspect": spec.aspect,
            "width": int(spec.width),
            "height": int(spec.height),
        },
        # Legacy fields remain for existing consumers. ``dimensions_role`` and ``target`` make
        # explicit that these describe the intended render, not the intermediate file's pixels.
        "aspect": spec.aspect,
        "width": int(spec.width),
        "height": int(spec.height),
        "duration_s": float(spec.duration_s),
        "source": sources,
        "voice": voice,
        "captions": captions,
        "actions": {"sha256": actions_sha},
    }


def build_receipt(plan: dict, source_paths: list[Path] | tuple[Path, ...], caption_path: Path,
                  artifacts: list[ArtifactSpec], voice_paths: list[Path] | tuple[Path, ...] | None = None,
                  vo_dir: Path | None = None, silent: bool = False,
                  invocation_command: str | None = None, command: str | None = None) -> dict:
    """Build a deterministic receipt for every artifact cut from one source pack.

    ``source_paths`` and ``caption_path`` are always read and hashed. Voice can be passed explicitly
    with ``voice_paths`` or derived from narrated beats in ``plan`` and one-file-per-beat ``vo_dir``.
    Any missing or unreadable source, voice, caption or artifact raises before a receipt is returned.

    ``silent=True`` is the *declared* no-narration cut: a caption-led reel someone chose to ship
    without a read. It records ``narration_policy: "silent"`` so a viewer of the receipt can tell
    a deliberate silent delivery from a voiced one that lost its files — which is the whole reason
    the missing-voice raise above stays a raise.
    """
    if not artifacts:
        raise ValueError("at least one artifact is required")
    if not source_paths:
        raise ValueError("at least one source path is required")
    recorded_command = command if command is not None else invocation_command
    if recorded_command is None:
        recorded_command = "python reel.py"
    if not recorded_command.strip():
        raise ValueError("command is required")
    if silent:
        if voice_paths:
            raise ValueError("a silent receipt cannot carry voice files")
        voice_paths = ()
    elif voice_paths is None:
        if vo_dir is None:
            raise ValueError("voice_paths or vo_dir is required")
        voice_paths = _voice_paths_from_plan(plan, Path(vo_dir))
    sources = _proofs(tuple(Path(path) for path in source_paths), "source")
    voice = _proofs(tuple(Path(path) for path in voice_paths), "voice")
    captions = asdict(hash_file(Path(caption_path), f"captions/{Path(caption_path).name}"))
    actions_sha = stable_digest(action_spine(plan))
    take_id = stable_digest({
        "source": [item["sha256"] for item in sources],
        "actions": actions_sha,
    })
    return {
        "receipt_version": 1,
        "invocation_command": recorded_command,
        "narration_policy": "silent" if silent else "voiced",
        "take_id": take_id,
        "source_pack": sources,
        "actions": {"sha256": actions_sha},
        "artifacts": [
            _artifact_record(spec, take_id, sources, voice, captions, actions_sha)
            for spec in artifacts
        ],
    }


def _pinned_repository(value: Mapping) -> dict:
    if not isinstance(value, Mapping):
        raise ValueError("repository must be an object")
    url = value.get("url")
    commit = value.get("commit")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("repository.url is required")
    if not isinstance(commit, str) or len(commit) != 40 or any(
            ch not in "0123456789abcdef" for ch in commit):
        raise ValueError("repository.commit must be a 40-character lowercase SHA")
    extra = {key: value[key] for key in value if key not in {"url", "commit"}}
    if extra:
        raise ValueError("repository may only contain url and commit")
    return {"url": url.strip(), "commit": commit}


def _webrec_source_names(session: Mapping, take_dir: Path) -> list[str]:
    names = ["session.json"]
    streams = session.get("streams")
    if not isinstance(streams, Mapping):
        raise ValueError("webrec session.json is missing streams")
    for stream in streams.values():
        if not isinstance(stream, Mapping):
            continue
        path = stream.get("path")
        if isinstance(path, str) and path.strip():
            names.append(path.strip())
    if (take_dir / "plan.json").is_file():
        names.append("plan.json")
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name in seen or "/" in name or name.startswith(".") or name == "take-provenance.json":
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def assemble_webrec_take(take_dir: Path | str, *, repository: Mapping,
                          expected_page_errors: list | None = None) -> dict[str, bytes]:
    """Hash one retained webrec take into the capture-asset contract repo_narration already consumes.

    The producer is capture-lane's ``session.json`` plus the stream files it names.
    This does not invent termrec frames or a PTY take-manifest: it writes
    ``take-provenance.json`` with a ``sources`` inventory over the real bytes.

    ``expected_page_errors`` is an optional ``[{match, why}]`` waiver list (same
    contract as ``repo-lane/cohort.py``'s ``gate()``): a page error is tolerated only
    when its text contains a named ``match``, and only when the caller states ``why``.
    Silent tolerance is refused; an unmatched error still raises.
    """
    root = Path(take_dir)
    session_path = root / "session.json"
    if not session_path.is_file():
        raise FileNotFoundError(f"missing webrec session.json in {root}")
    session = json.loads(session_path.read_text(encoding="utf-8"))
    if not isinstance(session, Mapping):
        raise ValueError("webrec session.json must be an object")
    steps = session.get("steps") if isinstance(session.get("steps"), Mapping) else {}
    total, ok = steps.get("total"), steps.get("ok")
    if not isinstance(total, int) or not isinstance(ok, int) or total <= 0 or ok != total:
        raise ValueError("webrec take is incomplete")
    for err in session.get("page_errors") or []:
        rule = next((e for e in (expected_page_errors or [])
                     if isinstance(e, Mapping) and e.get("match") and e.get("why") and e["match"] in err), None)
        if rule is None:
            raise ValueError("webrec take recorded page errors")
    screen = session.get("streams", {}).get("screen") if isinstance(session.get("streams"), Mapping) else {}
    if not isinstance(screen, Mapping) or screen.get("status") != "ok" or not screen.get("path"):
        raise ValueError("webrec take has no retained screen")
    names = _webrec_source_names(session, root)
    if screen["path"] not in names:
        raise ValueError("webrec screen path is missing from the source inventory")
    proofs = []
    files: dict[str, bytes] = {}
    for name in names:
        path = root / name
        if not path.is_file() or path.is_symlink() or path.parent != root:
            raise FileNotFoundError(f"missing webrec source {name}")
        proof = hash_file(path, name)
        files[name] = path.read_bytes()
        proofs.append({"name": name, "sha256": proof.sha256, "bytes": len(files[name])})
    proofs.sort(key=lambda item: item["name"])
    session_id = session.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("webrec session_id is required")
    screen_sha = next(item["sha256"] for item in proofs if item["name"] == screen["path"])
    provenance = {
        "schema_version": 1,
        "run_id": session_id.strip(),
        "repository": _pinned_repository(repository),
        "capture_mode": "webrec",
        "rendered_deliverable": False,
        "profile": "reel",
        "sources": proofs,
        "take_id": stable_digest(proofs),
        "useful_output": {
            "steps_ok": ok,
            "steps_total": total,
            "duration_s": session.get("duration_s"),
            "screen_path": screen["path"],
            "screen_sha256": screen_sha,
        },
    }
    files["take-provenance.json"] = receipt_json_bytes(provenance)
    return files
