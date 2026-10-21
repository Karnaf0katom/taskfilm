"Load and validate the brand identity used by story planning."

from __future__ import annotations

import json

from pathlib import Path

HERE = Path(__file__).resolve().parent

PALETTE_KEYS = ("bg", "primary", "secondary", "accent", "ink", "mute", "card")

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
