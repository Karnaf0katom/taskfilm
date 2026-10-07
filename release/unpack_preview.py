"""Verify a release preview's SHA-256 and unpack regular, bounded site files."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile


def unpack(archive: Path, checksums: Path, output: Path) -> None:
    matches = []
    for line in checksums.read_text().splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and parts[1].lstrip(" *") == archive.name:
            matches.append(parts[0])
    if len(matches) != 1 or not re.fullmatch(r"[a-f0-9]{64}", matches[0]):
        raise ValueError("the preview needs one exact checksum entry")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != matches[0]:
        raise ValueError("the preview differs from its release checksum")
    if output.exists() or output.is_symlink():
        raise ValueError("the site destination must be a new directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle, tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        members = bundle.infolist()
        if len(members) > 1000 or sum(item.file_size for item in members) > 512 * 1024 * 1024:
            raise ValueError("the preview exceeds the bounded site size")
        names = set()
        for item in members:
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename or not path.parts:
                raise ValueError("the preview contains an escaping path")
            if str(path) in names:
                raise ValueError("the preview contains duplicate paths")
            names.add(str(path))
            kind = stat.S_IFMT(item.external_attr >> 16)
            if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError("the preview contains a link or special file")
        prefix = ""
        if "index.html" not in names:
            roots = {PurePosixPath(name).parts[0] for name in names}
            if len(roots) != 1:
                raise ValueError("the preview needs one unambiguous site root")
            prefix = next(iter(roots))
        index = prefix + "/index.html" if prefix else "index.html"
        entry = next((item for item in members if item.filename == index), None)
        if entry is None or entry.is_dir() or entry.file_size == 0:
            raise ValueError("the preview needs a nonempty index.html at its site root")
        # All entries were inspected before any extraction. ZipFile checks CRC
        # as the real release bytes are read, before the site becomes visible.
        bundle.extractall(temporary)
        (Path(temporary) / prefix).rename(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--checksums", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    unpack(args.archive, args.checksums, args.out)
    print(f"Verified static preview: {args.out}")
