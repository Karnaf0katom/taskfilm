"""Prepare source and original editable-demo downloads on the publication runner."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(inputs: Path, tag: str) -> dict:
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:a\d+|b\d+|rc\d+)?", tag):
        raise ValueError("use a Taskfilm release tag")
    root = Path(__file__).resolve().parents[1]
    source_manifest = json.loads((root / "SOURCE-MANIFEST.json").read_text())
    source_zip = inputs / f"taskfilm-source-{tag}.zip"
    with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for row in source_manifest["files"]:
            path = root / row["path"]
            if digest(path) != row["sha256"]:
                raise ValueError("source changed after the publication manifest")
            archive.write(path, f"taskfilm/{row['path']}")
        archive.write(root / "SOURCE-MANIFEST.json", "taskfilm/SOURCE-MANIFEST.json")
    original = inputs / "historical-demo-inputs.zip"
    projects_zip = inputs / f"taskfilm-demo-projects-{tag}.zip"
    preserved = []
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(
            projects_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        entries = source.infolist()
        if len(entries) > 1000 or sum(item.file_size for item in entries) > 128 * 1024 * 1024:
            raise ValueError("demo inputs exceed the expected bounded archive")
        if len({item.filename for item in entries}) != len(entries):
            raise ValueError("demo inputs contain duplicate archive entries")
        for item in entries:
            path = PurePosixPath(item.filename)
            kind = stat.S_IFMT(item.external_attr >> 16)
            if (path.is_absolute() or ".." in path.parts or "\\" in item.filename
                    or kind not in {0, stat.S_IFREG, stat.S_IFDIR}):
                raise ValueError("demo inputs contain an unsafe archive entry")
            if item.is_dir() or not path.parts or path.parts[0] != "jarvis-oss-editable":
                continue
            relative = PurePosixPath(*path.parts[1:])
            if (len(relative.parts) < 2 or relative.parts[0] not in {"excalidraw", "drawdb"}
                    or relative.parts[1] == "recipes"):
                continue
            if any(part in {"auth", "profiles", ".env", "node_modules", "__pycache__"}
                   for part in relative.parts):
                raise ValueError("private or generated demo input")
            data = source.read(item)
            archive.writestr(f"taskfilm-demo-projects/{relative}", data)
            preserved.append({"path": str(relative), "sha256": hashlib.sha256(data).hexdigest()})
        for app in ("excalidraw", "drawdb"):
            recipe = root / "src/taskfilm/examples/oss-showcases"
            for path in sorted(recipe.iterdir()):
                if path.is_file():
                    archive.write(path, f"taskfilm-demo-projects/{app}/recipes/{path.name}")
        for filename in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
            archive.write(root / filename, f"taskfilm-demo-projects/{filename}")
        archive.writestr("taskfilm-demo-projects/README.md", """# Taskfilm editable examples

These completed Excalidraw and drawDB films retain their original browser takes,
native results, editable HyperFrames projects and render evidence. The films
and their compositions predate the public rename and retain the earlier wordmark.
The recipes use the current Taskfilm CLI. No Penpot film is included.

With Taskfilm installed, Node.js 22+ and Chromium available, render an original
project with `taskfilm render excalidraw/editable --output excalidraw.mp4` or
`taskfilm render drawdb/editable --output drawdb.mp4`. Update the editable HTML
to change its copy or motion. The source takes and evidence remain unchanged.

drawDB includes original narration, WAV, model-predicted word timings and
Kokoro's Apache-2.0 provenance and notices. No model weights or account state
are included. Original code and sample content are MIT licensed; third-party
fonts, runtime dependencies and model notices retain their own terms.
""")
        archive.writestr("taskfilm-demo-projects/PRESERVED-FILES.json", json.dumps({
            "historical_input_sha256": digest(original), "files": preserved}, indent=2) + "\n")
    showcase_path = inputs / "showcase.json"
    showcase = json.loads(showcase_path.read_text())
    for path, label in ((source_zip, "Standalone source and recipes"),
                        (projects_zip, "Editable OSS films, takes and native results")):
        showcase["downloads"].append({"path": path.name, "sha256": digest(path), "label": label})
    showcase_path.write_text(json.dumps(showcase, indent=2) + "\n")
    checksums = inputs / "SHA256SUMS"
    files = [path for path in sorted(inputs.iterdir())
             if path.is_file() and path.name not in {"SHA256SUMS", "historical-demo-inputs.zip"}]
    checksums.write_text("".join(f"{digest(path)}  {path.name}\n" for path in files))
    return {"source": source_zip.name, "projects": projects_zip.name,
            "preserved_original_files": len(preserved)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.inputs, args.tag), indent=2))
