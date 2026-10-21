"The product-story recipe supported by the standalone CLI."

from __future__ import annotations

from dataclasses import dataclass

ENGINES = {"hyperframes-lane": "Editable HTML motion rendered with HyperFrames"}

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

RECIPES: tuple[Recipe, ...] = (
    Recipe(
        id='product_launch_video',
        intent='A website / product promoted or toured from its own visuals (URL, brief or script).',
        engine='hyperframes-lane',
        entry='hyperframes-lane/product-motion/build.py',
        compositor='hyperframes-lane',
        requires=(),
        boosts=('url', 'image'),
        keywords=('product launch', 'launch video', 'promote', 'marketing video', 'site tour', 'website', 'landing page', 'showcase', 'product tour', 'saas', 'homepage', 'github review', 'repository review', 'repo review', 'repo demo'),
        director_format='site_tour',
        planner_skill='exemplar_site_tour',
        alt_entries=('director/product_story.py',),
        notes='Story planning only. Capture a real task, author a composition, then render and review it.',
        route_doc='../../../docs/WORKFLOWS.md',
        skill_doc='../../skills/taskfilm-video/SKILL.md',
    ),
)

BY_ID: dict[str, Recipe] = {r.id: r for r in RECIPES}

def get(recipe_id: str) -> Recipe:
    """Look up one recipe. Raises ``KeyError`` with the valid ids on a typo."""
    try:
        return BY_ID[recipe_id]
    except KeyError:
        raise KeyError(f"unknown recipe {recipe_id!r}; known: {sorted(BY_ID)}") from None

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
