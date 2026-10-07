"""Typed, data-driven show formats for Jarvis repo reels.

Eligibility is an objective evidence gate. A format is either supported by the
sandbox receipt and demoability signals or omitted; formats are never weakened.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypedDict


KNOWN_BEAT_TYPES = frozenset({"evidence", "explanation", "emotion", "presentation"})


class BeatSpec(TypedDict):
    """One beat in a repeatable show grammar."""

    type: str
    purpose: str


class FormatSpec(TypedDict):
    """Data required to route and author one show format."""

    id: str
    beats: tuple[BeatSpec, ...]
    hook_template: str
    cover_frame_style: str
    requires: dict[str, dict[str, Any]]
    duration_band: tuple[int, int]


class FormatRegistryError(ValueError):
    """Raised when a show format cannot be safely registered."""


FORMATS: dict[str, FormatSpec] = {
    "ran-it-for-you": {
        "id": "ran-it-for-you",
        "beats": (
            {"type": "presentation", "purpose": "name the repo and the promised result"},
            {"type": "evidence", "purpose": "show the successful run receipt"},
            {"type": "explanation", "purpose": "state what the result means"},
            {"type": "emotion", "purpose": "deliver the practical verdict"},
        ),
        "hook_template": "I ran {repo} so you don't have to",
        "cover_frame_style": "result-first proof frame with repo name",
        "requires": {
            "built": {"equals": True},
            "produces_visual_artifact": {"equals": True},
            "usable_seconds": {"min": 10},
        },
        "duration_band": (20, 45),
    },
    "install-to-wow-30s": {
        "id": "install-to-wow-30s",
        "beats": (
            {"type": "presentation", "purpose": "show the zero-config starting point"},
            {"type": "evidence", "purpose": "show install and launch receipts"},
            {"type": "emotion", "purpose": "reveal the visual payoff"},
        ),
        "hook_template": "From install to {payoff} in 30 seconds",
        "cover_frame_style": "split terminal command and finished artifact",
        "requires": {
            "built": {"equals": True},
            "config_steps": {"equals": 0},
            "install_seconds": {"max": 30},
            "produces_visual_artifact": {"equals": True},
        },
        "duration_band": (24, 36),
    },
    "readme-lied": {
        "id": "readme-lied",
        "beats": (
            {"type": "presentation", "purpose": "quote the documented claim"},
            {"type": "evidence", "purpose": "show the contradictory run receipt"},
            {"type": "explanation", "purpose": "explain the exact mismatch"},
        ),
        "hook_template": "The README said {claim}. The run said otherwise.",
        "cover_frame_style": "documented claim beside contradictory receipt",
        "requires": {
            "readme_claims": {"min_items": 1},
            "contradicted_readme_claims": {"min_items": 1},
        },
        "duration_band": (25, 50),
    },
    "x-vs-y": {
        "id": "x-vs-y",
        "beats": (
            {"type": "presentation", "purpose": "name both contenders"},
            {"type": "evidence", "purpose": "show the first receipt"},
            {"type": "evidence", "purpose": "show the second receipt"},
            {"type": "explanation", "purpose": "compare the observed outcomes"},
        ),
        "hook_template": "{x} vs {y}: the receipts decide",
        "cover_frame_style": "balanced side-by-side result frames",
        "requires": {"comparison_receipts": {"min": 2}},
        "duration_band": (30, 60),
    },
    "one-command": {
        "id": "one-command",
        "beats": (
            {"type": "presentation", "purpose": "show the command uncut"},
            {"type": "evidence", "purpose": "show its successful output"},
            {"type": "emotion", "purpose": "reveal the resulting artifact"},
        ),
        "hook_template": "One command to {payoff}",
        "cover_frame_style": "single command over the finished result",
        "requires": {
            "built": {"equals": True},
            "config_steps": {"max": 1},
            "produces_visual_artifact": {"equals": True},
        },
        "duration_band": (15, 35),
    },
    "proof-compilation": {
        "id": "proof-compilation",
        "beats": (
            {"type": "presentation", "purpose": "state the shared use case"},
            {"type": "evidence", "purpose": "sequence independently grounded atoms"},
            {"type": "explanation", "purpose": "connect the observed results"},
            {"type": "emotion", "purpose": "close on the strongest artifact"},
        ),
        "hook_template": "{atom_count} receipts, one useful result",
        "cover_frame_style": "multi-panel contact sheet of grounded artifacts",
        "requires": {
            "atom_count": {"min": 3},
            "usable_seconds": {"min": 45},
        },
        "duration_band": (35, 75),
    },
}


def register_format(registry: dict[str, FormatSpec], spec: FormatSpec) -> None:
    """Validate and add a format, refusing unsupported beats immediately."""

    _validate_format(spec)
    format_id = spec["id"]
    if format_id in registry:
        raise FormatRegistryError(f"duplicate format id: {format_id}")
    registry[format_id] = spec


def eligible_formats(
    repo: Mapping[str, Any],
    registry: Mapping[str, FormatSpec] | Sequence[FormatSpec] = FORMATS,
) -> list[FormatSpec]:
    """Return supported formats in recorded registry order, without scoring."""

    if not isinstance(repo, Mapping):
        raise TypeError("repo signals must be a mapping")
    specs: Iterable[FormatSpec]
    specs = registry.values() if isinstance(registry, Mapping) else registry
    result: list[FormatSpec] = []
    for spec in specs:
        _validate_format(spec)
        if _meets_requirements(repo, spec["requires"]):
            result.append(spec)
    return result


def _validate_format(spec: Mapping[str, Any]) -> None:
    format_id = spec.get("id")
    if not isinstance(format_id, str) or not format_id.strip():
        raise FormatRegistryError("format id must be a non-empty string")
    beats = spec.get("beats")
    if not isinstance(beats, (list, tuple)) or not beats:
        raise FormatRegistryError(f"format {format_id} must declare beats")
    for beat in beats:
        if not isinstance(beat, Mapping):
            raise FormatRegistryError(f"format {format_id} has an invalid beat")
        beat_type = beat.get("type")
        if beat_type not in KNOWN_BEAT_TYPES:
            raise FormatRegistryError(
                f"format {format_id} names unknown beat type {beat_type!r}"
            )
    band = spec.get("duration_band")
    if (
        not isinstance(band, (list, tuple))
        or len(band) != 2
        or not all(isinstance(value, (int, float)) for value in band)
        or band[0] >= band[1]
    ):
        raise FormatRegistryError(f"format {format_id} has an invalid duration band")
    if not isinstance(spec.get("requires"), Mapping):
        raise FormatRegistryError(f"format {format_id} must declare requirements")
    for field, checks in spec["requires"].items():
        if not isinstance(field, str) or not isinstance(checks, Mapping):
            raise FormatRegistryError(f"format {format_id} has an invalid requirement")
        unknown = set(checks) - {"equals", "min", "max", "min_items"}
        if unknown:
            raise FormatRegistryError(
                f"format {format_id} uses unknown requirement operators: {sorted(unknown)}"
            )


def _meets_requirements(
    repo: Mapping[str, Any], requirements: Mapping[str, Mapping[str, Any]]
) -> bool:
    for field, checks in requirements.items():
        if field not in repo:
            return False
        value = repo[field]
        if "equals" in checks and value != checks["equals"]:
            return False
        if "min" in checks and not _ordered(value, checks["min"], at_least=True):
            return False
        if "max" in checks and not _ordered(value, checks["max"], at_least=False):
            return False
        if "min_items" in checks:
            try:
                if isinstance(value, (str, bytes)) or len(value) < checks["min_items"]:
                    return False
            except (TypeError, ValueError):
                return False
    return True


def _ordered(value: Any, boundary: Any, *, at_least: bool) -> bool:
    try:
        return value >= boundary if at_least else value <= boundary
    except TypeError:
        return False


for _format_id, _format_spec in FORMATS.items():
    if _format_spec["id"] != _format_id:
        raise FormatRegistryError(
            f"registry key {_format_id!r} does not match format id {_format_spec['id']!r}"
        )
    _validate_format(_format_spec)
