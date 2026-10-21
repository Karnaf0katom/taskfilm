"Shot lanes and role order used by the story router."

from __future__ import annotations

ROLE_ORDER = ("promise", "identity", "run-start", "proof", "bookend", "cta")

LANES = frozenset({"terminal", "browser", "diagram", "text-slide", "generated-broll"})
