#!/usr/bin/env python3
"""Verify the public source inventory before building a distribution."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def check_source(root: Path) -> dict:
    root = root.resolve()
    manifest_file = root / "SOURCE-MANIFEST.json"
    if manifest_file.is_symlink():
        raise ValueError("the source manifest must be a regular file")
    manifest = json.loads(manifest_file.read_text())
    rows = manifest["files"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("the source inventory must be nonempty")
    expected = {"SOURCE-MANIFEST.json"}
    total_bytes = 0
    python_lines = 0
    for row in rows:
        name = row["path"]
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
                or path.as_posix() != name or name in expected):
            raise ValueError(f"unsafe or duplicate inventory path: {name}")
        file = root / name
        if file.is_symlink() or any(parent.is_symlink() for parent in file.parents if parent != root and root in parent.parents):
            raise ValueError(f"symlink in source inventory: {name}")
        if not file.is_file():
            raise ValueError(f"missing source file: {name}")
        data = file.read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError(f"source hash mismatch: {name}")
        if file.suffix == ".py":
            ast.parse(data, filename=name)
            python_lines += len(data.splitlines())
        expected.add(name)
        total_bytes += len(data)
    # Developer build/test residue is permitted after a build. It is never
    # included in the export, wheel or source distribution.
    ignored = {".git", ".venv", "build", "dist", "__pycache__", ".pytest_cache"}
    for file in root.rglob("*"):
        parts = file.relative_to(root).parts
        if any(part in ignored or part.endswith(".egg-info") for part in parts):
            continue
        if file.is_symlink():
            raise ValueError(f"symlink in source tree: {file.relative_to(root)}")
        if file.is_file() and file.relative_to(root).as_posix() not in expected:
            raise ValueError(f"unlisted source file: {file.relative_to(root)}")
    metadata = (root / "pyproject.toml").read_text()
    version = re.search(r'^version = "([^"]+)"$', metadata, re.MULTILINE)
    module = ast.parse((root / "src/taskfilm/__init__.py").read_text())
    versions = [ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)]
    if version is None or versions != [version[1]]:
        raise ValueError("package and CLI versions must match")
    return {"files": len(rows), "bytes": total_bytes, "python_lines": python_lines,
            "version": version[1], "source_hashes_verified": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(json.dumps(check_source(args.root), indent=2))
    except (ValueError, OSError, KeyError, TypeError, SyntaxError) as exc:
        parser.exit(2, f"taskfilm source: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
