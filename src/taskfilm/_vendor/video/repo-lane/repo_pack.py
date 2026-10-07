#!/usr/bin/env python3
"""Create a deterministic repository evidence pack for repo-lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

import secrets_policy


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
KNOWN_SPDX = {
    "MIT",
    "Apache-2.0",
    "GPL-3.0-only",
    "GPL-3.0",
}

INVENTORY_SCHEMA_VERSION = 1
DEFAULT_INVENTORY_MAX_ENTRIES = 256

# The inventory is intentionally a small intake artifact, not a source archive.
# Root entries provide useful layout context; these signals make nested projects
# visible without walking and hashing every file in a large monorepo.
MANIFEST_FILENAMES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "cargo.toml",
        "go.mod",
        "gemfile",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "composer.json",
    }
)
LOCKFILE_FILENAMES = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "uv.lock",
        "poetry.lock",
        "cargo.lock",
        "go.sum",
        "gemfile.lock",
        "composer.lock",
        "gradle.lockfile",
    }
)
OTHER_SIGNAL_FILENAMES = frozenset({"dockerfile", "makefile"})
INVENTORY_SIGNAL_FILENAMES = MANIFEST_FILENAMES | LOCKFILE_FILENAMES | OTHER_SIGNAL_FILENAMES
EXCLUDED_INVENTORY_DIRECTORIES = frozenset(
    {
        ".git",
        ".cache",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "bower_components",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "vendor",
        "venv",
    }
)


# A local git command answers in milliseconds; a clone of a real repository does not.
# Measured 2026-09-06: BerriAI/litellm exceeded the old flat 60 s budget on the clone and
# stage 1 failed for every large repository. Network work gets its own budget, and history
# blobs stay on the server unless the checkout actually needs them.
LOCAL_GIT_TIMEOUT_SECONDS = 60
NETWORK_GIT_TIMEOUT_SECONDS = int(os.environ.get("REPO_PACK_GIT_TIMEOUT", "900"))
BLOBLESS_FILTER = "--filter=blob:none"


def run_git(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = LOCAL_GIT_TIMEOUT_SECONDS,
) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def _safe_intake_text(value: object, label: str) -> str:
    """Refuse credential-shaped intake data before it can reach Git or a pack."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    secrets_policy.require_safe_text(value, label)
    return value


def ls_remote(url: str, kind: str, ref: str) -> list[tuple[str, str]]:
    url = _safe_intake_text(url, "repository_url")
    output = run_git(["ls-remote", kind, url, ref], timeout=NETWORK_GIT_TIMEOUT_SECONDS)
    rows: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        sha, name = line.split("\t", 1)
        rows.append((sha, name))
    return rows


def resolve_ref(url: str, ref: str, allow_branch: bool) -> tuple[str, str | None]:
    url = _safe_intake_text(url, "repository_url")
    ref = _safe_intake_text(ref, "requested_ref")
    if ref == "HEAD":
        output = run_git(["ls-remote", url, "HEAD"], timeout=NETWORK_GIT_TIMEOUT_SECONDS)
        rows = []
        for line in output.splitlines():
            if not line.strip():
                continue
            sha, name = line.split("\t", 1)
            if name == "HEAD":
                rows.append(sha)
        if rows and not allow_branch:
            raise SystemExit("Ref 'HEAD' is a moving branch; rerun with --allow-branch to pin its current SHA")
        if not rows:
            raise SystemExit("Could not resolve 'HEAD' to an immutable commit SHA")
        commit = rows[0]
        if not SHA_RE.fullmatch(commit):
            raise SystemExit("Could not resolve 'HEAD' to an immutable commit SHA")
        return commit, None

    branch_rows = ls_remote(url, "--heads", ref)
    if branch_rows and not allow_branch:
        raise SystemExit(f"Ref {ref!r} is a moving branch; rerun with --allow-branch to pin its current SHA")

    tag_rows = ls_remote(url, "--tags", ref)
    tag = None
    if any(name == f"refs/tags/{ref}" for _, name in tag_rows):
        tag = ref

    with tempfile.TemporaryDirectory(prefix="repo-pack-") as tmp:
        clone_dir = Path(tmp) / "repo"
        clone_without_worktree(url, clone_dir)
        if branch_rows:
            commit = branch_rows[0][0]
        else:
            commit = run_git(["rev-parse", f"{ref}^{{commit}}"], cwd=clone_dir)
        if not SHA_RE.fullmatch(commit):
            raise SystemExit(f"Could not resolve {ref!r} to an immutable commit SHA")
        return commit, tag


def clone_without_worktree(url: str, target: Path) -> None:
    """Clone refs and trees only, leaving history blobs on the server when the remote allows it.

    A blobless clone is an optimisation, never a requirement: a server that refuses the filter
    falls back to a full clone rather than failing the pin.
    """
    try:
        run_git(
            ["clone", "-q", "--no-checkout", BLOBLESS_FILTER, url, str(target)],
            timeout=NETWORK_GIT_TIMEOUT_SECONDS,
        )
        return
    except SystemExit:
        shutil.rmtree(target, ignore_errors=True)
    run_git(
        ["clone", "-q", "--no-checkout", url, str(target)],
        timeout=NETWORK_GIT_TIMEOUT_SECONDS,
    )


def checkout_repo(url: str, commit: str, target: Path) -> None:
    url = _safe_intake_text(url, "repository_url")
    clone_without_worktree(url, target)
    # Under a blobless clone this materialisation is the fetch, so it gets the network budget.
    run_git(
        ["checkout", "-q", "--detach", commit],
        cwd=target,
        timeout=NETWORK_GIT_TIMEOUT_SECONDS,
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _is_checkout_file(path: Path) -> bool:
    """True only for a regular checkout file, never a repository-controlled link."""
    return not path.is_symlink() and path.is_file()


def detect_license_text(text: str) -> str | None:
    lowered = text.lower()
    if "mit license" in lowered and "permission is hereby granted" in lowered:
        return "MIT"
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    if "gnu general public license" in lowered and "version 3" in lowered:
        return "GPL-3.0-only"
    return None


def license_from_pyproject(path: Path) -> str | None:
    text = read_text(path)
    match = re.search(r'^\s*license\s*=\s*["\']([^"\']+)["\']\s*$', text, re.MULTILINE)
    if match:
        return normalize_spdx(match.group(1))
    return None


def license_from_package(path: Path) -> str | None:
    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError:
        return None
    value = data.get("license")
    if isinstance(value, str):
        return normalize_spdx(value)
    return None


def normalize_spdx(value: str) -> str | None:
    cleaned = value.strip()
    if cleaned == "GPL-3.0":
        return "GPL-3.0-only"
    if cleaned in KNOWN_SPDX:
        return cleaned
    return None


def detect_license(repo: Path) -> str:
    evidence: set[str] = set()
    for child in sorted(repo.iterdir(), key=lambda p: p.name.lower()):
        if _is_checkout_file(child) and child.name.lower().startswith("license"):
            detected = detect_license_text(read_text(child))
            if detected:
                evidence.add(detected)
    pyproject = repo / "pyproject.toml"
    if _is_checkout_file(pyproject):
        detected = license_from_pyproject(pyproject)
        if detected:
            evidence.add(detected)
    package = repo / "package.json"
    if _is_checkout_file(package):
        detected = license_from_package(package)
        if detected:
            evidence.add(detected)
    if len(evidence) == 1:
        return next(iter(evidence))
    return "UNKNOWN"


def iter_document_paths(repo: Path) -> list[Path]:
    readmes: list[Path] = []
    docs_paths: list[Path] = []
    for child in repo.iterdir():
        if _is_checkout_file(child) and child.name.lower().startswith("readme"):
            readmes.append(child)
    docs = repo / "docs"
    if not docs.is_symlink() and docs.is_dir():
        for path in docs.rglob("*"):
            if _is_checkout_file(path):
                docs_paths.append(path)
    return sorted(readmes, key=lambda p: p.relative_to(repo).as_posix().lower()) + sorted(
        docs_paths,
        key=lambda p: p.relative_to(repo).as_posix().lower(),
    )


def collect_documents(repo: Path) -> list[dict[str, str]]:
    return [
        {"path": path.relative_to(repo).as_posix(), "sha256": file_sha256(path)}
        for path in iter_document_paths(repo)
    ]


def _path_sort_key(path: Path, repo: Path) -> tuple[str, str]:
    relative = path.relative_to(repo).as_posix()
    return relative.casefold(), relative


def _is_inventory_signal(path: Path) -> bool:
    return path.name.casefold() in INVENTORY_SIGNAL_FILENAMES


def _iter_inventory_signals(repo: Path) -> list[Path]:
    """Return included manifest/lockfile-style files without following links.

    A repository may contain arbitrary symlinks.  Intake must never follow one
    merely to compute a convenience hash, and vendored dependency trees must
    not make a repository appear to contain hundreds of subprojects.
    """

    signals: list[Path] = []
    for root, directories, filenames in os.walk(repo, topdown=True, followlinks=False):
        base = Path(root)
        directories[:] = sorted(
            (
                directory
                for directory in directories
                if directory.casefold() not in EXCLUDED_INVENTORY_DIRECTORIES
                and not (base / directory).is_symlink()
            ),
            key=lambda name: (name.casefold(), name),
        )
        for filename in sorted(filenames, key=lambda name: (name.casefold(), name)):
            path = base / filename
            if path.is_symlink() or not path.is_file() or not _is_inventory_signal(path):
                continue
            signals.append(path)
    return sorted(signals, key=lambda path: _path_sort_key(path, repo))


def _iter_root_inventory_entries(repo: Path) -> list[Path]:
    entries: list[Path] = []
    for path in repo.iterdir():
        if path.is_symlink():
            continue
        if path.is_dir() and path.name.casefold() in EXCLUDED_INVENTORY_DIRECTORIES:
            continue
        if path.is_file() or path.is_dir():
            entries.append(path)
    return sorted(entries, key=lambda path: _path_sort_key(path, repo))


def _inventory_entry(path: Path, repo: Path) -> dict[str, object]:
    relative = path.relative_to(repo).as_posix()
    if path.is_dir():
        # Directories deliberately do not acquire a made-up content hash.
        return {"path": relative, "kind": "directory"}
    if path.is_file():
        return {
            "path": relative,
            "kind": "file",
            "size_bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        }
    raise ValueError(f"inventory path is neither a regular file nor a directory: {relative}")


def collect_inventory(repo: Path, *, max_entries: int = DEFAULT_INVENTORY_MAX_ENTRIES) -> dict[str, object]:
    """Collect a deterministic, bounded intake inventory for a pinned checkout.

    The ordered priority is deliberate: manifest and lockfile evidence comes
    first so the consumer can identify a small repository family before the
    bounded root-layout context.  If either class cannot fit, ``truncated`` is
    recorded and consumers must refuse to infer a recipe from the partial view.
    """

    if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
        raise ValueError("inventory max_entries must be a positive integer")

    signals = _iter_inventory_signals(repo)
    roots = _iter_root_inventory_entries(repo)
    selected_paths: dict[str, Path] = {}
    ordered_paths: list[Path] = []
    for path in [*signals, *roots]:
        relative = path.relative_to(repo).as_posix()
        if relative in selected_paths:
            continue
        selected_paths[relative] = path
        ordered_paths.append(path)

    # Selection is priority-ordered, while serialized entries remain canonical
    # for byte-stable packs and simple downstream validation.
    selected = sorted(ordered_paths[:max_entries], key=lambda path: _path_sort_key(path, repo))
    entries = [_inventory_entry(path, repo) for path in selected]
    entry_paths = {str(entry["path"]) for entry in entries}
    manifest_paths = [
        path.relative_to(repo).as_posix()
        for path in signals
        if path.name.casefold() in MANIFEST_FILENAMES
        and path.relative_to(repo).as_posix() in entry_paths
    ]
    lockfile_paths = [
        path.relative_to(repo).as_posix()
        for path in signals
        if path.name.casefold() in LOCKFILE_FILENAMES
        and path.relative_to(repo).as_posix() in entry_paths
    ]
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "entries": entries,
        # An empty list is meaningful: this checkout had no detected manifests,
        # rather than a producer that forgot to emit inventory data.
        "manifest_paths": manifest_paths,
        "lockfile_paths": lockfile_paths,
        "limits": {"max_entries": max_entries},
        "candidate_count": len(ordered_paths),
        "truncated": len(ordered_paths) > max_entries,
    }


def parse_supported_environments(repo: Path) -> list[str]:
    found: list[str] = []
    for path in iter_document_paths(repo):
        in_section = False
        for line in read_text(path).splitlines():
            if re.match(r"^#{1,6}\s+", line):
                title = re.sub(r"^#{1,6}\s+", "", line).strip().lower()
                in_section = title in {"supported environments", "supported environment", "environments"}
                continue
            if in_section:
                item = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
                if item:
                    value = item.group(1).strip()
                    if value and value not in found:
                        found.append(value)
                elif line.strip() and not line.startswith(" "):
                    in_section = False
    return found


def _normalise_requested_subdirectory(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("requested_subdirectory must be a string")
    path = value.replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    if path in {"", "."}:
        return ""
    if path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError("requested_subdirectory must be a relative repository path")
    secrets_policy.require_safe_text(path, "requested_subdirectory")
    return path


def _normalise_requested_manifest(value: object) -> str:
    """Validate the manifest an operator selected as THE project of a checkout.

    A subdirectory cannot name every project: a repository root that carries both a
    Python and a Node manifest (litellm) is only answerable by naming one of them.
    The value must still be an existing manifest path in the pinned checkout, which
    the recipe consumer checks against the inventory; intake only proves its shape.
    """

    if not isinstance(value, str):
        raise ValueError("requested_manifest must be a string")
    path = value.replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    if path in {"", "."}:
        return ""
    if path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError("requested_manifest must be a relative repository path")
    if path.rsplit("/", 1)[-1].casefold() not in MANIFEST_FILENAMES:
        raise ValueError("requested_manifest must name a manifest file")
    secrets_policy.require_safe_text(path, "requested_manifest")
    return path


def normalise_intake_context(intake_context: Mapping[str, object] | None) -> dict[str, object] | None:
    """Keep operator routing context alongside the immutable repository pack.

    The selected subdirectory or manifest is data, not an inference from a monorepo.
    That lets a caller intentionally choose one project while an unspecified
    multi-project checkout remains ambiguous in the recipe consumer.
    """

    if intake_context is None:
        return None
    if not isinstance(intake_context, Mapping):
        raise ValueError("intake_context must be a mapping")
    notes = intake_context.get("operator_notes", [])
    if isinstance(notes, str):
        notes = [notes]
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        raise ValueError("operator_notes must be a string or a list of strings")
    for index, note in enumerate(notes):
        secrets_policy.require_safe_text(note, f"operator_notes[{index}]")
    context: dict[str, object] = {"operator_notes": list(notes)}
    if "requested_subdirectory" in intake_context:
        context["requested_subdirectory"] = _normalise_requested_subdirectory(
            intake_context["requested_subdirectory"]
        )
    if "requested_manifest" in intake_context:
        context["requested_manifest"] = _normalise_requested_manifest(
            intake_context["requested_manifest"]
        )
    return context


def build_pack(
    url: str,
    requested_ref: str,
    allow_branch: bool,
    *,
    inventory_max_entries: int = DEFAULT_INVENTORY_MAX_ENTRIES,
    intake_context: Mapping[str, object] | None = None,
) -> dict:
    url = _safe_intake_text(url, "repository_url")
    requested_ref = _safe_intake_text(requested_ref, "requested_ref")
    commit, tag = resolve_ref(url, requested_ref, allow_branch)
    normalized_context = normalise_intake_context(intake_context)
    with tempfile.TemporaryDirectory(prefix="repo-pack-work-") as tmp:
        repo = Path(tmp) / "repo"
        checkout_repo(url, commit, repo)
        pack = {
            "repository_url": url,
            "requested_ref": requested_ref,
            "resolved_commit": commit,
            "tag": tag,
            "license_spdx": detect_license(repo),
            "documents": collect_documents(repo),
            "supported_environments": parse_supported_environments(repo),
            "trademark": {"status": "UNKNOWN", "notes": ""},
            "attribution": {"status": "UNKNOWN", "notes": ""},
            "rights_status": "UNKNOWN",
            "inventory": collect_inventory(repo, max_entries=inventory_max_entries),
        }
        if normalized_context is not None:
            pack["intake_context"] = normalized_context
        return pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write repo-pack.json for a pinned repository ref.")
    parser.add_argument("url")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--allow-branch", action="store_true")
    parser.add_argument(
        "--inventory-max-entries",
        type=int,
        default=DEFAULT_INVENTORY_MAX_ENTRIES,
        help="maximum root/signal entries included in the bounded repository inventory",
    )
    parser.add_argument(
        "--subdirectory",
        help="optional relative subproject selected by the operator for recipe detection",
    )
    parser.add_argument(
        "--manifest",
        help=(
            "optional relative manifest path selected by the operator as the project "
            "itself, for a root that carries more than one ecosystem"
        ),
    )
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        dest="operator_notes",
        help="operator note retained with the intake context (repeatable)",
    )
    args = parser.parse_args(argv)

    intake_context: dict[str, object] | None = None
    if args.subdirectory is not None or args.manifest is not None or args.operator_notes:
        intake_context = {"operator_notes": args.operator_notes}
        if args.subdirectory is not None:
            intake_context["requested_subdirectory"] = args.subdirectory
        if args.manifest is not None:
            intake_context["requested_manifest"] = args.manifest
    pack = build_pack(
        args.url,
        args.ref,
        args.allow_branch,
        inventory_max_entries=args.inventory_max_entries,
        intake_context=intake_context,
    )
    output = Path("repo-pack.json")
    output.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
