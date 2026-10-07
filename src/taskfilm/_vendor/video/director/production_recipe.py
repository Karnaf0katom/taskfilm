"""production_recipe.py — request → the RECIPE that produces it (which of OUR engines runs, in order).

`format_select` answers *what kind of video is this* (the planner exemplar to load). This module
answers the next question: **who builds it.** One row per creation route we can actually serve,
naming the engine, the concrete entry file, the compositor, and the doc to read before running.

Why it exists: we harvested HeyGen's HyperFrames workflow suite whole
(``hyperframes-harvest/skills/`` — Apache-2.0, 10 creation routes + their intent layer), and we own
five renderers of our own. Nothing in *our* code knew those routes existed, so they were a folder of
markdown instead of an option. This is the **bridge**, not a second brain:

- The HyperFrames route rows point at HeyGen's own ``routes/*.md`` + ``SKILL.md`` — the steps stay
  upstream's, we never paraphrase them (they refresh with ``npx hyperframes skills update``).
- Our native rows point at our own runnable entries, so a caller picking a route sees ALL the
  options — HyperFrames, Manim, edit-lane, generative, human — in one table.
- ``edit-lane`` stays the only compositor. No recipe grows one.

PURE + offline: data, string scoring, and path values. No I/O beyond ``Path`` arithmetic, no render,
no network. Scoring reuses ``format_select.keyword_hits`` — one matcher, two vocabularies.

CLI::

    python3 director/production_recipe.py --list
    python3 director/production_recipe.py "add hebrew subtitles to this cut" --inputs video
"""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from format_select import keyword_hits

# ``apps/video`` — every path in this module is relative to it, so the rows stay portable and the
# test suite can assert every one of them exists (a registry that rots silently is worse than none).
VIDEO_ROOT = Path(__file__).resolve().parent.parent

BOUNDARY_APPROVAL_VERSION = "production-recipe-boundary-approval/v1"
RENDER_PLAN_VERSION = "production-render-plan/v1"
HYPERFRAMES_VERSION = "0.8.16"

# The engines we can actually run today, each a real directory under ``apps/video``.
ENGINES: dict[str, str] = {
    "hyperframes-lane": "HTML/CSS/WebGL in headless Chrome (HeyGen's renderer, Cloud Build)",
    "motion-lane": "Manim — equations, geometry, plots, where the drawing IS the argument",
    "edit-lane": "the robot editor + the ONLY compositor (ffmpeg argv, captions, shorts)",
    "captions-service": "the sellable subtitle front door (tiers, quotes, jobs)",
    "director": "planning + generative-provider CLIs (Higgsfield, Vertex)",
    "grok-imagine": "generative shot batches",
    "mix": "the hand-off that lands a machine cut in FreeCut for a human",
    "freecut": "the screen — a human drags the timeline",
}

# Input kinds a caller can declare. ``requires`` gates on these; ``boosts`` only nudges.
INPUT_KINDS: frozenset[str] = frozenset(
    {"url", "text", "pr", "video", "audio", "image", "deck", "remotion"}
)


@dataclass(frozen=True)
class Recipe:
    """One producible route: what it is, who runs it, and what to read first."""

    id: str
    intent: str
    engine: str
    entry: str
    compositor: str
    route_doc: str
    requires: tuple[str, ...] = ()
    boosts: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    director_format: str | None = None
    planner_skill: str | None = None
    skill_doc: str | None = None
    alt_entries: tuple[str, ...] = ()
    notes: str = ""


def _hf(route: str) -> dict:
    """The two upstream docs for a HyperFrames route — the route brief and the full skill."""
    return {
        "route_doc": f"hyperframes-harvest/skills/hyperframes/references/routes/{route}.md",
        "skill_doc": f"hyperframes-harvest/skills/{route}/SKILL.md",
    }


# Keywords DISCRIMINATE, they do not describe. A word both rows would claim ("captions", "video")
# earns nothing and is left out; only the phrase that separates two neighbours is listed.
RECIPES: tuple[Recipe, ...] = (
    # ── HyperFrames routes (upstream owns the steps; we own the engine + the compositor) ────────
    Recipe(
        id="product_launch_video",
        intent="A website / product promoted or toured from its own visuals (URL, brief or script).",
        engine="hyperframes-lane",
        entry="hyperframes-lane/build_reel.py",
        compositor="edit-lane",
        requires=(),
        boosts=("url", "image"),
        keywords=("product launch", "launch video", "promote", "marketing video", "site tour",
                  "website", "landing page", "showcase", "product tour", "saas", "homepage",
                  "github review", "repository review", "repo review", "repo demo"),
        director_format="site_tour",
        planner_skill="exemplar_site_tour",
        alt_entries=("director/product_story.py",),
        notes="SaaS demos and source-based GitHub reviews can prepare capture and multi-engine "
              "story briefs with --product-story; this does not execute the recipe.",
        **_hf("product-launch-video"),
    ),
    Recipe(
        id="faceless_explainer",
        intent="Explain a topic from arbitrary text — no product, no URL; every visual is invented.",
        engine="hyperframes-lane",
        entry="hyperframes-lane/build_reel.py",
        compositor="edit-lane",
        requires=(),
        boosts=("text",),
        keywords=("faceless", "explainer", "explain", "how it works", "tutorial", "educational",
                  "concept", "walkthrough", "teach"),
        director_format="explainer",
        planner_skill="exemplar_explainer",
        **_hf("faceless-explainer"),
    ),
    Recipe(
        id="pr_to_video",
        intent="A GitHub pull request → changelog / feature-reveal / fix explainer, read via `gh`.",
        engine="hyperframes-lane",
        entry="hyperframes-lane/build_reel.py",
        compositor="edit-lane",
        requires=("pr",),
        boosts=("pr",),
        keywords=("pull request", "merge request", "changelog", "release notes", "the diff",
                  "code change", "refactor", "commit"),
        director_format="explainer",
        planner_skill="exemplar_explainer",
        notes="Input is a code change, not a website — no capture step.",
        **_hf("pr-to-video"),
    ),
    Recipe(
        id="embedded_captions",
        intent="Designed / kinetic captions on existing talking-head footage; the cut is untouched.",
        engine="hyperframes-lane",
        entry="hyperframes-lane/captions_html.py",
        compositor="edit-lane",
        requires=("video",),
        boosts=("video",),
        keywords=("kinetic caption", "embedded caption", "caption behind", "cinematic caption",
                  "caption style", "caption dna", "karaoke", "word by word", "word-by-word"),
        alt_entries=("edit-lane/ass_captions.py",),
        notes="Alpha master is --format mov (ProRes 4444); webm has NO alpha. libass stays the "
              "cheap backend — never run both, the track prints twice.",
        **_hf("embedded-captions"),
    ),
    Recipe(
        id="talking_head_recut",
        intent="Package an interview / podcast with graphic overlays: lower-thirds, callouts, PiP.",
        engine="hyperframes-lane",
        entry="hyperframes-lane/build_reel.py",
        compositor="edit-lane",
        requires=("video",),
        boosts=("video",),
        keywords=("lower third", "lower-third", "recut", "pull quote", "pull-quote", "b-roll",
                  "overlay", "podcast", "interview", "side panel", "callout"),
        notes="Overlays render transparent and ride Output.overlays; edit-lane composites.",
        **_hf("talking-head-recut"),
    ),
    Recipe(
        id="motion_graphics",
        intent="A short unnarrated design piece (<10s): kinetic type, stat hit, logo sting, tweet.",
        engine="hyperframes-lane",
        entry="hyperframes-lane/build_reel.py",
        compositor="edit-lane",
        requires=(),
        keywords=("motion graphic", "logo sting", "logo reveal", "kinetic type", "kinetic typography",
                  "stat", "sting", "bumper", "animated tweet", "headline"),
        notes="No director format — there is no exemplar for an unnarrated graphic; the brief IS "
              "the spec. Transparent output is supported (overlay, not a standalone cut).",
        **_hf("motion-graphics"),
    ),
    Recipe(
        id="music_to_video",
        intent="A track (given or generated) → a beat-synced lyric / slideshow / kinetic promo.",
        engine="hyperframes-lane",
        entry="hyperframes-lane/build_reel.py",
        compositor="edit-lane",
        requires=(),
        boosts=("audio",),
        keywords=("music video", "lyric video", "beat-synced", "beat synced", "song", "track",
                  "soundtrack", "bpm", "on the beat"),
        director_format="music_video",
        planner_skill="exemplar_music_video",
        alt_entries=("edit-lane/beat_detect.py",),
        notes="Beat grid can come from our own edit-lane/beat_detect.py rather than re-detecting.",
        **_hf("music-to-video"),
    ),
    Recipe(
        id="slideshow",
        intent="A navigable deck — fragments, branching, hotspots, presenter mode. Not a render.",
        engine="hyperframes-lane",
        entry="hyperframes-lane/build_reel.py",
        compositor="none",
        requires=(),
        boosts=("deck", "text"),
        keywords=("slideshow", "slide show", "deck", "presentation", "pitch deck", "slides",
                  "presenter mode"),
        director_format="slideshow",
        planner_skill="exemplar_slideshow",
        notes="Output is an interactive deck, so nothing reaches the compositor.",
        **_hf("slideshow"),
    ),
    Recipe(
        id="remotion_to_hyperframes",
        intent="Port an existing Remotion (React) composition's source to HyperFrames HTML.",
        engine="hyperframes-lane",
        entry="hyperframes-lane/build_reel.py",
        compositor="none",
        requires=("remotion",),
        boosts=("remotion",),
        keywords=("remotion", "port the composition", "migrate the composition"),
        alt_entries=("edit-lane/caption_remotion/props_builder.py",),
        notes="One-way migration. Our own deferred Remotion caption backend "
              "(edit-lane/caption_remotion/) is the first candidate: its node render was never "
              "built, and the HTML lane already renders alpha in Cloud Build.",
        **_hf("remotion-to-hyperframes"),
    ),
    Recipe(
        id="general_video",
        intent="Anything else — longer, multi-scene, sizzle, title card, freeform. The fallback.",
        engine="hyperframes-lane",
        entry="hyperframes-lane/build_reel.py",
        compositor="edit-lane",
        requires=(),
        keywords=("sizzle", "brand film", "title card", "multi-scene", "companion mode"),
        planner_skill="director_plan",
        notes="director_format is None on purpose: call format_select.recommend_format(brief).",
        **_hf("general-video"),
    ),
    # ── Ours — the options that already existed, listed so a router sees the whole estate ───────
    Recipe(
        id="shorts_clipper",
        intent="Long video → vertical shorts: moment finding, smart crop, word-snapped cuts.",
        engine="edit-lane",
        entry="edit-lane/scripts/make_shorts.py",
        compositor="edit-lane",
        requires=("video",),
        boosts=("video",),
        keywords=("shorts", "clip it", "clips", "opusclip", "viral moment", "repurpose", "tiktok",
                  "reels", "best moments", "highlights"),
        route_doc="docs/archive/OPUSCLIP-HANDOFF.md",
        alt_entries=("edit-lane/scripts/make_reframe.py",),
        notes="Ours, not HeyGen's — HyperFrames has no moment finder.",
    ),
    Recipe(
        id="subtitle_localize",
        intent="Translate a finished cut into broadcast-timed subtitles in another language.",
        engine="edit-lane",
        entry="edit-lane/subtitle_localize.py",
        compositor="edit-lane",
        requires=("video",),
        boosts=("video",),
        keywords=("translate", "translation", "localize", "localise", "hebrew", "arabic", "spanish",
                  "french", "portuguese", "russian", "srt", "vtt", "foreign language"),
        route_doc="captions-service/README.md",
        alt_entries=("captions-service/lane.py", "edit-lane/subtitle_cast.py"),
        notes="Gendered languages need the cast map (subtitle_cast.py) BEFORE translating.",
    ),
    Recipe(
        id="manim_proof",
        intent="An equation, geometric construction, plot with real axes, vector field, 3D math.",
        engine="motion-lane",
        entry="motion-lane/compose.py",
        compositor="edit-lane",
        requires=(),
        keywords=("equation", "formula", "geometry", "geometric", "derivation", "vector field",
                  "axes", "theorem", "proof", "latex", "manim"),
        route_doc="motion-lane/README.md",
        notes="HyperFrames ships NO math typesetting (zero KaTeX/LaTeX) — this is the one beat "
              "kind it cannot serve. Everything else it usually does better.",
    ),
    Recipe(
        id="generative_shots",
        intent="AI-generated footage / b-roll shots to feed a cut (Higgsfield, Grok Imagine).",
        engine="director",
        entry="director/higgsfield_cli.py",
        compositor="edit-lane",
        requires=(),
        boosts=("image",),
        keywords=("generate footage", "generated shot", "b roll", "ai video", "seedance", "kling",
                  "veo", "image to video", "generative"),
        route_doc="director/HIGGSFIELD-CLI-INTEGRATION.md",
        alt_entries=("grok-imagine/grok_gen.py",),
        notes="Costs credits — a paid provider, unlike every other row here.",
    ),
    Recipe(
        id="human_finish",
        intent="Hand a machine cut to a human on the FreeCut timeline to disagree with it.",
        engine="mix",
        entry="mix/land_in_freecut.py",
        compositor="freecut",
        requires=(),
        boosts=("video",),
        keywords=("edit it myself", "by hand", "manually", "timeline", "freecut", "fine tune",
                  "fine-tune", "tweak the cut"),
        route_doc="docs/architecture/EDITLANE-FREECUT-BORDER-BRIEF.md",
        notes="The border: edit-lane decides, FreeCut lets a human disagree.",
    ),
)

BY_ID: dict[str, Recipe] = {r.id: r for r in RECIPES}

FALLBACK_ID = "general_video"


def recipes() -> tuple[Recipe, ...]:
    """Every producible route, registry order (HyperFrames routes first, then ours)."""
    return RECIPES


def get(recipe_id: str) -> Recipe:
    """Look up one recipe. Raises ``KeyError`` with the valid ids on a typo."""
    try:
        return BY_ID[recipe_id]
    except KeyError:
        raise KeyError(f"unknown recipe {recipe_id!r}; known: {sorted(BY_ID)}") from None


def _normalize_inputs(inputs) -> frozenset[str]:
    """Lower-cased, known input kinds only — an unknown kind is dropped, never an error."""
    return frozenset(str(k).strip().lower() for k in (inputs or ()) if str(k).strip().lower() in INPUT_KINDS)


def eligible(inputs=()) -> tuple[Recipe, ...]:
    """Recipes whose hard ``requires`` are satisfied.

    An empty / unknown ``inputs`` declares nothing, so nothing is gated out — the brief alone
    decides. Declaring inputs is what makes routing sharp.
    """
    kinds = _normalize_inputs(inputs)
    if not kinds:
        return RECIPES
    return tuple(r for r in RECIPES if set(r.requires) <= kinds)


def score_recipes(brief: str, *, inputs=()) -> list[tuple[str, int]]:
    """``(recipe_id, score)`` for every eligible recipe, highest first (deterministic).

    Score = keyword hits + 2 per satisfied ``requires`` kind + 1 per ``boosts`` kind present.
    The input bonuses are what let "add hebrew subtitles" with a video in hand beat a generic
    keyword tie.
    """
    norm = str(brief or "").lower()
    kinds = _normalize_inputs(inputs)
    scored: list[tuple[str, int]] = []
    for r in eligible(kinds):
        score = keyword_hits(norm, list(r.keywords))
        if kinds:
            score += 2 * len(set(r.requires) & kinds)
            score += len(set(r.boosts) & kinds)
        scored.append((r.id, score))
    return sorted(scored, key=lambda kv: kv[1], reverse=True)


def select_recipe(brief: str, *, inputs=(), default: str = FALLBACK_ID) -> str:
    """Pick one recipe id for ``brief``.

    Zero score or a tie at the top → ``default`` (``general_video``), the same discipline
    ``format_select.recommend_format`` uses: a tie means we genuinely do not know, and HeyGen's own
    front door treats general-video as the route that asks. Always returns a valid id.
    """
    fallback = default if default in BY_ID else FALLBACK_ID
    scores = score_recipes(brief, inputs=inputs)
    if not scores or scores[0][1] <= 0:
        return fallback
    if len(scores) > 1 and scores[0][1] == scores[1][1]:
        return fallback
    return scores[0][0]


def resolve_path(rel: str) -> Path:
    """A registry path value → an absolute path under ``apps/video`` (no existence check)."""
    return VIDEO_ROOT / rel


def plan(recipe_id: str, *, brief: str = "") -> dict:
    """The runnable shape of a recipe: read these, run this, composite there.

    ``format`` resolves through ``format_select`` when the recipe pins none (``general_video``),
    so the caller always gets a planner exemplar to load.
    """
    r = get(recipe_id)
    fmt = r.director_format
    if fmt is None and brief and r.planner_skill == "director_plan":
        from format_select import recommend_format

        fmt = recommend_format(brief)
    return {
        "recipe": r.id,
        "intent": r.intent,
        "read_first": [p for p in (r.route_doc, r.skill_doc) if p],
        "engine": r.engine,
        "engine_is": ENGINES[r.engine],
        "entry": r.entry,
        "alt_entries": list(r.alt_entries),
        "compositor": r.compositor,
        "director_format": fmt,
        "planner_skill": r.planner_skill,
        "notes": r.notes,
    }


class RecipeBoundaryError(ValueError):
    """A request is not authorized to cross the offline recipe boundary."""


def _boundary_fail(path: str, message: str) -> None:
    raise RecipeBoundaryError(f"{path}: {message}")


def _boundary_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _boundary_fail(path, "must be an object")
    return value


def _boundary_fields(value: Mapping[str, Any], path: str, expected: set[str]) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        _boundary_fail(path, f"missing fields {missing}")
    if unknown:
        _boundary_fail(path, f"unknown fields {unknown}")


def _boundary_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _boundary_fail(path, "must be a non-empty string")
    return value.strip()


def _boundary_time(value: Any, path: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _boundary_text(value, path)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            _boundary_fail(path, "must be an ISO-8601 timestamp")
            raise AssertionError from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _boundary_fail(path, "must include a timezone")
    return parsed.astimezone(timezone.utc)


def _boundary_rows(value: Any, path: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        _boundary_fail(path, "must be a list")
    rows: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        rows.append(_boundary_mapping(item, f"{path}[{index}]"))
    return rows


def _rows_by_id(rows: Sequence[Mapping[str, Any]], path: str, fields: set[str]) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        row_path = f"{path}[{index}]"
        _boundary_fields(row, row_path, fields)
        row_id = _boundary_text(row["id"], f"{row_path}.id")
        if row_id in indexed:
            _boundary_fail(f"{row_path}.id", "must be unique")
        indexed[row_id] = row
    return indexed


def _match_boundary_assets(request: Mapping[str, Any], approval: Mapping[str, Any]) -> None:
    source_rows = _rows_by_id(
        _boundary_rows(approval["sources"], "approval.sources"),
        "approval.sources",
        {"id", "asset_ref", "rights_evidence_ref"},
    )
    expected_sources = {str(row["id"]): row for row in request["sources"]}
    for source_id, source in expected_sources.items():
        path = f"approval.sources.{source_id}"
        if source_id not in source_rows:
            _boundary_fail(path, "missing fresh asset and rights confirmation")
        confirmed = source_rows[source_id]
        if confirmed["asset_ref"] != source["uri"]:
            _boundary_fail(f"{path}.asset_ref", "does not match request source uri")
        if confirmed["rights_evidence_ref"] != source["rights"]["evidence_ref"]:
            _boundary_fail(
                f"{path}.rights_evidence_ref",
                "does not match request source rights.evidence_ref",
            )
    extra_sources = sorted(set(source_rows) - set(expected_sources))
    if extra_sources:
        _boundary_fail("approval.sources", f"unknown source ids {extra_sources}")

    reference_rows = _rows_by_id(
        _boundary_rows(approval["references"], "approval.references"),
        "approval.references",
        {"id", "asset_ref", "approval_ref"},
    )
    expected_references = {str(row["id"]): row for row in request["references"]}
    for reference_id, reference in expected_references.items():
        path = f"approval.references.{reference_id}"
        if reference_id not in reference_rows:
            _boundary_fail(path, "missing fresh asset and approval confirmation")
        confirmed = reference_rows[reference_id]
        if confirmed["asset_ref"] != reference["uri"]:
            _boundary_fail(f"{path}.asset_ref", "does not match request reference uri")
        if confirmed["approval_ref"] != reference["approval_ref"]:
            _boundary_fail(
                f"{path}.approval_ref", "does not match request reference approval_ref"
            )
    extra_references = sorted(set(reference_rows) - set(expected_references))
    if extra_references:
        _boundary_fail("approval.references", f"unknown reference ids {extra_references}")


def _authorize_request(request: Any, approval_value: Any, checked_at: datetime | str | None):
    # Lazy imports avoid a module cycle: production_request validates recipe ids through this module.
    import production_request

    raw_request = request.request if isinstance(request, production_request.ValidatedProductionRequest) else request
    validated = production_request.validate_production_request(raw_request)
    if validated.request["recipe"]["id"] != "product_launch_video":
        _boundary_fail("request.recipe.id", "must be 'product_launch_video' for this render plan")
    if validated.request["cost"]["status"] != "unknown":
        _boundary_fail("request.cost.status", "must remain 'unknown' for an argv-only plan")
    if validated.request["approvals"]["spend"] is not None:
        _boundary_fail("request.approvals.spend", "must remain null for an argv-only plan")

    approval = _boundary_mapping(approval_value, "approval")
    _boundary_fields(
        approval,
        "approval",
        {
            "schema_version",
            "prepared_request_digest",
            "content_approval_ref",
            "approved_at",
            "expires_at",
            "sources",
            "references",
        },
    )
    if approval["schema_version"] != BOUNDARY_APPROVAL_VERSION:
        _boundary_fail("approval.schema_version", f"must equal {BOUNDARY_APPROVAL_VERSION!r}")
    if approval["prepared_request_digest"] != validated.request_digest:
        _boundary_fail("approval.prepared_request_digest", "does not match the request at this boundary")

    now = _boundary_time(checked_at or datetime.now(timezone.utc), "checked_at")
    approved_at = _boundary_time(approval["approved_at"], "approval.approved_at")
    expires_at = _boundary_time(approval["expires_at"], "approval.expires_at")
    if approved_at > now:
        _boundary_fail("approval.approved_at", "cannot be in the future")
    if approved_at.date() != now.date():
        _boundary_fail("approval.approved_at", "must be dated today at recipe boundary")
    if expires_at <= now:
        _boundary_fail("approval.expires_at", "stale at recipe boundary")
    if expires_at <= approved_at:
        _boundary_fail("approval.expires_at", "must be later than approval.approved_at")

    _match_boundary_assets(validated.request, approval)
    authorized_request = copy.deepcopy(validated.request)
    authorized_request["approvals"]["content"] = _boundary_text(
        approval["content_approval_ref"], "approval.content_approval_ref"
    )
    authorized = production_request.validate_production_request(authorized_request)
    return validated, authorized, {
        "schema_version": approval["schema_version"],
        "prepared_request_digest": validated.request_digest,
        "authorized_request_digest": authorized.request_digest,
        "content_approval_ref": authorized.request["approvals"]["content"],
        "approved_at": approved_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "source_ids": [row["id"] for row in authorized.request["sources"]],
        "reference_ids": [row["id"] for row in authorized.request["references"]],
    }


def _canvas(aspect_ratio: str) -> tuple[int, int]:
    return {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
    }.get(aspect_ratio, (1920, 1080))


def _shot_shape(output_kind: str, duration_cap: float) -> tuple[int, float]:
    desired = {"landscape_video": 3, "vertical_short": 2, "square_video": 1}.get(output_kind, 1)
    if duration_cap < 4:
        _boundary_fail("request.limits.max_duration_seconds", "must be at least 4 for Veo footage")
    count = max(1, min(desired, int(duration_cap // 4)))
    duration = 6.0 if count * 6 <= duration_cap else 4.0
    return count, duration


def _raw_book_prompt(request: Mapping[str, Any], output: Mapping[str, Any], beat: int, total: int) -> str:
    movements = (
        "Open on the supplied cover identity already in motion, with a controlled cinematic push in",
        "Reveal a tactile detail from the supplied book assets while the camera tracks laterally",
        "Resolve on a clean, legible packshot based on the supplied cover, with no invented cover text",
    )
    movement = movements[min(beat - 1, len(movements) - 1)]
    return (
        f"{request['brief']} Create visual beat {beat} of {total} for output {output['id']} "
        f"in {output['aspect_ratio']}. {movement}. Use only the supplied source identities; "
        "do not invent quotations, awards, logos, author likeness, or claims."
    )


def _render_output(request: Mapping[str, Any], output: Mapping[str, Any], root: Path) -> dict[str, Any]:
    import ipe

    output_id = str(output["id"])
    output_root = root / output_id
    reel_path = output_root / "reel.json"
    project = output_root / "hyperframes"
    rendered = output_root / f"{output_id}.mp4"
    width, height = _canvas(str(output["aspect_ratio"]))
    count, duration = _shot_shape(
        str(output["kind"]), float(request["limits"]["max_duration_seconds"])
    )
    palette = request.get("_brand_palette", {})
    beats: list[dict[str, Any]] = []
    prompt_receipts: list[dict[str, Any]] = []
    for beat_number in range(1, count + 1):
        raw_prompt = _raw_book_prompt(request, output, beat_number, count)
        directed = ipe.enforce_for_model(
            raw_prompt, "veo_3_1", genre="ad", has_performer=False
        )
        slug = f"{output_id}-{beat_number:02d}"
        ipe_argv = [
            "python3",
            "director/ipe.py",
            "enforce",
            "--genre",
            "ad",
            "--model",
            "veo_3_1",
            "--no-performer",
            "--json",
            raw_prompt,
        ]
        receipt = directed.as_dict()
        prompt_receipts.append(
            {
                "beat": beat_number,
                "raw_prompt": raw_prompt,
                "ipe_argv": ipe_argv,
                "ipe_result": receipt,
            }
        )
        beats.append(
            {
                "footage": f"shots/{slug}.mp4",
                "duration": duration,
                "fit": "cover",
                "generate": {
                    "slug": slug,
                    "model": "veo_3_1",
                    "prompt": directed.prompt,
                    "negative_prompt": ", ".join(directed.avoid) or None,
                    "aspect": output["aspect_ratio"],
                    "resolution": "1080p",
                    "duration": duration,
                },
            }
        )
    reel = {
        "name": output_id,
        "fps": 30,
        "width": width,
        "height": height,
        "brand": {
            "bg": palette.get("bg", "#080B12"),
            "ink": palette.get("ink", "#E8ECF7"),
            "accent": palette.get("accent", "#7AA2FF"),
        },
        "beats": beats,
    }
    commands = [
        {
            "step": "generation_dry_run",
            "cwd": str(VIDEO_ROOT),
            "argv": ["python3", "hyperframes-lane/render_shots.py", str(reel_path), str(project)],
            "provider_call": False,
            "spend": False,
        },
        {
            "step": "scaffold",
            "cwd": str(output_root),
            "argv": [
                "npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "init", "hyperframes",
                "--non-interactive", "--example", "blank",
            ],
        },
        {
            "step": "build_composition",
            "cwd": str(VIDEO_ROOT),
            "argv": ["python3", "hyperframes-lane/build_reel.py", str(reel_path), str(project)],
        },
        {
            "step": "lint",
            "cwd": str(project),
            "argv": ["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "lint"],
        },
        {
            "step": "check",
            "cwd": str(project),
            "argv": ["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "check"],
        },
        {
            "step": "render",
            "cwd": str(project),
            "argv": [
                "npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "render", "-o", str(rendered)
            ],
        },
    ]
    return {
        "id": output_id,
        "kind": output["kind"],
        "aspect_ratio": output["aspect_ratio"],
        "reel_spec_path": str(reel_path),
        "reel_spec": reel,
        "project_dir": str(project),
        "rendered_path": str(rendered),
        "prompts": prompt_receipts,
        "argv": commands,
    }


def plan_request(
    request: Any,
    approval: Mapping[str, Any],
    *,
    artifact_root: str | Path,
    checked_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Authorize one request and return its complete offline recipe/render plan.

    This is the existing recipe planner's request boundary. It revalidates the request, binds a
    same-day approval to its exact digest, re-matches every asset and rights reference, and passes
    every generation prompt through :mod:`ipe`. It returns data and argv only: no subprocess,
    provider, renderer, network, filesystem write, or spend occurs here.
    """

    prepared, authorized, approval_receipt = _authorize_request(request, approval, checked_at)
    route = plan(authorized.request["recipe"]["id"], brief=authorized.request["brief"])
    request_for_plan = copy.deepcopy(authorized.request)
    request_for_plan["_brand_palette"] = copy.deepcopy(
        authorized.brand_identity.get("palette", {})
    )
    root = Path(artifact_root)
    outputs = [_render_output(request_for_plan, output, root) for output in authorized.request["outputs"]]
    return {
        "schema_version": RENDER_PLAN_VERSION,
        "phase": "render_plan",
        "execution": "planned_only",
        "request_id": authorized.request["request_id"],
        "prepared_request_digest": prepared.request_digest,
        "authorized_request_digest": authorized.request_digest,
        "approval_boundary": approval_receipt,
        "recipe": route,
        "compositor": route["compositor"],
        "outputs": outputs,
        "provider_calls": 0,
        "spend_authorized": False,
        "cost_status": authorized.request["cost"]["status"],
        "proof": "pure_argv_plan_only",
    }


def plan_product_story(request: Mapping[str, Any], story: Mapping[str, Any], *, repo_pack=None) -> dict:
    """Prepare a product story through the existing recipe capability, without dispatch."""
    from product_story import build_product_story

    return build_product_story(request, story, repo_pack=repo_pack)


def _main(argv: list[str]) -> int:
    args = list(argv[1:])
    if args and args[0] == "--product-story":
        from product_story import main as product_story_main

        return product_story_main(args[1:])
    if not args or args[0] in {"--list", "-l"}:
        for r in RECIPES:
            req = ",".join(r.requires) or "-"
            print(f"{r.id:<24} {r.engine:<17} needs={req:<9} {r.intent}")
        return 0
    inputs: list[str] = []
    if "--inputs" in args:
        i = args.index("--inputs")
        inputs = [k for k in args[i + 1].split(",") if k] if i + 1 < len(args) else []
        del args[i : i + 2]
    brief = " ".join(args)
    print(json.dumps(plan(select_recipe(brief, inputs=inputs), brief=brief), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
