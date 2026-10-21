"""Brand contract checks against either the source owner or installed distribution."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


OWNER = Path(__file__).resolve().parents[2] / "hyperframes-lane/motion-studies/build.py"
if not OWNER.is_file():
    package = importlib.util.find_spec("taskfilm")
    if package is None or package.origin is None:
        raise ImportError("brand checks require the source tree or installed taskfilm")
    OWNER = Path(package.origin).parent / "_vendor/video/hyperframes-lane/motion-studies/build.py"
DEFAULTS = {"brand": "Taskfilm", "tagline": "Editable motion.",
            "palette": {"ink": "#142124", "paper": "#fff5e5", "accent": "#ff613d"}}
CUSTOM = {"schema": "taskfilm-brand/v1", "brand": "Northstar", "tagline": "Ideas in motion.",
          "palette": {"ink": "#102120", "paper": "#ffffff", "accent": "#F47732"}}


@pytest.fixture
def owner():
    spec = importlib.util.spec_from_file_location("brand_kit_owner", OWNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_brand(tmp_path, data):
    file = tmp_path / "brand.json"
    file.write_text(json.dumps(data), encoding="utf-8")
    return file


def read_plan(destination):
    return json.loads((destination / "ANIMATION-PLAN.json").read_text())


@pytest.mark.parametrize("format,size", [("landscape", (1920, 1080)), ("portrait", (1080, 1920))])
def test_supplied_brand_survives_both_formats(owner, tmp_path, format, size):
    file = write_brand(tmp_path, CUSTOM)
    raw = file.read_bytes()
    destination = tmp_path / format
    assert owner.main([str(destination), "--brand-file", str(file), "--format", format, "--silent"]) == 0
    plan = read_plan(destination)
    config = plan["config"]
    assert (config["width"], config["height"]) == size
    resolved = {key: config[key] for key in DEFAULTS}
    assert resolved == {key: CUSTOM[key] for key in DEFAULTS}
    assert plan["brand_file"] == {"schema": "taskfilm-brand/v1",
                                  "sha256": hashlib.sha256(raw).hexdigest(), "resolved": resolved}
    assert file.read_bytes() == raw
    html = (destination / "index.html").read_text()
    assert json.dumps(config, ensure_ascii=True) in html
    assert (destination / "runtime.js").read_bytes() == (OWNER.parent / "runtime.js").read_bytes()
    assert plan["audio"] == "deliberate_silence"


def test_explicit_flags_override_file_even_when_equal_original_defaults(owner, tmp_path):
    file = write_brand(tmp_path, CUSTOM)
    destination = tmp_path / "explicit"
    flags = ["--brand", "Taskfilm", "--tagline", "Editable motion.",
             "--ink", "#142124", "--paper", "#fff5e5", "--accent", "#ff613d"]
    assert owner.main([str(destination), "--brand-file", str(file), "--silent", *flags]) == 0
    plan = read_plan(destination)
    assert {key: plan["config"][key] for key in DEFAULTS} == DEFAULTS
    assert plan["brand_file"]["resolved"] == DEFAULTS


def test_direct_author_explicit_values_override_file(owner, tmp_path):
    destination = tmp_path / "direct"
    owner.author(destination, brand_file=write_brand(tmp_path, CUSTOM),
                 brand="Taskfilm", accent="#ff613d", audio=False)
    config = read_plan(destination)["config"]
    assert config["brand"] == "Taskfilm"
    assert config["tagline"] == CUSTOM["tagline"]
    assert config["palette"] == {**CUSTOM["palette"], "accent": "#ff613d"}


@pytest.mark.parametrize("data", [{"schema": "taskfilm-brand/v1"},
                                   {"schema": "taskfilm-brand/v1", "palette": {}},
                                   {"schema": "taskfilm-brand/v1", "palette": {"accent": "#abcdef"}}])
def test_omitted_file_fields_retain_defaults(owner, tmp_path, data):
    destination = tmp_path / "partial"
    owner.author(destination, brand_file=write_brand(tmp_path, data), audio=False)
    expected = {**DEFAULTS, "palette": {**DEFAULTS["palette"], **data.get("palette", {})}}
    assert {key: read_plan(destination)["config"][key] for key in DEFAULTS} == expected


@pytest.mark.parametrize("data,error", [
    ([], "object"), (None, "object"), ({}, "schema"),
    ({"schema": "taskfilm-brand/v2"}, "schema"),
    ({"schema": "taskfilm-brand/v1", "headline": "Oops"}, "unknown"),
    ({"schema": "taskfilm-brand/v1", "brand": 12}, "brand"),
    ({"schema": "taskfilm-brand/v1", "brand": None}, "brand"),
    ({"schema": "taskfilm-brand/v1", "brand": " "}, "brand"),
    ({"schema": "taskfilm-brand/v1", "brand": "x" * 25}, "brand"),
    ({"schema": "taskfilm-brand/v1", "tagline": ["bad"]}, "tagline"),
    ({"schema": "taskfilm-brand/v1", "tagline": "x" * 55}, "tagline"),
    ({"schema": "taskfilm-brand/v1", "tagline": "bad\ntext"}, "tagline"),
    ({"schema": "taskfilm-brand/v1", "palette": None}, "palette"),
    ({"schema": "taskfilm-brand/v1", "palette": []}, "palette"),
    ({"schema": "taskfilm-brand/v1", "palette": {"extra": "#123456"}}, "palette"),
    ({"schema": "taskfilm-brand/v1", "palette": {"ink": 123}}, "hex"),
    ({"schema": "taskfilm-brand/v1", "palette": {"accent": "red"}}, "hex"),
    ({"schema": "taskfilm-brand/v1", "palette": {"paper": "#fff"}}, "hex"),
    ({"schema": "taskfilm-brand/v1", "palette": {"ink": "#eeeeee", "paper": "#ffffff"}}, "contrast"),
])
def test_invalid_file_leaves_no_output_or_parent(owner, tmp_path, capsys, data, error):
    file = write_brand(tmp_path, data)
    destination = tmp_path / "new-parent" / "rejected"
    with pytest.raises(SystemExit) as exc:
        owner.main([str(destination), "--brand-file", str(file), "--silent"])
    assert exc.value.code == 2
    assert error in capsys.readouterr().err
    assert not destination.parent.exists()
    assert not list(tmp_path.glob(".taskfilm-animation-*"))


@pytest.mark.parametrize("raw", [b"{broken", b"\xff", b'{"schema":"taskfilm-brand/v1"}'.decode().encode("utf-16")])
def test_bad_json_or_encoding_is_rejected(owner, tmp_path, capsys, raw):
    file = tmp_path / "brand.json"
    file.write_bytes(raw)
    destination = tmp_path / "missing-parent" / "project"
    with pytest.raises(SystemExit) as exc:
        owner.main([str(destination), "--brand-file", str(file), "--silent"])
    assert exc.value.code == 2
    assert "JSON" in capsys.readouterr().err
    assert not destination.parent.exists()


def test_missing_file_is_rejected_without_output(owner, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        owner.main([str(tmp_path / "project"), "--brand-file", str(tmp_path / "absent.json"), "--silent"])
    assert exc.value.code == 2
    assert not (tmp_path / "project").exists()


def test_override_must_still_pass_effective_contrast(owner, tmp_path):
    with pytest.raises(ValueError, match="contrast"):
        owner.author(tmp_path / "bad", brand_file=write_brand(tmp_path, CUSTOM), ink="#ffffff", audio=False)
    assert not (tmp_path / "bad").exists()


def test_no_file_keeps_original_defaults_and_output(owner, tmp_path):
    implicit, explicit = tmp_path / "implicit", tmp_path / "explicit"
    assert owner.main([str(implicit), "--silent"]) == 0
    owner.author(explicit, audio=False, brand="Taskfilm", tagline="Editable motion.", **DEFAULTS["palette"])
    plan = read_plan(implicit)
    assert "brand_file" not in plan
    assert {key: plan["config"][key] for key in DEFAULTS} == DEFAULTS
    assert plan["config"]["headline"] == "Make it move."
    assert plan["config"]["duration"] == 12
    for path in implicit.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (explicit / path.relative_to(implicit)).read_bytes()
