"Names and locations of the included production folders."

from __future__ import annotations

from pathlib import Path

VIDEO_ROOT = Path(__file__).resolve().parent.parent

LANES = {'director': 'director', 'mix': 'mix', 'repolane': 'repo-lane', 'reellane': 'reel-lane', 'hyperframeslane': 'hyperframes-lane', 'capturelane': 'capture-lane', 'editlane': 'edit-lane'}

def lane_dir(alias: str) -> Path:
    """Absolute path of a lane, or raise with the list of known aliases."""
    try:
        return VIDEO_ROOT / LANES[alias]
    except KeyError:
        known = ", ".join(sorted(LANES))
        raise KeyError(f"unknown lane {alias!r}; known lanes: {known}") from None
