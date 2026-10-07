"""The rule that decides which engine renders which beat.

One engine per beat, chosen by the beat's JOB and never by taste, so the same job always gets the
same engine: evidence is captured, explanation is drawn, atmosphere is generated, the presenter is
filmed. When two engines could serve a beat the cheapest truthful one wins — capture > diagram >
motion > generated > 3d — and every step up that ladder records why on the decision itself.

This module decides and refuses; it renders nothing and verifies no claim text (claim_check.py owns
that). The taxonomy, the presenter slots and the shot lanes belong to formats.py and
validate_reel_script.py and are read from them, never re-typed here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from formats import KNOWN_BEAT_TYPES
from validate_reel_script import LANES, ROLE_ORDER

SCHEMA = "beat-routing/v1"
SCHEMA_VERSION = 1

LADDER = ("capture", "diagram", "motion", "generated", "3d")
ENGINE_LANES = {
    "capture": "capture-lane",
    "diagram": "hyperframes-lane",
    "motion": "motion-lane",
    "generated": "comfy-arsenal",
    "3d": "blender-lane",
    "cinema": "cinema-lane",
}
SHOT_LANE_ENGINES = {
    "terminal": "capture",
    "browser": "capture",
    "diagram": "diagram",
    "text-slide": "diagram",
    "generated-broll": "generated",
}
# The reel grammar owns the shot-lane vocabulary. A lane it gains without an engine here would be
# routed by silence, so the drift fails closed at import rather than at render time.
_UNMAPPED_SHOT_LANES = tuple(sorted(LANES - set(SHOT_LANE_ENGINES)))
if _UNMAPPED_SHOT_LANES:  # pragma: no cover - drift guard
    raise ImportError(
        f"validate_reel_script.LANES has shot lanes with no engine: {_UNMAPPED_SHOT_LANES}"
    )

EVIDENCE_ROLES = ("run-start", "proof")
PRESENTER_SLOTS = tuple(role for role in ROLE_ORDER if role not in EVIDENCE_ROLES)


class BeatRoutingError(ValueError):
    """Raised when a beat cannot be routed by the known taxonomy."""


class BeatRoutingRefused(BeatRoutingError):
    """Raised when a beat asks for a route its job forbids."""


@dataclass(frozen=True)
class BeatPolicy:
    """One row in the beat-type routing table."""

    beat_type: str
    engine: str
    allowed_engines: tuple[str, ...]
    refused_engines: tuple[str, ...]
    hard_rule: str
    compose_in_brandkit: bool


@dataclass(frozen=True)
class Routing:
    """The recorded engine decision for one beat."""

    beat_type: str
    engine: str
    lane: str
    ladder_rung: int | None
    compose_in_brandkit: bool
    rule: str
    reason: str
    justification: str = ""

    def to_json(self) -> dict[str, Any]:
        """Return the JSON-shaped routing decision."""

        return {
            "schema": SCHEMA,
            "beat_type": self.beat_type,
            "engine": self.engine,
            "lane": self.lane,
            "ladder_rung": self.ladder_rung,
            "compose_in_brandkit": self.compose_in_brandkit,
            "rule": self.rule,
            "reason": self.reason,
            "justification": self.justification,
        }


ROUTING_TABLE = {
    "evidence": BeatPolicy(
        beat_type="evidence",
        engine="capture",
        allowed_engines=("capture",),
        refused_engines=("diagram", "motion", "generated", "3d", "cinema"),
        hard_rule="Evidence beats route to capture-lane only and require evidence ids; reenactment is refused.",
        compose_in_brandkit=False,
    ),
    "explanation": BeatPolicy(
        beat_type="explanation",
        engine="diagram",
        allowed_engines=("diagram", "motion", "3d"),
        refused_engines=("capture", "generated", "cinema"),
        hard_rule="Explanation beats are diagrammatic first; motion or 3D must record why, and 3D requires 2D insufficiency.",
        compose_in_brandkit=True,
    ),
    "emotion": BeatPolicy(
        beat_type="emotion",
        engine="generated",
        allowed_engines=("generated", "3d"),
        refused_engines=("capture", "diagram", "motion", "cinema"),
        hard_rule="Emotion beats may use generated atmosphere or 3D but must carry zero claims.",
        compose_in_brandkit=True,
    ),
    "presentation": BeatPolicy(
        beat_type="presentation",
        engine="cinema",
        allowed_engines=("cinema",),
        refused_engines=("capture", "diagram", "motion", "generated", "3d"),
        hard_rule="Presentation beats route to cinema-lane only and only in declared presenter slots.",
        compose_in_brandkit=True,
    ),
}


def route_beat(beat: Mapping[str, Any]) -> Routing:
    """Route one beat to its engine, or refuse an unsafe shape."""

    if not isinstance(beat, Mapping):
        raise BeatRoutingError("beat must be a mapping")
    beat_type = _text(beat.get("type"))
    if beat_type not in KNOWN_BEAT_TYPES:
        raise BeatRoutingError(f"unknown beat type: {beat_type!r}")
    policy = ROUTING_TABLE[beat_type]
    requested = _text(beat.get("requested_engine")) or policy.engine
    justification = _text(beat.get("justification"))

    if requested not in policy.allowed_engines:
        raise BeatRoutingRefused(
            f"{beat_type} beat cannot route to {requested!r}; allowed engines are {policy.allowed_engines}"
        )

    if beat_type == "evidence":
        _refuse_evidence_reenactment(beat, requested)
    elif beat_type == "explanation":
        _refuse_unjustified_explanation_escalation(beat, requested, policy.engine, justification)
    elif beat_type == "emotion":
        _refuse_claim_bearing_emotion(beat)
        _refuse_unjustified_ladder_step(beat_type, requested, policy.engine, justification)
    elif beat_type == "presentation":
        _refuse_floating_presentation(beat)

    return Routing(
        beat_type=beat_type,
        engine=requested,
        lane=ENGINE_LANES[requested],
        ladder_rung=LADDER.index(requested) if requested in LADDER else None,
        compose_in_brandkit=policy.compose_in_brandkit,
        rule=policy.hard_rule,
        reason=_reason_for(beat_type, requested),
        justification=justification if requested != policy.engine else "",
    )


def route_beats(beats: Sequence[Mapping[str, Any]]) -> tuple[Routing, ...]:
    """Route a sequence of beats in order."""

    return tuple(route_beat(beat) for beat in beats)


def engine_per_beat(beats: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Return the decision_manifest engine_per_beat mapping."""

    routed = route_beats(beats)
    return {
        f"{index}:{routing.beat_type}": routing.engine
        for index, routing in enumerate(routed, start=1)
    }


def _refuse_evidence_reenactment(beat: Mapping[str, Any], requested: str) -> None:
    evidence_ids = tuple(beat.get("evidence_ids") or ())
    if not evidence_ids:
        raise BeatRoutingRefused("evidence beat requires evidence ids")
    if requested != "capture":
        raise BeatRoutingRefused("evidence beat refuses reenactment engines")
    shot_lane = _text(beat.get("shot_lane"))
    if shot_lane and SHOT_LANE_ENGINES.get(shot_lane) != "capture":
        raise BeatRoutingRefused(f"evidence beat cannot use {shot_lane!r} as a shot lane")


def _refuse_unjustified_explanation_escalation(
    beat: Mapping[str, Any],
    requested: str,
    default: str,
    justification: str,
) -> None:
    _refuse_unjustified_ladder_step("explanation", requested, default, justification)
    if requested == "3d" and not bool(beat.get("two_d_insufficient")):
        raise BeatRoutingRefused("explanation beat needs two_d_insufficient before routing to 3D")


def _refuse_unjustified_ladder_step(
    beat_type: str,
    requested: str,
    default: str,
    justification: str,
) -> None:
    if requested in LADDER and default in LADDER and LADDER.index(requested) > LADDER.index(default):
        if not justification:
            raise BeatRoutingRefused(f"{beat_type} beat needs a justification to step up the ladder")


def _refuse_claim_bearing_emotion(beat: Mapping[str, Any]) -> None:
    if tuple(beat.get("claim_ids") or ()):
        raise BeatRoutingRefused("emotion beat must carry zero claims")


def _refuse_floating_presentation(beat: Mapping[str, Any]) -> None:
    role = _text(beat.get("role"))
    if role not in PRESENTER_SLOTS:
        raise BeatRoutingRefused("presentation beat must be in a declared presenter slot")


def _reason_for(beat_type: str, engine: str) -> str:
    if beat_type == "evidence":
        return "evidence must show what the repo actually did"
    if beat_type == "explanation":
        return f"explanation routed to {engine} by the cost-truthfulness ladder"
    if beat_type == "emotion":
        return f"emotion routed to {engine} only after refusing claim-bearing atmosphere"
    return "presentation belongs to the cinema presenter lane"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
