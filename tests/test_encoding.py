"""Exercise legacy streams and file defaults without requiring a Windows host."""
import io
import json
import os
import shutil
import subprocess
import sys

import pytest

from taskfilm import cli


@pytest.mark.parametrize("encoding", ["gbk", "cp1252", "ascii"])
def test_cli_and_owner_output_is_utf8_with_legacy_streams(tmp_path, encoding):
    script = json.loads((cli.HERE / "examples/capture.json").read_text(encoding="utf-8"))
    script["url"] = "https://example.invalid/任务/🎬"
    source = tmp_path / "任务-🎬.json"
    source.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    # -I ignores PYTHONIOENCODING in the public process; configure its streams
    # explicitly. The environment still reaches the separate owner process.
    bootstrap = """
import sys
from taskfilm.cli import main
encoding = sys.argv.pop(1)
sys.stdout.reconfigure(encoding=encoding, errors='strict')
sys.stderr.reconfigure(encoding=encoding, errors='strict')
raise SystemExit(main())
"""
    env = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING=encoding)

    def run(*args):
        return subprocess.run(
            [sys.executable, "-I", "-X", "utf8=0", "-c", bootstrap, encoding, *map(str, args)],
            cwd=tmp_path, env=env, capture_output=True, timeout=30)

    result = run("capture", "validate", source)
    assert result.returncode == 0, result.stderr.decode("utf-8")
    output = result.stdout.decode("utf-8")
    assert "ok · 14 steps · " in output
    assert "beat×3" in output
    assert script["url"] in output
    assert "\ufffd" not in output

    # The public parser's stderr uses the same contract as owner stdout.
    failed = run("doctor", "--未知-🎬")
    assert failed.returncode == 2
    assert "--未知-🎬" in failed.stderr.decode("utf-8")


def test_init_reads_utf8_brand_under_gbk_file_default(tmp_path, monkeypatch):
    assets = tmp_path / "kit"
    brand_path = assets / "mix/brand/taskfilm-demo.json"
    brand_path.parent.mkdir(parents=True)
    brand = json.loads((cli.VIDEO / "mix/brand/taskfilm-demo.json").read_text(encoding="utf-8"))
    brand["wordmark"] = "任务 🎬 —"
    brand_path.write_text(json.dumps(brand, ensure_ascii=False), encoding="utf-8")
    shutil.copytree(cli.VIDEO / "hyperframes-lane/product-motion/assets",
                    assets / "hyperframes-lane/product-motion/assets")
    monkeypatch.setattr(cli, "VIDEO", assets)
    original_open = io.open

    def gbk_open(file, mode="r", buffering=-1, encoding=None, *args, **kwargs):
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "gbk"
        return original_open(file, mode, buffering, encoding, *args, **kwargs)

    monkeypatch.setattr(io, "open", gbk_open)
    # Prove the emulation reaches Path.read_text before exercising the app.
    with pytest.raises(UnicodeDecodeError):
        brand_path.read_text()
    destination = tmp_path / "sample"
    assert cli.initialize(destination) == 0
    saved = json.loads((destination / "brand/taskfilm-demo.json").read_text(encoding="utf-8"))
    assert saved["wordmark"] == brand["wordmark"]


def test_cli_supports_embedded_text_streams(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    assert cli.main(["doctor", "--json"]) == 0
    assert json.loads(output.getvalue())["planning_ready"] is True
