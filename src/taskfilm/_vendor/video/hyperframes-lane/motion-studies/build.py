"""Author original motion studies; playback and encoding stay with HyperFrames."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
VIDEO = HERE.parents[1]
DIRECTOR = VIDEO / "director"
sys.path.insert(0, str(DIRECTOR))
from creative_treatments import CATALOG, SOURCE, select

FORMATS = {"landscape": (1920, 1080), "portrait": (1080, 1920)}
BRAND_DEFAULTS = {"brand": "Taskfilm", "tagline": "Editable motion.",
                  "ink": "#142124", "paper": "#fff5e5", "accent": "#ff613d"}
_UNSET = object()


def text(value: str, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must contain 1–{limit} printable characters")
    return value.strip()


def palette(ink: str, paper: str, accent: str) -> dict:
    colors = {"ink": ink, "paper": paper, "accent": accent}
    if any(not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value) for value in colors.values()):
        raise ValueError("palette colors must be six-digit hex values")
    def luminance(color):
        values = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055)**2.4 for v in values]
        return sum(a*b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))
    a, b = sorted((luminance(ink), luminance(paper)))
    if (b + 0.05) / (a + 0.05) < 4.5:
        raise ValueError("ink and paper need contrast of at least 4.5:1")
    return colors


def load_brand(file: Path) -> tuple[dict, str]:
    """Validate the versioned input without writing any project files."""
    raw = file.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("brand file must be valid UTF-8 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("brand file must be a JSON object")
    if set(data) - {"schema", "brand", "tagline", "palette"}:
        raise ValueError("brand file contains unknown keys")
    if data.get("schema") != "taskfilm-brand/v1":
        raise ValueError("brand file schema must be taskfilm-brand/v1")
    values = {}
    for key, limit in (("brand", 24), ("tagline", 54)):
        if key in data:
            values[key] = text(data[key], key, limit)
    if "palette" in data:
        colors = data["palette"]
        if not isinstance(colors, dict) or set(colors) - {"ink", "paper", "accent"}:
            raise ValueError("brand palette must be an object with only ink, paper and accent keys")
        for key, value in colors.items():
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError("brand palette colors must be six-digit hex values")
            values[key] = value
    return values, hashlib.sha256(raw).hexdigest()


def score(destination: Path, duration: int, treatment: str, seed: int) -> None:
    """Arrange sounds and normalize through the existing product-motion owner."""
    import numpy as np
    kit = VIDEO / "hyperframes-lane/product-motion"
    sys.path.insert(0, str(kit))
    spec = importlib.util.spec_from_file_location("taskfilm_original_score_owner", kit / "build.py")
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    sounds = owner.sfx
    period = {"type-sculpture": .5, "orbit-story": .6, "signal-field": .4, "showreel": .5}[treatment]
    mix = sounds.pulse_bed(duration, period) * .60
    events = ([0.10, 2.6, 6.8, 10.0] if duration == 12 else [0.1, 5.4, 10.8, 16.0])
    for index, at in enumerate(events):
        hit = sounds.impact(size=.40 if index % 2 else .65, seed=(seed + index + 31) % 2**32) * .25
        start = int(at * sounds.SR)
        count = min(len(hit), len(mix) - start)
        mix[start:start+count] += hit[:count]
        if index:
            swish = sounds.swish(seed=(seed + index + 91) % 2**32) * .12
            start = int((at - .20) * sounds.SR)
            count = min(len(swish), len(mix) - start)
            mix[start:start+count] += swish[:count]
    # A designed 0.2-second audio tail; the picture holds its final signature.
    fade = np.clip((duration - np.arange(len(mix)) / sounds.SR) / .20, 0, 1)
    mix *= fade[:, None]
    raw = destination / "assets/score-source.wav"
    owner.write_wav(raw, mix)
    owner.loudnorm(raw, destination / "assets/mix.wav")
    raw.unlink()


def author(destination: Path, *, brief: str = "An original motion study", headline: str = "Make it move.",
           brand: str = _UNSET, tagline: str = _UNSET, format: str = "landscape",
           treatment: str | None = None, seed: int = 41, history: dict | None = None,
           allow_repeat: bool = False, showreel: bool = False, audio: bool = True,
           ink: str = _UNSET, paper: str = _UNSET, accent: str = _UNSET,
           brand_file: Path | None = None) -> dict:
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("animation destination must be a new directory")
    resolved = BRAND_DEFAULTS.copy()
    brand_hash = None
    if brand_file is not None:
        supplied, brand_hash = load_brand(Path(brand_file))
        resolved.update(supplied)
    explicit = {"brand": brand, "tagline": tagline, "ink": ink, "paper": paper, "accent": accent}
    resolved.update({key: value for key, value in explicit.items() if value is not _UNSET})
    brand, tagline = resolved["brand"], resolved["tagline"]
    ink, paper, accent = resolved["ink"], resolved["paper"], resolved["accent"]
    headline, brand, tagline = (text(headline, "headline", 54), text(brand, "brand", 24), text(tagline, "tagline", 54))
    colors = palette(ink, paper, accent)
    if audio and any(importlib.util.find_spec(name) is None for name in ("numpy", "scipy")):
        raise ValueError("audio requires pip install 'taskfilm[motion]'; use --silent for a silent study")
    choice = select(brief, format=format, seed=seed, history=history,
                    treatment=treatment, allow_repeat=allow_repeat)
    if not choice["selected"] and not showreel:
        raise ValueError(choice["exhaustion"])
    if showreel and treatment:
        raise ValueError("--showreel and --treatment cannot be combined")
    selected = "showreel" if showreel else choice["selected"]
    duration = 18 if showreel else 12
    width, height = FORMATS[format]
    config = {"treatment": selected, "headline": headline, "brand": brand, "tagline": tagline,
              "width": width, "height": height, "duration": duration, "fps": 30, "seed": seed, "palette": colors}
    cuts = [0, 5.4, 10.8, 16] if showreel else [0, 2.6, 6.8, 10]
    movie_plan = {"schema": "taskfilm-animation/v1", "execution": "authored_not_rendered",
                  "config": config, "selection": choice, "cuts_seconds": cuts,
                  "end_hold_seconds": 1, "audio": "original_synthesized_score" if audio else "deliberate_silence",
                  "picture_source": "Original Canvas geometry and supplied text; no UI recording or generated media.",
                  "visual_review": "not_performed", "history_updated": False}
    if brand_file is not None:
        movie_plan["brand_file"] = {"schema": "taskfilm-brand/v1", "sha256": brand_hash,
                                    "resolved": {"brand": brand, "tagline": tagline, "palette": colors}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".taskfilm-animation-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "project"
        assets = stage / "assets"
        assets.mkdir(parents=True)
        for name in ("Manrope.ttf", "Manrope-OFL.txt"):
            shutil.copy2(VIDEO / "hyperframes-lane/product-motion/assets" / name, assets / name)
        shutil.copy2(HERE / "runtime.js", stage / "runtime.js")
        inline = json.dumps(config, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        audio_markup = f'<audio id="motion-score" class="clip" data-start="0" data-duration="{duration}" data-track-index="2" data-track-kind="audio" src="assets/mix.wav"></audio>' if audio else ""
        html = (HERE / "study.html").read_text().replace("__WIDTH__", str(width)).replace("__HEIGHT__", str(height)).replace(
            "__DURATION__", str(duration)).replace("__CONFIG__", inline).replace("__AUDIO__", audio_markup)
        (stage / "index.html").write_text(html, encoding="utf-8")
        (stage / "ANIMATION-PLAN.json").write_text(json.dumps(movie_plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (stage / "hyperframes.json").write_text(json.dumps({"$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
            "paths": {"assets": "assets", "blocks": "compositions", "components": "compositions/components"}}, indent=2) + "\n")
        (stage / "package.json").write_text(json.dumps({"name": "taskfilm-motion-study", "private": True, "type": "module",
            "scripts": {"check": "npx --yes hyperframes@0.8.134 check", "render": "npx --yes hyperframes@0.8.134 render"}}, indent=2) + "\n")
        acts = ([("type-sculpture", 0, 5.4), ("orbit-story", 5.4, 10.8), ("signal-field", 10.8, 16), ("signature", 16, 18)]
                if showreel else [(role, cuts[i], cuts[i+1] if i < 3 else duration)
                                 for i, role in enumerate(next(row for row in CATALOG if row["id"] == selected)["scene_roles"])])
        storyboard = [f"# {brand}: {selected}", "", f"Idea: {brief}", "", f"Headline: {headline}",
                      f"Delivery: {width}×{height}, 30fps, {duration}s.", "",
                      "The artwork carries the film: no corner labels, fake product UI or progress counters.",
                      "Entries decelerate from oversize or offscreen; cuts arrive during movement.",
                      "Each frame is computed from absolute time; the final resolved signature holds for one second.", "",
                      "| Act | Seconds | Purpose |", "|---|---|---|"]
        for role, start, end in acts:
            storyboard.append(f"| {role} | {start:g}–{end:g} | " + ("Resolve to the supplied brand." if role == "signature" else
                "Make the selected visual mechanism visible and carry it into the next beat.") + " |")
        storyboard += ["", "## Sources", "", f"Craft study: {SOURCE['creator']}, {SOURCE['repository']} at {SOURCE['commit']}.",
                       "All pictures and recipe code are original Taskfilm work. Manrope retains its OFL notice.",
                       "Orbit depth is perspective-projected Canvas geometry, not a WebGL scene.", ""]
        (stage / "STORYBOARD.md").write_text("\n".join(storyboard), encoding="utf-8")
        (stage / "NOTE.md").write_text("# Review record\n\nAuthored source; final movie and visual/audio review are still pending.\n\n"
            "After encoding, retain its SHA-256, resolution/FPS/duration, complete decode result, seek comparison, "
            "sampled frames, readable-copy check and listening result when audio is present.\n"
            "Technical success alone does not certify visual quality. Do not add a reviewed history event yet.\n", encoding="utf-8")
        (stage / "README.md").write_text("# Editable animation\n\n"
            "Render with `taskfilm render . --output ../film.mp4`. Edit ANIMATION-PLAN.json only as a record; "
            "the actual render inputs are the embedded config in index.html and runtime.js.\n"
            "Open index.html through an HTTP server with `?preview=1` for playback and seeking.\n"
            "Use TaskfilmMotion.draw(seconds) for an exact frame, independent of playback order.\n", encoding="utf-8")
        if audio:
            score(stage, duration, selected, seed)
        if destination.exists() or destination.is_symlink():
            raise ValueError("destination appeared during authoring; no files overwritten")
        stage.rename(destination)
    return {"project": str(destination), "treatment": selected, "format": format,
            "duration": duration, "plan_sha256": hashlib.sha256((destination / "ANIMATION-PLAN.json").read_bytes()).hexdigest(),
            "rendered": False, "next": f"taskfilm render {destination} --output {destination.name}.mp4"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--brief", default="An original motion study")
    parser.add_argument("--headline", default="Make it move.")
    parser.add_argument("--brand", default=argparse.SUPPRESS)
    parser.add_argument("--tagline", default=argparse.SUPPRESS)
    parser.add_argument("--brand-file", type=Path, help="taskfilm-brand/v1 JSON; explicit flags override its values")
    parser.add_argument("--format", choices=FORMATS, default="landscape")
    parser.add_argument("--treatment", choices=[row["id"] for row in CATALOG])
    parser.add_argument("--showreel", action="store_true", help="18-second study containing all three families")
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--history", type=Path, help="caller-owned history of reviewed movies")
    parser.add_argument("--allow-repeat", action="store_true")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--ink", default=argparse.SUPPRESS)
    parser.add_argument("--paper", default=argparse.SUPPRESS)
    parser.add_argument("--accent", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        options = vars(args).copy()
        destination = options.pop("destination")
        options["audio"] = not options.pop("silent")
        options["history"] = json.loads(args.history.read_text()) if args.history else None
        print(json.dumps(author(destination, **options), indent=2))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"animate: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
