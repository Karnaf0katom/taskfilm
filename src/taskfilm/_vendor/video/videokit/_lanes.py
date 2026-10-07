"""Where each lane actually lives on disk.

`apps/video` grew 19 folders whose names contain a hyphen (`edit-lane`, `motion-lane`,
`capture-lane`, …). A hyphen is not legal in a Python identifier, so none of those
1,555 modules can be imported as a package — which is why 306 files in this tree open
with `sys.path.insert(...)`.

This table is the ONE place that maps a legal alias onto the real folder. Nothing else
in the tree should have to know that `editlane` is spelled `edit-lane` on disk.
"""

from __future__ import annotations

from pathlib import Path

VIDEO_ROOT = Path(__file__).resolve().parent.parent

# alias -> folder name on disk. Aliases are what callers type.
LANES: dict[str, str] = {
    # the brains
    "editlane": "edit-lane",
    "director": "director",
    "spine": "spine",
    "mix": "mix",
    "repolane": "repo-lane",
    "reellane": "reel-lane",
    "cinema": "cinema",
    "personalane": "persona-lane",
    # the render lanes
    "motionlane": "motion-lane",
    "hyperframeslane": "hyperframes-lane",
    "blenderlane": "blender-lane",
    "capturelane": "capture-lane",
    # platform + services
    "controlplane": "controlplane",
    "store": "store",
    "batch": "batch",
    "captionsservice": "captions-service",
    "clientpipeline": "client-pipeline",
}


def lane_dir(alias: str) -> Path:
    """Absolute path of a lane, or raise with the list of known aliases."""
    try:
        return VIDEO_ROOT / LANES[alias]
    except KeyError:
        known = ", ".join(sorted(LANES))
        raise KeyError(f"unknown lane {alias!r}; known lanes: {known}") from None
