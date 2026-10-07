"""build_mix — the conductor for a multi-engine timeline.

It owns NO compositing and NO motion. It only:

  1. hands each engine the spec IT understands            (--engine-spec manim|hyperframes)
  2. turns the rendered assets into an edit-lane EditPlan (--plan)   -> one mp4, server-side
  3. turns the same assets into FreeCut ops               (--ops)    -> editable timeline items

Both outputs describe the SAME arrangement. That is the whole point: an engine is a producer of
clips, and the timeline is the shared surface. Adding a fourth engine later means teaching this
file how to write its spec — edit-lane and FreeCut do not learn anything new.

Durations are PROBED from the rendered assets, never declared. Manim decides its own beat length
from the template, HyperFrames from the block, and footage from its in/out — so a declared
duration in the spec would be a second source of truth that silently drifts.

    python3 build_mix.py mix.json --engine-spec hyperframes > reel.json
    python3 build_mix.py mix.json --engine-spec manim      > reel.json
    python3 build_mix.py mix.json --assets assets.json --out-dir out/
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "edit-lane"))

from freecut_timeline_ops import build_timeline_ops, sequence  # noqa: E402

# `models` is NOT imported here, and that is load-bearing rather than style. It pulls pydantic, and
# this file is executed inside THREE different images: the manim beat runs it as
# `build_mix.py --engine-spec manim` inside `manimcommunity/manim:stable`, which has no pydantic and
# cannot get one (uid 1000, no apt — see mix/brand/fonts/README.md). A module-level import therefore
# reddened the whole mix build at step 2 the moment item 7 added it, before a single frame rendered
# (Cloud Build 7d6894a0). Only the PLAN path needs the contract, and the plan path runs in
# video-edit-render where pydantic exists — so the two functions that need it import it themselves.
# The doctrine is unchanged: edit-lane still owns Transition/TransitionKind/Output and this file
# still imports them rather than restating them. It just does it where they are actually used.

ENGINES = {"hyperframes", "manim", "remotion", "footage"}

PALETTE_KEYS = ("bg", "primary", "secondary", "accent", "ink", "mute", "card")

# The pack names weights the way a designer does; CSS and Chrome want a number. The translation is
# the CONDUCTOR's job, exactly like every other projection here — a lane that mapped `semibold -> 600`
# itself would be a second vocabulary, and the last time two vocabularies disagreed the weight gate
# asked for a file called `Inter-Normal` that has never existed. Unknown name = SystemExit, because
# the alternative is Chrome picking the nearest face and synthesising the difference silently.
WEIGHT_CSS = {"thin": 100, "extralight": 200, "light": 300, "normal": 400,
              "medium": 500, "semibold": 600, "bold": 700, "extrabold": 800, "black": 900}


def load_brand_pack(mix: dict, base: Path | None = None, *, brand_dir: Path | None = None) -> dict:
    """Resolve + validate the client brand pack ONCE. Owner: this file (see
    .agent/portfolio/decisions/video-render-brand-pack-owner.md).

    A reel is a job; an identity is an asset reused across reels — so the pack is a file
    (mix/brand/<name>.json) named by the mix, not a block inlined in it.

    This is the single validation point ON PURPOSE. The three projections below used to check
    three different amounts: hyperframes got the dict whole and unfiltered, manim failed closed
    on the palette but OPEN on font, remotion filtered to an allow-list where a missing key was
    silently absent. Asymmetric in three directions is a symptom, not a feature — so everything
    is checked here and the projections inherit it by construction.
    """
    if "brand" in mix:
        raise SystemExit(
            "this mix carries an inline `brand` block. The pack moved to its own file so one "
            "identity can serve many reels — replace it with `\"brand_pack\": \"<name>\"` "
            "pointing at mix/brand/<name>.json. Two sources for one identity is the drift the "
            "pack exists to stop."
        )
    name = mix.get("brand_pack")
    if not name:
        raise SystemExit("mix declares no `brand_pack` — nothing tells the engines what to look like")

    path = (brand_dir if brand_dir is not None else (base or HERE) / "brand") / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"brand pack `{name}` not found at {path}")
    pack = json.loads(path.read_text(encoding="utf-8"))

    missing_palette = [k for k in PALETTE_KEYS if k not in pack.get("palette", {})]
    if missing_palette:
        raise SystemExit(
            f"brand pack `{name}` palette is missing {missing_palette} — motion-lane's BrandKit "
            f"silently falls back to ITS OWN defaults for absent keys, so the reel would render "
            f"in motion-lane's colours and nothing would complain"
        )

    type_block = pack.get("type", {})
    if not type_block.get("family"):
        # Fails CLOSED now. This is the exact key that used to be `brand.get("font", "sans-serif")`
        # — a default that resolved to Noto Sans in the manim container while Remotion rendered
        # Inter, i.e. two typefaces in a reel whose premise is one identity.
        raise SystemExit(f"brand pack `{name}` declares no type.family — the reel has no typeface")
    weights = type_block.get("weights")
    if not weights:
        raise SystemExit(
            f"brand pack `{name}` declares no type.weights — the font install has nothing to "
            f"gate on, so a template asking for an unshipped weight gets a synthesised one"
        )
    # Resolve the files here rather than in the build step: the pack is the only thing that
    # knows which file provides which weight, and the two vocabularies genuinely differ
    # (CSS/manim `normal` is the file Inter ships as `Regular`). Nothing downstream guesses.
    absent = [f"{w} -> {rel}" for w, rel in weights.items() if not (path.parent / rel).exists()]
    if absent:
        raise SystemExit(
            f"brand pack `{name}` names weight files that do not exist: {absent}. "
            f"Ship the file into mix/brand/fonts/ or drop the weight — see that dir's README."
        )
    return pack


def brand_render_identity(pack: dict) -> dict:
    """Project a validated pack into the stable identity shared by render callers.

    ``load_brand_pack`` remains the validation owner.  This projection deliberately contains
    no job/request fields: a reusable identity is not a recipe, and callers should bind it by
    digest rather than copying the pack into their own schema.
    """
    return {
        "name": pack["name"],
        "wordmark": pack.get("wordmark", pack["name"]),
        "font": pack["type"]["family"],
        "palette": {key: pack["palette"][key] for key in PALETTE_KEYS},
    }


def _font_files(pack: dict) -> list[dict]:
    """The pack's weights as a browser can consume them: CSS weight + the file's BASENAME.

    Basename, not the pack-relative path, because the two sides of this hand-off do not share a
    filesystem: the render step copies `mix/brand/fonts/*` into the lane's `public/` and Remotion
    addresses it with `staticFile("fonts/<basename>")`. Sending `fonts/X.ttf` would resolve to
    `public/fonts/fonts/X.ttf` and 404 into a silent fallback — the failure this whole field exists
    to prevent. Sorted so the props are stable and two identical mixes diff clean.
    """
    weights = pack["type"]["weights"]
    unknown = sorted(w for w in weights if w not in WEIGHT_CSS)
    if unknown:
        raise SystemExit(
            f"brand pack `{pack['name']}` declares weight name(s) {unknown} that have no CSS "
            f"weight. Known: {', '.join(WEIGHT_CSS)}. Rename in the pack, or add the mapping to "
            f"WEIGHT_CSS if the family really ships that weight."
        )
    return sorted(
        ({"weight": WEIGHT_CSS[w], "file": Path(rel).name} for w, rel in weights.items()),
        key=lambda f: f["weight"],
    )


def engine_spec(mix: dict, engine: str, base: Path | None = None) -> dict:
    """The spec that engine's own lane already knows how to read — not a new format.

    hyperframes -> hyperframes-lane/reel.json shape (blocks + per-instance variable values)
    manim       -> motion-lane/reel.json shape (brand pack + scene templates)
    remotion    -> remotion-lane props for ONE composition (`--props`)

    Each is a PROJECTION of the one validated pack. A lane never reads the pack itself.
    """
    beats = [b for b in mix["beats"] if b["engine"] == engine]
    if not beats:
        raise SystemExit(f"no {engine} beats in this mix")

    pack = load_brand_pack(mix, base)
    identity = brand_render_identity(pack)
    palette = identity["palette"]
    family = identity["font"]

    if engine == "hyperframes":
        # NO default duration. The old `b.get("duration", 6)` was not a fallback, it was the
        # answer: hyperframes-lane writes this number straight into the block's `data-duration`,
        # advances its timeline cursor by it, and sums it as the reel length (build_reel.py:95,
        # 119, 149, 246). So the conductor's invented 6 BECAME the beat — mix/out/assets.json
        # records the shipped hook at exactly 6.0s, a length no one chose. The lane itself has
        # always failed closed here (`float(beat["duration"])`); only the conductor papered over
        # it. A missing duration is now an error, per SC-IDENTITY-DECISIONS Q4: "the conductor
        # should never invent a number, and a rhythm is a director choice."
        undeclared = [b.get("id", "<no id>") for b in beats if "duration" not in b]
        if undeclared:
            raise SystemExit(
                f"hyperframes beat(s) {undeclared} declare no duration. There is nothing to "
                f"fall back to: a block does not author its own length on this path — the "
                f"conductor writes it — and nothing is probed until after the render. Declare "
                f"`duration` in seconds on each hyperframes beat in the mix spec."
            )
        return {
            "name": f"{mix['name']}-hyperframes",
            "fps": mix["fps"],
            "width": mix["width"],
            "height": mix["height"],
            # PROJECTION, not the pack. This used to hand over mix["brand"] whole, by reference
            # and unfiltered — so doc keys and manim-only palette entries rode along into a lane
            # spec that reads none of them. hyperframes resolves "@ink" / "@font" against these
            # flat keys (build_reel.py::resolve), the latter being what a `retype` map targets.
            "brand": {**palette, "font": family},
            "beats": [
                {
                    "block": b["block"],
                    "duration": b["duration"],
                    **({"recolor": b["recolor"]} if "recolor" in b else {}),
                    **({"retype": b["retype"]} if "retype" in b else {}),
                    # A declared decision to ship a beat in the vendor's own typeface. Forwarded
                    # so the lane's audit reports it as a CHOICE rather than as a miss.
                    **({"vendor_type": b["vendor_type"]} if "vendor_type" in b else {}),
                    **({"blank_assets": b["blank_assets"]} if "blank_assets" in b else {}),
                    "values": b.get("values", {}),
                }
                for b in beats
            ],
        }

    if engine == "manim":
        # A template name is not checked anywhere else. `compose.py` resolves it with a bare
        # `importlib.import_module(f"scenes.{s['template']}")` at RENDER time, so a typo survives
        # every validation in this file — brand, palette, fonts, audio, look, grade — boards the
        # Cloud Build, spins up the manim image, and dies there on ModuleNotFoundError. That is a
        # multi-minute round trip to learn about a misspelling. Same argument as
        # motion-lane/tests/test_layout.py: ask the question here, in milliseconds.
        _check_templates(beats)

        # motion-lane/brandkit.py reads the palette from brand["palette"], and brand["font"] /
        # brand["wordmark"] from the level above it. A FLAT brand dict does not error — BrandKit
        # just falls through to its own defaults, so the reel renders in motion-lane's colours and
        # nothing complains. Build the nested shape explicitly and keep only the keys it reads.
        # The palette/font checks that used to live here (one closed, one OPEN) now happen once,
        # for every engine, in load_brand_pack().
        return {
            # Manim was the ONE engine spec that did not carry the delivery format, so the lane
            # fell back to a CLI quality flag (-qm = 1280x720) and every beat arrived undersized
            # into a 1920x1080 mix. hyperframes and remotion below always forwarded these.
            "fps": mix["fps"],
            "width": mix["width"],
            "height": mix["height"],
            # Platform-reserved strips, forwarded when the mix declares them. compose.py builds the
            # scene's safe box from these, so a template centres on the VISIBLE frame rather than
            # the whole one. Absent (a landscape mix, or a hand-written spec), the lane falls back
            # to its symmetric margin and nothing changes.
            **({"safe_top": mix["safe_top"]} if "safe_top" in mix else {}),
            **({"safe_bottom": mix["safe_bottom"]} if "safe_bottom" in mix else {}),
            "brand": {
                "wordmark": pack.get("wordmark", mix.get("name", "brand")),
                "font": family,
                "palette": {k: palette[k] for k in PALETTE_KEYS},
            },
            "scenes": [{"template": b["template"], "content": b.get("content", {})} for b in beats],
        }

    if engine == "remotion":
        # Remotion renders ONE composition per call, so a remotion beat is its own props file —
        # not a reel. Size/fps/length are read from these props by `calculateMetadata`, so the
        # component stays the only place that decides how long the beat runs.
        if len(beats) != 1:
            raise SystemExit(
                f"remotion renders one composition per call; this mix has {len(beats)} remotion "
                f"beats — render them one at a time (--engine-spec remotion --beat <id>)"
            )
        beat = beats[0]
        return {
            "width": mix["width"],
            "height": mix["height"],
            "fps": mix["fps"],
            # Beat.tsx's Brand type. The `if k in ...` include-only-if-present filter is gone:
            # it made a missing key silently absent, and the component then rendered its own
            # default as if it had been asked for. The pack is validated, so these exist.
            "brand": {**{k: palette[k] for k in ("bg", "ink", "accent", "secondary", "mute", "card")},
                      "font": family,
                      # The BYTES, not just the name — the difference between this projection and the
                      # other two. manim gets a family name because the render step installs the files
                      # into fontconfig first; Chrome has no fontconfig to install into, so the lane
                      # has to be told which files to @font-face. Without this the component asked for
                      # `${brand.font}, Inter` and only ever LOADED Inter, so naming a new family in
                      # the pack silently kept rendering the old one — the fail-open item 1's closing
                      # note predicted and item 6's gate closed for hyperframes only.
                      "font_files": _font_files(pack)},
            "content": beat.get("content", {}),
        }

    raise SystemExit(f"{engine} renders nothing — it is source media")


def _transition_for(beat: dict, index: int) -> dict | None:
    """A beat's declared seam, validated against edit-lane's OWN contract.

    edit-lane already implements transitions end to end — `Clip.transition` compiles to ffmpeg
    `xfade` + `acrossfade` with an overlap-safety preflight. What was missing was never the
    compositor; it was the conductor asking for anything, so `compile_xfade` took its
    all-None fast path and every beat butt-cut. So this validates and forwards; it does not
    invent a second transition system.

    The kind enum is IMPORTED rather than copied. A hardcoded list here would be a second
    source of truth that silently rots the day edit-lane adds a wipe.

    Semantics follow edit-lane's: a clip's transition is the seam ENTERING it (the compiler
    reads `clips[1:]`). A transition on beat 0 has no preceding clip and is silently ignored
    down there — so it is refused up here instead of quietly doing nothing.
    """
    declared = beat.get("transition")
    if declared is None:
        return None
    if index == 0:
        raise SystemExit(
            f"beat '{beat['id']}' is first and declares a transition, but a transition is the "
            f"seam INTO a beat — there is nothing before it. edit-lane would ignore it silently."
        )
    from models import Transition, TransitionKind  # edit-lane owns the contract; see the note at the imports
    try:
        return Transition(**declared).model_dump(mode="json")
    except Exception as exc:
        kinds = ", ".join(k.value for k in TransitionKind)
        raise SystemExit(
            f"beat '{beat['id']}' has an invalid transition {declared}: {exc}\nkinds: {kinds}"
        )


def _look_name(value, what: str) -> str:
    """Validate a look/grade NAME against edit-lane's own field rule, eagerly.

    A name that fails the pattern is not an error downstream — ``look_stage.load_look`` returns None
    for anything it cannot find and the render proceeds ungraded. That is the right behaviour there
    (a typo in a colour field should not kill a cut) and exactly the wrong place to discover it here,
    because the conductor's whole job is to hand over a plan that means what it says. So the check
    happens at the border, against the pattern edit-lane's ``Output.look`` declares — imported, not
    copied, so it cannot rot apart from it.
    """
    from models import Output  # edit-lane owns the contract; see the note at the imports

    field = Output.model_fields["look"]
    pattern = next(m.pattern for m in field.metadata if hasattr(m, "pattern"))
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise SystemExit(
            f"{what} must match {pattern} (edit-lane's look-name rule); got {value!r}. "
            f"Named looks live in edit-lane/looks/<name>.json."
        )
    return value


def _known_templates() -> set[str] | None:
    """Template module names under `motion-lane/scenes`, or ``None`` when that tree is not visible.

    ``None`` rather than an empty set, deliberately. This file runs inside THREE images (see the note
    at the imports), and an empty set would be indistinguishable from "the scene library is missing",
    which would reject every beat in an image that simply does not carry it. Only a caller that can
    SEE the library gets to police it.
    """
    scenes = HERE.parent / "motion-lane" / "scenes"
    if not scenes.is_dir():
        return None
    return {p.stem for p in scenes.glob("*.py") if p.stem != "__init__"}


def _check_templates(beats: list[dict]) -> None:
    """Fail here, on a name compose.py would only reject after the Cloud Build has started."""
    nameless = [b.get("id", "?") for b in beats if not str(b.get("template", "")).strip()]
    if nameless:
        raise SystemExit(
            f"manim beats {nameless} name no `template`. Every manim beat renders one scene module "
            f"from motion-lane/scenes — without a name there is nothing to render."
        )

    known = _known_templates()
    if known is None:            # not our tree to police; compose.py still resolves it at render
        return
    unknown = sorted({b["template"] for b in beats} - known)
    if unknown:
        raise SystemExit(
            f"unknown manim template(s) {unknown} — no such module in motion-lane/scenes. "
            f"compose.py would import this at RENDER time, so the Cloud Build is where you would "
            f"have found out. Known templates: {sorted(known)}"
        )


def _audio(block: dict) -> dict:
    """Validate a mix's audio request against edit-lane's ``Audio`` model and hand back plain JSON.

    Imported, not re-implemented: the mood strings, the VO fields and the accent styles are already
    bounded there, and a second copy of those rules here is the drift the conductor exists to avoid.
    A bad request fails at the border with the model's own message instead of rendering silently
    without the layer that was asked for.
    """
    # Imported HERE, not at module scope: this file also runs inside `manimcommunity/manim:stable`,
    # which has no pydantic and cannot get one — see the note at the imports. Only the plan path
    # needs the contract, and the plan path runs where pydantic exists.
    from models import Audio  # edit-lane owns the contract; see the note at the imports
    from pydantic import ValidationError

    try:
        return Audio.model_validate(block).model_dump(mode="json")
    except ValidationError as exc:
        # Deliberately NOT a bare ``except``. The first draft here caught Exception and reported a
        # NameError in this very function as "your audio block is invalid" — a wrong request and a
        # broken conductor must never produce the same message.
        raise SystemExit(f"mix `audio` block is not a valid edit-lane Audio request: {exc}")


def build_plan(mix: dict, assets: dict) -> dict:
    """An edit-lane EditPlan whose clips are the rendered beats, in spec order.

    Every beat becomes one source and one clip. edit-lane neither knows nor cares which engine
    made which file — that is exactly the property that lets engines mix.

    COLOUR crosses this border in two places, and they are not interchangeable. A beat may name a
    per-source ``grade`` (a normalizer for THAT media's own white point — a generator that renders
    warm, a camera left on tungsten); the mix may name one ``look`` (the film's grade, applied once
    to the finished concat). Neither used to be forwarded at all, so a multi-engine reel arrived at
    the compositor completely ungraded and the one-film look this lane exists for was unreachable
    from a mix spec. See edit-lane/looks/ and motion-lane/spikes/tempproof/README.md for why both
    are needed rather than either.
    """
    # A beat that asks to be STACKED cannot be honoured here yet, and flattening it into a
    # full-screen cut is a lie the render tells silently — the ops path (build_ops → sequence())
    # stacks it, this path cuts it, and the same spec produces two different films with no signal.
    # Fail loudly instead, in the same shape _engine_spec uses for multi-beat remotion.
    #
    # The tempting fix — emit `Output.overlays` here, the mechanism is live — was MEASURED and does
    # not work: spikes/f4-overlay-proof renders an opaque card composited over footage and a plain
    # cut to the same card, and they are pixel-identical (MAD 0.000). motion-lane has no
    # transparency at all, so stacking today buys nothing AND shortens the reel by the overlay
    # beats' durations. Two things must be decided first — alpha in motion-lane, and what
    # `overlay.picture` selects — both written up in that spike's README.
    # WARN rather than raise: this path is the only way the director chain reaches a valid EditPlan,
    # and the flagship specs (mix/planned-*.json) all carry overlay beats. Killing it would trade a
    # long-latent defect for a dead pipeline — the same "looks like progress, renders worse" trade
    # the spike argues against. Loud is enough; the intent is no longer dropped in silence.
    stacked = [b["id"] for b in mix["beats"] if b.get("overlay")]
    if stacked:
        print(
            f"WARNING: beats {stacked} ask to be stacked (`overlay`); this EditPlan flattens them "
            f"into full-screen cuts, dropping the one thing they asked for. The FreeCut ops path "
            f"(build_ops) DOES stack them, so the same spec yields two different films. Board row "
            f"F4, blocked on two decisions — see spikes/f4-overlay-proof/README.md.",
            file=sys.stderr,
        )

    sources, clips = [], []
    for i, beat in enumerate(mix["beats"]):
        a = assets[beat["id"]]
        sources.append({
            "path": a["path"],
            "duration_sec": float(a["duration"]),
            "language": "he",
            **({"grade": _look_name(beat["grade"], f"beat '{beat['id']}' grade")} if "grade" in beat else {}),
        })
        idx = len(sources) - 1
        start = float(beat.get("in", 0.0))
        end = float(beat.get("out", start + float(a["duration"])))
        transition = _transition_for(beat, i)
        clips.append({
            "source_index": idx,
            "start": start,
            "end": end,
            "reason": f"{beat['id']} ({beat['engine']})",
            # WHERE a 16:9 master is cropped from when the delivery is vertical. The director already
            # decided this per beat (faces and product sit above centre); it was travelling as far as
            # the mix spec and stopping there, so every vertical cut was centre-cropped regardless.
            **({"crop_anchor": list(beat["crop_anchor"])} if "crop_anchor" in beat else {}),
            **({"transition": transition} if transition else {}),
        })

    # An xfade OVERLAPS its two clips, so it SUBTRACTS from the timeline — output is
    # A + B - d, not A + B. Summing clip lengths alone would overstate the reel by the total
    # overlap, and beat_wire.py builds the music grid off this number.
    #
    # The clamp is IMPORTED and the accumulation MIRRORED, because re-deriving it got it wrong.
    # This used to read `min(fade, prev_clip, cur_clip)` under a comment claiming to mirror the
    # compositor — but `compile_xfade` clamps against `acc_dur`, the output built SO FAR, not
    # against the previous clip. The two agree until a transition is longer than the beat before
    # it, and then this number is optimistic: a 0.5s beat between two 1.0s fades predicted 5.500s
    # where ffmpeg renders 5.000s. Latent while every seam is a hard cut (SC-IDENTITY-DECISIONS
    # item 7) and wrong the moment one is not — which is exactly the kind of drift that only shows
    # up as music sliding out of sync with the picture, long after anyone would look here.
    # `_orphans.crossfade_overlap` is pure python, but it is imported HERE rather than at module
    # scope for the same reason `models` is: this function is the plan path, and the plan path is
    # the only one that runs in an image where edit-lane's tree is guaranteed importable.
    from _orphans.crossfade_overlap import crossfade_overlap  # edit-lane owns the clamp

    total = clips[0]["end"] - clips[0]["start"] if clips else 0.0
    for cur in clips[1:]:
        dur_b = cur["end"] - cur["start"]
        t = cur.get("transition")
        total += dur_b - (crossfade_overlap(total, dur_b, t["duration"]) if t else 0.0)
    return {
        "schema_version": "edit_plan/v1",
        "job_id": "engine-mix",
        "goal": f"{mix['name']} — {len(clips)} beats across {len({b['engine'] for b in mix['beats']})} engines",
        "mode": "auto_preview",
        "sources": sources,
        "outputs": [{
            "name": "mix",
            "format": "mp4",
            "aspect_ratio": mix["aspect_ratio"],
            "duration_target": round(total, 3),
            "clips": clips,
            "captions": {"enabled": False, "language": "he"},
            **({"look": _look_name(mix["look"], "mix look")} if "look" in mix else {}),
            # AUDIO crosses this border as ONE block, validated by edit-lane's own contract rather
            # than re-checked here. It carried nothing until now, so a mix could not ask for a music
            # bed, a voiceover or accents on its cuts — three layers that already existed downstream
            # and were unreachable from a spec. Same gap the look/grade/crop_anchor ones were.
            **({"audio": _audio(mix["audio"])} if "audio" in mix else {}),
        }],
    }


def build_ops(mix: dict, assets: dict, **tracks: str | None) -> list[dict]:
    """The same arrangement as FreeCut ops. Media ids come from the workspace, not from us.

    A beat that names an `in`/`out` (footage taken from a longer source) keeps that window here
    too — as a source in-point on the timeline item, NOT by pre-cutting the media. Pre-cutting
    would make the beat un-extendable in the editor, which is the whole reason ops cross this
    border instead of a baked mp4.

    ``base_track`` / ``overlay_track`` (see freecut_timeline_ops) name tracks that already exist
    in the target project instead of adding new ones.
    """
    beats = []
    for beat in mix["beats"]:
        a = assets[beat["id"]]
        start = float(beat.get("in", 0.0))
        end = float(beat.get("out", start + float(a["duration"])))
        beats.append({
            # A fabricated id would validate and resolve to nothing. PENDING:: is rejected by
            # FreeCut's id pattern, so ops built before the assets are in a workspace cannot be
            # applied by accident — run mix/land_in_freecut.py to mint the real ones.
            "media_id": a.get("media_id") or f"PENDING::{beat['id']}",
            "duration": end - start,
            "source_start": start,
            "has_audio": bool(a.get("has_audio")),
            "overlay": bool(beat.get("overlay")),
            "label": f"{beat['id']} ({beat['engine']})",
            **({"start": beat["start"]} if "start" in beat else {}),
        })
    return build_timeline_ops(sequence(beats), fps=int(mix["fps"]), **tracks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mix")
    ap.add_argument("--engine-spec", choices=sorted(ENGINES))
    ap.add_argument("--brand-pack", action="store_true",
                    help="print the resolved+validated brand pack (what the font install gates on)")
    ap.add_argument("--assets", help="json: {beat_id: {path, duration, media_id?}}")
    ap.add_argument("--out-dir")
    args = ap.parse_args()

    mix = json.loads(Path(args.mix).read_text(encoding="utf-8"))
    unknown = {b["engine"] for b in mix["beats"]} - ENGINES
    if unknown:
        raise SystemExit(f"unknown engine(s): {sorted(unknown)} — known: {sorted(ENGINES)}")

    base = Path(args.mix).resolve().parent
    if args.brand_pack:
        print(json.dumps(load_brand_pack(mix, base), ensure_ascii=False, indent=2))
        return 0

    if args.engine_spec:
        print(json.dumps(engine_spec(mix, args.engine_spec, base), ensure_ascii=False, indent=2))
        return 0

    if not (args.assets and args.out_dir):
        raise SystemExit("need --assets and --out-dir (or --engine-spec)")

    assets = json.loads(Path(args.assets).read_text(encoding="utf-8"))
    missing = [b["id"] for b in mix["beats"] if b["id"] not in assets]
    if missing:
        raise SystemExit(f"no rendered asset for beat(s): {missing}")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    plan = build_plan(mix, assets)
    ops = build_ops(mix, assets)
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "ops.json").write_text(json.dumps(ops, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "mix": mix["name"],
        "engines": sorted({b["engine"] for b in mix["beats"]}),
        "beats": [{"id": b["id"], "engine": b["engine"],
                   "seconds": round(plan["outputs"][0]["clips"][i]["end"]
                                    - plan["outputs"][0]["clips"][i]["start"], 3)}
                  for i, b in enumerate(mix["beats"])],
        "total_sec": plan["outputs"][0]["duration_target"],
        "freecut_ops": len(ops),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
