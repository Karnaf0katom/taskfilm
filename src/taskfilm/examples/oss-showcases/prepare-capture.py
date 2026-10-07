"""Bind an example's local upload files without changing the checked recipe.

The capture owner resolves relative seeds against its repository root. An
installed CLI has a different root, so the execution copy uses absolute paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def prepare(recipe: Path, output: Path) -> dict:
    recipe = recipe.resolve()
    data = json.loads(recipe.read_text())
    for seed in data.get("stage", {}).get("seed_files", []):
        path = Path(seed["path"])
        if not path.is_absolute():
            path = recipe.parent / path
        if path.is_symlink() or not path.is_file():
            raise ValueError("the upload seed must be a regular local file")
        path = path.resolve()
        name = seed.get("as") or path.name
        proof = next(step for step in data["steps"] if step.get("do") == "upload" and step["seed"] == name)
        if path.stat().st_size != proof["expected_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != proof["expected_sha256"]:
            raise ValueError("the upload seed differs from the recipe's checked bytes")
        seed["path"] = str(path)
    with output.open("x") as stream:
        stream.write(json.dumps(data, indent=2) + "\n")
    return {"execution_recipe": str(output.resolve()),
            "template_sha256": hashlib.sha256(recipe.read_bytes()).hexdigest(),
            "execution_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.recipe, args.out), indent=2))
