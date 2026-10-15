"""Exercise the boundary between a downloaded release ZIP and the Pages site."""
import hashlib
import importlib.util
from pathlib import Path
import stat
import zipfile

import pytest

spec = importlib.util.spec_from_file_location(
    "taskfilm_preview_unpack", Path(__file__).parents[1] / "release/unpack_preview.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def archive(tmp_path, entries):
    path = tmp_path / "preview.zip"
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in entries:
            if isinstance(name, str):
                # ZipInfo's constructor normalizes backslashes on Windows.
                # Assign the raw member name after construction so the archive
                # exercises unpack's guard on every platform.
                member = zipfile.ZipInfo()
                member.filename = name
                name = member
            bundle.writestr(name, data)
    checksums = tmp_path / "DEMO-SHA256SUMS"
    checksums.write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "  preview.zip\n", encoding="utf-8")
    return path, checksums


@pytest.mark.parametrize("prefix", ["", "preview/"])
def test_checked_preview_has_one_site_root(tmp_path, prefix):
    path, checksums = archive(tmp_path, [(prefix + "index.html", "A local preview"),
                                       (prefix + "assets/movie.mp4", b"retained bytes")])
    output = tmp_path / "site"
    module.unpack(path, checksums, output)
    assert (output / "index.html").read_text(encoding="utf-8") == "A local preview"
    assert (output / "assets/movie.mp4").read_bytes() == b"retained bytes"


def test_changed_release_is_refused_before_extracting(tmp_path):
    path, checksums = archive(tmp_path, [("index.html", "Preview")])
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="differs"):
        module.unpack(path, checksums, tmp_path / "site")
    assert not (tmp_path / "site").exists()


@pytest.mark.parametrize("unsafe", ["../outside", "/outside", "assets\\outside"])
@pytest.mark.parametrize("normalize", [False, True], ids=["native", "windows-separators"])
def test_escaping_release_paths_are_refused(tmp_path, unsafe, normalize, monkeypatch):
    path, checksums = archive(tmp_path, [("index.html", "Preview"), (unsafe, "Unsafe")])
    if normalize:
        original_init = zipfile.ZipInfo.__init__

        def windows_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self.filename = self.filename.replace("\\", "/")

        monkeypatch.setattr(zipfile.ZipInfo, "__init__", windows_init)
    with zipfile.ZipFile(path) as bundle:
        assert unsafe in [member.orig_filename for member in bundle.infolist()]
    with pytest.raises(ValueError, match="escaping"):
        module.unpack(path, checksums, tmp_path / "site")
    assert not (tmp_path / "site").exists()


def test_release_cannot_install_a_symlink(tmp_path):
    link = zipfile.ZipInfo("assets/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    path, checksums = archive(tmp_path, [("index.html", "Preview"), (link, "../../outside")])
    with pytest.raises(ValueError, match="link or special"):
        module.unpack(path, checksums, tmp_path / "site")
    assert not (tmp_path / "site").exists()


def test_duplicate_release_paths_are_refused(tmp_path):
    with pytest.warns(UserWarning, match="Duplicate name"):
        path, checksums = archive(tmp_path, [("index.html", "One"), ("index.html", "Two")])
    with pytest.raises(ValueError, match="duplicate"):
        module.unpack(path, checksums, tmp_path / "site")
    assert not (tmp_path / "site").exists()
