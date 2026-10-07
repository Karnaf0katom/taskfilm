#!/usr/bin/env python3
"""Bind the original Taskfilm sample's planning claims to its actual pinned README.

Use a repo-pack made from the public Taskfilm release and the matching README
from that checkout. This prepares inputs; it does not verify runtime behaviour.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote


def prepare(pack_path: Path, readme: Path, destination: Path) -> None:
    if destination.exists():
        raise ValueError("output must be a new file")
    pack = json.loads(pack_path.read_text())
    url, commit = pack["repository_url"].removesuffix(".git").rstrip("/"), pack["resolved_commit"]
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url):
        raise ValueError("use the public Taskfilm GitHub repository URL")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("repo-pack must contain an immutable commit")
    data = readme.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    document = next((row for row in pack["documents"]
                     if row["path"] == "README.md" and row["sha256"] == digest), None)
    if document is None:
        raise ValueError("README bytes do not match the pinned repo-pack")
    if not all(term in data.decode("utf-8") for term in ("Taskfilm", "Taskboard", "local storage")):
        raise ValueError("this recipe is for Taskfilm's original Taskboard sample")
    reference = f"{url}/blob/{commit}/{quote(document['path'])}"
    request = json.loads((Path(__file__).parent / "request.json").read_text())
    request["request_id"] = "taskfilm-pinned-source-review"
    request["brief"] = "Show the original Taskfilm Taskboard sample and its pinned source, useful fit and limitation. Retain real capture evidence before rendering."
    request["claims"] = [
        {"id": "hook", "text": "The Taskfilm release includes an original local Taskboard sample"},
        {"id": "add-task", "text": "The sample lets you add a task"},
        {"id": "complete-task", "text": "The sample lets you complete a task and filter the result"},
        {"id": "fit", "text": "Try the sample locally without an account or API key"},
        {"id": "limitation", "text": "The sample uses browser local storage and has no shared backend"},
    ]
    for claim in request["claims"]:
        claim.update(approved=True, evidence_ref=reference)
    request["cta"] = {"type": "link", "label": "Get Taskfilm", "target": url}
    destination.write_text(json.dumps(request, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-pack", type=Path, required=True)
    parser.add_argument("--readme", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(args.repo_pack, args.readme, args.out)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, f"prepare OSS review: {exc}\n")


if __name__ == "__main__":
    main()
