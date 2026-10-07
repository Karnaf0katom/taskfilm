"""Dispatch to exported owner modules; never duplicate planning or rendering."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import __version__

HERE = Path(__file__).resolve().parent
VIDEO = HERE / "_vendor/video"
HYPERFRAMES_VERSION = "0.8.134"
OWNERS = {
    "story": "director/product_story.py",
    "capture": "capture-lane/webrec.py",
    "edit": "capture-lane/plan.py",
    "compose": "capture-lane/hfcomp.py",
    "reel": "capture-lane/reel.py",
    "repo-pack": "repo-lane/repo_pack.py",
    "package": "reel-lane/demo_package.py",
    "motion": "hyperframes-lane/product-motion/build.py",
}


def run_owner(command: str, args: list[str]) -> int:
    if command == "motion":
        # Help and a useful install error work even without the optional DSP
        # dependencies. Parsing remains the owner's job once they are present.
        if "--help" in args or "-h" in args:
            sub = argparse.ArgumentParser(prog="taskfilm motion", description=
                "Author the existing motion-film kit from spec.json and a real 4K take.")
            sub.add_argument("film", type=Path)
            sub.add_argument("--format", choices=("landscape", "portrait"), default="landscape")
            sub.add_argument("--no-audio", action="store_true")
            sub.add_argument("--take", type=Path)
            sub.print_help()
            return 0
        if any(importlib.util.find_spec(name) is None for name in ("numpy", "scipy")):
            raise ValueError("motion requires the optional dependencies: pip install 'taskfilm[motion]'")
    owner = VIDEO / OWNERS[command]
    if not owner.is_file():
        raise ValueError("owner files are absent; install the exported Taskfilm distribution")
    env = os.environ.copy()
    env.setdefault("CAPTURE_HYPERFRAMES_VERSION", HYPERFRAMES_VERSION)
    custom_font = any(arg == "--font-file" or arg.startswith("--font-file=") for arg in args)
    if command in {"compose", "reel"} and not custom_font and not env.get("CAPTURE_COMPOSITION_FONT"):
        assets = VIDEO / "hyperframes-lane/product-motion/assets"
        env["CAPTURE_COMPOSITION_FONT"] = str(assets / "Manrope.ttf")
        env["CAPTURE_COMPOSITION_FONT_NOTICE"] = str(assets / "Manrope-OFL.txt")
    return subprocess.run([sys.executable, str(owner), *args], env=env).returncode


def doctor(as_json: bool) -> int:
    checks = {
        "python": sys.version_info >= (3, 10),
        "owners": all((VIDEO / path).is_file() for path in OWNERS.values()),
        "playwright": importlib.util.find_spec("playwright") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "node": shutil.which("node") is not None,
        "npm": shutil.which("npm") is not None,
        "motion_dependencies": all(importlib.util.find_spec(name) is not None for name in ("numpy", "scipy")),
    }
    result = {"version": __version__, "checks": checks,
              "planning_ready": checks["python"] and checks["owners"],
              "capture_tools_ready": all(checks[k] for k in ("owners", "playwright", "ffmpeg", "ffprobe")),
              "browser_check": "run taskfilm capture check",
              "hyperframes_version": HYPERFRAMES_VERSION}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        for name, ok in checks.items():
            print(f"{name:12} {'ok' if ok else 'missing'}")
        print("Check the browser with: taskfilm capture check")
    return 0 if result["planning_ready"] else 1


def initialize(destination: Path, kind: str = "examples") -> int:
    source = HERE / kind
    if not source.is_dir():
        raise ValueError(f"{kind} are missing from the installed distribution")
    if destination.exists():
        raise ValueError("example destination must be a new directory")
    shutil.copytree(source, destination)
    if kind == "skill":
        print(json.dumps({"skill": str(destination / "SKILL.md")}))
        return 0
    # Make the bundled identity editable beside the sample. The original font
    # bytes and licence still come from their selected asset owner.
    brand = json.loads((VIDEO / "mix/brand/taskfilm-demo.json").read_text())
    fonts = destination / "brand/fonts"
    fonts.mkdir(parents=True)
    for filename in ("Manrope.ttf", "Manrope-OFL.txt"):
        shutil.copy2(VIDEO / f"hyperframes-lane/product-motion/assets/{filename}", fonts / filename)
    brand["type"]["weights"] = {weight: "fonts/Manrope.ttf" for weight in brand["type"]["weights"]}
    brand["type"]["licence"]["file"] = "fonts/Manrope-OFL.txt"
    (destination / "brand/taskfilm-demo.json").write_text(json.dumps(brand, indent=2) + "\n")
    lab_assets = destination / "motion-lab/assets"
    lab_assets.mkdir(parents=True)
    for filename in ("Manrope.ttf", "Manrope-OFL.txt", "GeistMono.ttf", "GeistMono-OFL.txt"):
        shutil.copy2(VIDEO / f"hyperframes-lane/product-motion/assets/{filename}", lab_assets / filename)
    print(json.dumps({"example": str(destination), "next":
        f"taskfilm story --request {destination / 'request.json'} --story {destination / 'feature.json'} --brand-dir {destination / 'brand'}"}))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Forward the owner's --help as well as its flags without interpreting them.
    if argv and argv[0] in OWNERS:
        try:
            return run_owner(argv[0], argv[1:])
        except (ValueError, OSError) as exc:
            print(f"taskfilm: {exc}", file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(prog="taskfilm", description=
        "Turn real product workflows into feature lessons, product promos and OSS demos.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("command", nargs="?", choices=[*OWNERS, "doctor", "init", "skill", "render"])
    args, rest = parser.parse_known_args(argv)
    try:
        if args.command in OWNERS:
            return run_owner(args.command, rest)
        if args.command == "doctor":
            sub = argparse.ArgumentParser(prog="taskfilm doctor")
            sub.add_argument("--json", action="store_true")
            return doctor(sub.parse_args(rest).json)
        if args.command in {"init", "skill"}:
            sub = argparse.ArgumentParser(prog=f"taskfilm {args.command}")
            sub.add_argument("destination", type=Path)
            return initialize(sub.parse_args(rest).destination, "skill" if args.command == "skill" else "examples")
        if args.command == "render":
            sub = argparse.ArgumentParser(prog="taskfilm render")
            sub.add_argument("project", type=Path)
            sub.add_argument("--output", type=Path, default=Path("out.mp4"))
            sub.add_argument("--quality", choices=["draft", "looks", "delivery"], default="looks")
            options = sub.parse_args(rest)
            if not (options.project / "hyperframes.json").is_file():
                raise ValueError("project must contain hyperframes.json and its HyperFrames composition")
            if not shutil.which("npm"):
                raise ValueError("render requires Node.js 22+ and npm")
            output = options.output.resolve()
            if output.exists():
                raise ValueError("render output must be a new file")
            # Use the composition's pin. Checks and rendering go through the same
            # maintained HyperFrames CLI that the existing owner emits.
            checked = subprocess.run(["npm", "run", "check"], cwd=options.project)
            if checked.returncode:
                return checked.returncode
            return subprocess.run(["npm", "run", "render", "--", "--quality", options.quality,
                                   "--output", str(output)], cwd=options.project).returncode
        if rest:
            parser.error(f"unrecognized arguments: {' '.join(rest)}")
        parser.print_help()
        return 0
    except (ValueError, OSError) as exc:
        print(f"taskfilm: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
