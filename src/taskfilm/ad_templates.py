"""Declarative ad compositions and deterministic, inspectable selection.

External templates use exactly the same geometry contract as built-ins. They
cannot inject HTML, CSS or JavaScript; the renderer owns all markup and motion.
Coordinates are normalized to the canvas, not to a source recording.
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

FORMATS = {"portrait": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}
# Keep product, logo and copy away from common social player controls/captions.
SAFE = {"portrait": [0.06, 0.09, 0.82, 0.70],
        "landscape": [0.05, 0.06, 0.90, 0.86],
        "square": [0.06, 0.07, 0.86, 0.80]}


def _frame(copy_box, media, size, *, logo=None, align="left", radius=20):
    return {"copy": copy_box, "media": media, "logo": logo or [0.07, 0.10, 0.27, 0.045],
            "headline_size": size, "align": align, "radius": radius}


def _family(ident, name, description, products, styles, portrait, landscape, square):
    return {"schema": "taskfilm-ad-template/v1", "id": ident, "name": name,
            "description": description, "products": products.split(), "styles": styles.split(),
            "frames": {"portrait": portrait, "landscape": landscape, "square": square}}


BUILTINS = [
    _family("hero-stage", "Hero stage", "A large centered product below a concise promise.",
            "saas booking productivity", "clear calm product",
            _frame([.07,.19,.80,.16], [.07,.39,.80,.37], 78),
            _frame([.14,.19,.72,.20], [.14,.43,.72,.46], 84, align="center"),
            _frame([.07,.19,.80,.20], [.07,.43,.80,.41], 65)),
    _family("editorial-split", "Editorial split", "An asymmetric editorial column beside the evidence.",
            "saas finance analytics", "editorial premium clear",
            _frame([.07,.19,.52,.24], [.25,.47,.62,.29], 76),
            _frame([.06,.28,.31,.54], [.42,.18,.52,.69], 83),
            _frame([.07,.22,.32,.59], [.44,.23,.43,.59], 54)),
    _family("proof-strip", "Proof strip", "Wide evidence first, with a strong caption underneath.",
            "analytics finance developer", "direct proof product",
            _frame([.07,.59,.80,.17], [.07,.20,.80,.34], 72),
            _frame([.07,.73,.86,.17], [.07,.19,.86,.49], 65),
            _frame([.07,.66,.80,.18], [.07,.20,.80,.40], 56)),
    _family("detail-poster", "Detail poster", "A narrow, tall detail and a compact side note.",
            "mobile booking wellness", "bold premium product",
            _frame([.57,.32,.30,.38], [.07,.20,.44,.56], 57),
            _frame([.57,.32,.36,.40], [.12,.18,.37,.70], 86),
            _frame([.55,.30,.32,.47], [.07,.20,.42,.64], 57)),
    _family("quiet-card", "Quiet card", "Small centered evidence with generous whitespace and centered copy.",
            "wellness lifestyle booking", "calm minimal premium",
            _frame([.13,.55,.68,.20], [.20,.22,.54,.27], 67, align="center", radius=30),
            _frame([.53,.30,.36,.43], [.13,.26,.33,.48], 75, align="center", radius=30),
            _frame([.14,.59,.66,.24], [.22,.22,.50,.30], 58, align="center", radius=30)),
    _family("caption-rail", "Caption rail", "A product-dominant panel with a compact adjacent caption rail.",
            "developer saas productivity", "technical direct proof",
            _frame([.07,.20,.80,.10], [.07,.34,.80,.42], 53, radius=4),
            _frame([.74,.25,.19,.58], [.06,.18,.63,.70], 57, radius=4),
            _frame([.07,.20,.80,.12], [.07,.36,.80,.48], 47, radius=4)),
    _family("type-led", "Type led", "A typographic statement with a small supporting product inset.",
            "lifestyle productivity wellness", "bold editorial minimal",
            _frame([.07,.20,.80,.30], [.48,.55,.39,.20], 105, radius=8),
            _frame([.07,.24,.53,.60], [.67,.50,.26,.33], 129, radius=8),
            _frame([.07,.21,.80,.34], [.51,.61,.36,.23], 86, radius=8)),
    _family("brand-close", "Brand close", "A real logo lockup, a centered call to action and optional proof thumbnail.",
            "booking wellness saas lifestyle", "brand calm minimal",
            _frame([.12,.37,.70,.21], [.33,.63,.28,.13], 74,
                   logo=[.22,.20,.50,.10], align="center"),
            _frame([.22,.39,.56,.23], [.40,.68,.20,.21], 90,
                   logo=[.33,.16,.34,.13], align="center"),
            _frame([.12,.39,.70,.23], [.33,.68,.28,.16], 65,
                   logo=[.22,.20,.50,.12], align="center")),
]


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_template(template: dict) -> dict:
    """Reject malformed/unsafe geometry, including overlapping content boxes."""
    keys = {"schema", "id", "name", "description", "products", "styles", "frames"}
    if not isinstance(template, dict) or set(template) != keys:
        raise ValueError("template must contain exactly " + ", ".join(sorted(keys)))
    if template["schema"] != "taskfilm-ad-template/v1":
        raise ValueError("unsupported template schema")
    if not isinstance(template["id"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", template["id"]):
        raise ValueError("invalid template id")
    for key in ("name", "description"):
        if not isinstance(template[key], str) or not template[key].strip():
            raise ValueError(f"template {key} must be nonempty text")
    for key in ("products", "styles"):
        if not isinstance(template[key], list) or any(not isinstance(v, str) or not v for v in template[key]):
            raise ValueError(f"template {key} must be a list of tags")
    if not isinstance(template["frames"], dict) or set(template["frames"]) != set(FORMATS):
        raise ValueError("template must define portrait, landscape and square frames")
    for fmt, frame in template["frames"].items():
        if not isinstance(frame, dict) or set(frame) != {"copy", "media", "logo", "headline_size", "align", "radius"}:
            raise ValueError(f"{fmt}: invalid frame interface")
        if frame["align"] not in ("left", "center"):
            raise ValueError("align must be left or center")
        if not _number(frame["headline_size"]) or not 40 <= frame["headline_size"] <= 160:
            raise ValueError("headline_size must be 40..160 canvas pixels")
        if not _number(frame["radius"]) or not 0 <= frame["radius"] <= 40:
            raise ValueError("radius must be 0..40 canvas pixels")
        sx, sy, sw, sh = SAFE[fmt]
        boxes = []
        for name in ("copy", "media", "logo"):
            box = frame[name]
            if not isinstance(box, list) or len(box) != 4 or not all(_number(v) for v in box):
                raise ValueError(f"{fmt}.{name}: expected [x,y,width,height]")
            x,y,w,h = box
            if w <= 0 or h <= 0 or x < sx-1e-8 or y < sy-1e-8 or x+w > sx+sw+1e-8 or y+h > sy+sh+1e-8:
                raise ValueError(f"{fmt}.{name}: outside mobile-safe content bounds")
            for previous in boxes:
                a,b,c,d = previous
                if min(x+w,a+c)-max(x,a) > 1e-8 and min(y+h,b+d)-max(y,b) > 1e-8:
                    raise ValueError(f"{fmt}.{name}: content boxes overlap")
            boxes.append(box)
    return copy.deepcopy(template)


def templates(paths=()) -> dict[str, dict]:
    registry = {t["id"]: validate_template(t) for t in BUILTINS}
    for path in paths:
        template = validate_template(json.loads(Path(path).read_text()))
        if template["id"] in registry:
            raise ValueError(f"duplicate template id: {template['id']}")
        registry[template["id"]] = template
    return registry


def rank_templates(registry, *, product="saas", style="clear", history=(), used=(), has_media=True):
    """Stable scores; history oldest first. Ratings apply to matching product/style.

    Repetition penalties dominate a matching tag. A single good rating cannot
    overpower an immediately repeated layout. Explicit author choice always wins.
    """
    ranked = []
    for ident, template in registry.items():
        fit = (4 if product in template["products"] else 0) + (3 if style in template["styles"] else 0)
        feedback = [r["rating"] for r in history if ident in r.get("templates", [])
                    and r.get("rating") is not None
                    and r.get("product") == product and r.get("style") == style]
        preference = (sum(feedback)/len(feedback)-3)*1.5 if feedback else 0
        recent = sum((i+1)*1.5 for i,r in enumerate(list(history)[-5:]) if ident in r.get("templates", []))
        local = sum(5 for t in used if t == ident) + (12 if used and used[-1] == ident else 0)
        medium = (9 if ident == "brand-close" else 4 if ident == "type-led" else -5) if not has_media else (-5 if ident == "brand-close" else 0)
        ranked.append({"id": ident, "score": round(fit+preference-recent-local+medium, 3),
                       "fit": fit, "feedback": round(preference,3), "recent_penalty": recent, "scene_penalty": local})
    return sorted(ranked, key=lambda r: (-r["score"], r["id"]))
