"""videokit — the one front door to every reusable video capability.

Twenty-one product directions want the same twenty capabilities. Before this package,
reusing one of them meant copying `sys.path.insert(0, str(HERE.parent / "edit-lane"))`
into your file (306 files do) and then guessing the module name. Now:

    import videokit

    reframe  = videokit.capability("reframe")          # by capability id
    captions = videokit.load("editlane.caption_pipeline")  # by module path

    from videokit import editlane                       # or as a normal package
    editlane.find_moments.find_moments(...)

Rules of the road
-----------------
* **Look here before you write it.** ``videokit.capabilities()`` lists what already
  exists and who owns it. A second implementation of an owned capability is the thing
  this package is here to prevent (`.claude/rules/capability-ownership.md`).
* **The owner keeps owning it.** videokit is a *door*, not a home. Behaviour stays in
  the owning lane; nothing gets reimplemented in here.
* **A hyphenated lane is not a Python package** — that is why the aliases in
  ``_lanes.py`` exist. `edit-lane` is `videokit.editlane`.

The capability table is data: ``CAPABILITY-MAP.yaml``, checked by
``tools/capability-map-check.sh``.
"""

from __future__ import annotations

import functools
import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

from . import _loader
from ._lanes import LANES, VIDEO_ROOT, lane_dir

__all__ = [
    "LANES",
    "VIDEO_ROOT",
    "capabilities",
    "capability",
    "capability_row",
    "lane_dir",
    "load",
]

_loader.install()

CAPABILITY_MAP = Path(__file__).resolve().parent / "CAPABILITY-MAP.yaml"


def load(dotted: str) -> ModuleType:
    """Import a lane module by ``<alias>.<module>``.

    >>> load("editlane.reframe")            # doctest: +SKIP
    <module 'reframe' from '.../edit-lane/reframe.py'>
    """
    if "." not in dotted:
        raise ValueError(f"expected '<lane>.<module>', got {dotted!r}")
    alias = dotted.split(".", 1)[0]
    if alias not in LANES:
        known = ", ".join(sorted(LANES))
        raise KeyError(f"unknown lane {alias!r}; known lanes: {known}")
    return importlib.import_module(f"videokit.{dotted}")


@functools.lru_cache(maxsize=1)
def capabilities() -> dict[str, dict[str, Any]]:
    """Every capability we already own, keyed by id. Read from CAPABILITY-MAP.yaml."""
    import yaml  # imported lazily: the loader must work without PyYAML installed

    data = yaml.safe_load(CAPABILITY_MAP.read_text()) or {}
    return {row["id"]: row for row in data.get("capabilities", [])}


def capability_row(cap_id: str) -> dict[str, Any]:
    """The catalog entry for a capability — owner, module, what it takes and returns."""
    try:
        return capabilities()[cap_id]
    except KeyError:
        known = ", ".join(sorted(capabilities()))
        raise KeyError(f"unknown capability {cap_id!r}; known: {known}") from None


def capability(cap_id: str) -> ModuleType:
    """Import the module that OWNS a capability. Use this instead of rebuilding it."""
    return load(capability_row(cap_id)["module"])


def __getattr__(name: str) -> ModuleType:
    """`from videokit import editlane` — resolve a lane alias as an attribute."""
    if name in LANES:
        return importlib.import_module(f"videokit.{name}")
    raise AttributeError(f"module 'videokit' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*__all__, *LANES])
