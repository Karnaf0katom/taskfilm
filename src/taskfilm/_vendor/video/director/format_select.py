"""format_select.py — brief tone → director video FORMAT (auto-picks the planner exemplar).

The planner composes ``skills/director_plan/SKILL.md`` + an optional ``skills/exemplar_<format>/SKILL.md``
layer (``knowledge.compose_skill``). When a caller leaves ``format=None`` no exemplar loads, so the
format-specific know-how goes unused. This maps a brief to one of the director's CONTENT exemplar
formats so ``plan_video`` can fill that gap. Pure, offline; mirrors ``caption_dna_select``.

Scope: the CONTENT formats that have exemplars (``ad`` · ``explainer`` · ``ugc`` · ``story`` ·
``music_video`` · ``slideshow`` · ``site_tour``). The artefact skills (beatboard / storyboard /
critique) are internal and never tone-selected. Unknown / neutral briefs fall back to ``explainer``.
"""

from __future__ import annotations

import re


FORMAT_REGISTRY: dict[str, dict] = {
    "ad": {
        "keywords": ["ad", "advert", "commercial", "promo", "promote", "campaign", "sale", "offer",
                     "product launch", "brand", "sell", "conversion"],
    },
    "explainer": {
        "keywords": ["explainer", "how-to", "how to", "tutorial", "educational", "explain", "guide",
                     "walkthrough", "concept", "onboarding", "demo", "learn"],
    },
    "ugc": {
        "keywords": ["ugc", "testimonial", "review", "authentic", "talking head", "talking-head",
                     "creator", "unboxing", "reaction", "vlog", "selfie", "handheld"],
    },
    "talking_head_explainer": {
        # A specialization of ``explainer``: keywords are chosen so a genuinely talking-head brief
        # accumulates >=2 hits (beating the single "explainer" hit + the tie→fallback rule), while a
        # plain "make an explainer" brief still routes to the faceless base ``explainer`` default.
        "keywords": ["talking head explainer", "talking-head explainer", "talking head",
                     "talking-head", "presenter explainer", "presenter", "spokesperson",
                     "avatar explainer", "with a presenter", "with a host", "with a face",
                     "presenter walkthrough", "host walkthrough", "narrated site walkthrough",
                     "explain this url"],
    },
    "story": {
        "keywords": ["story", "narrative", "cinematic", "emotional", "journey", "documentary",
                     "short film", "trailer", "montage", "mini-doc"],
    },
    "music_video": {
        "keywords": ["music video", "music-video", "lyric video", "beat-synced", "beat synced",
                     "synthwave", "song", "soundtrack", "kinetic promo", "bpm"],
    },
    "slideshow": {
        "keywords": ["slideshow", "slide show", "listicle", "countdown", "top 5", "top 10",
                     "top five", "signs", "reasons", "tips", "before and after", "before/after"],
    },
    "site_tour": {
        "keywords": ["website", "site tour", "landing page", "landing-page", "portfolio", "showcase",
                     "product tour", "saas landing", "web page", "homepage"],
    },
}


def _hits(text: str, keywords: list[str]) -> int:
    """Count word-ish keyword hits (avoids tiny substring false positives)."""
    return sum(
        1
        for kw in keywords
        if re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", text)
    )


# Public alias: ``production_recipe`` scores its own vocabulary with the SAME matcher rather than
# growing a second keyword engine. One matcher, two vocabularies.
keyword_hits = _hits


def score_formats(brief: str) -> list[tuple[str, int]]:
    """``(format, score)`` pairs sorted by score descending (deterministic keyword counts)."""
    norm = str(brief or "").lower()
    scores = [(name, _hits(norm, list(spec.get("keywords", ())))) for name, spec in FORMAT_REGISTRY.items()]
    return sorted(scores, key=lambda kv: kv[1], reverse=True)


def recommend_format(brief: str, *, default: str = "explainer") -> str:
    """Recommend a content format for ``brief``.

    Case-insensitive keyword scoring; empty / zero-score / tied briefs fall back to ``default``.
    The returned value is always a key of :data:`FORMAT_REGISTRY`; an invalid default → ``explainer``.
    """
    fallback = default if default in FORMAT_REGISTRY else "explainer"
    scores = score_formats(brief)
    if not scores or scores[0][1] <= 0:
        return fallback
    if len(scores) > 1 and scores[0][1] == scores[1][1]:
        return fallback
    return scores[0][0]
