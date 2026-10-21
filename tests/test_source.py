"""Keep the public source small, complete and bound to its reviewed bytes."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("taskfilm_source_check", ROOT / "release/check_source.py")
CHECK = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CHECK)


def test_export_has_one_readme_and_one_copy_of_each_skill():
    manifest = json.loads((ROOT / "SOURCE-MANIFEST.json").read_text())
    paths = {row["path"] for row in manifest["files"]}
    assert len(paths) == len(manifest["files"])
    assert "README.md" in paths and "PUBLIC-README.md" not in paths
    assert not any(path.startswith("skills/") or path.startswith("src/taskfilm/skill/") for path in paths)
    for name in ("taskfilm-video", "taskfilm-feature-explainer"):
        assert f"src/taskfilm/skills/{name}/SKILL.md" in paths


def test_installed_story_dependencies_exclude_private_execution_engines():
    from taskfilm.cli import VIDEO

    # Courses export only their existing audio owners, with environment-only TTS.
    assert {path.name for path in (VIDEO / "edit-lane").glob("*.py")} == {
        "course_delivery.py", "course_narration.py", "tts_registry.py",
        "long_narration.py", "audio_stitch.py", "analyze.py",
    }
    assert not (VIDEO / "reel-lane/hook.py").exists()
    for path, unwanted in {
        "director/production_recipe.py": {"build_render_plan", "write_boundary_approval", "_dispatch"},
        "mix/build_mix.py": {"build_ops", "build_plan", "engine_spec", "main"},
        "reel-lane/formats.py": {"FORMATS", "FormatRegistryError"},
        "reel-lane/validate_reel_script.py": {"validate_reel_script", "_INTRO_RE"},
        "videokit/__init__.py": {"capabilities", "capability", "CAPABILITY_MAP"},
        "edit-lane/tts_registry.py": {"_secrets_pool", "_vertex_access_token", "_fishaudio_tts_fn"},
        "edit-lane/course_delivery.py": {"narrate"},
        "edit-lane/audio_stitch.py": {"loop_to", "pad_to", "_main"},
    }.items():
        tree = ast.parse((VIDEO / path).read_text())
        names = {item.name for item in tree.body if isinstance(item, (ast.ClassDef, ast.FunctionDef))}
        names.update(item.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                     for item in ast.walk(node) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store))
        assert not names & unwanted, path


@pytest.fixture
def source_fixture(tmp_path):
    files = {"pyproject.toml": b'version = "1.0.0"\n',
             "src/taskfilm/__init__.py": b'__version__ = "1.0.0"\n'}
    rows = []
    for name, data in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        rows.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    (tmp_path / "SOURCE-MANIFEST.json").write_text(json.dumps({"files": rows}))
    return tmp_path


def test_inventory_accepts_exact_source(source_fixture):
    assert CHECK.check_source(source_fixture)["source_hashes_verified"] is True


def test_inventory_rejects_changed_source(source_fixture):
    (source_fixture / "pyproject.toml").write_text('version = "2.0.0"\n')
    with pytest.raises(ValueError, match="source hash mismatch"):
        CHECK.check_source(source_fixture)


def test_inventory_rejects_an_unlisted_private_file(source_fixture):
    (source_fixture / ".env").write_text("example private state\n")
    with pytest.raises(ValueError, match="unlisted source file"):
        CHECK.check_source(source_fixture)


@pytest.mark.parametrize("name", ["../outside", "/outside", "./pyproject.toml", "src\\private"])
def test_inventory_rejects_escaping_or_noncanonical_paths(source_fixture, name):
    path = source_fixture / "SOURCE-MANIFEST.json"
    manifest = json.loads(path.read_text())
    manifest["files"][0]["path"] = name
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unsafe or duplicate"):
        CHECK.check_source(source_fixture)


def test_inventory_rejects_symlinked_source(source_fixture):
    path = source_fixture / "pyproject.toml"
    target = source_fixture / "private.toml"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        CHECK.check_source(source_fixture)
