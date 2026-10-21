"Import the production modules included with Taskfilm."

from __future__ import annotations

import importlib

from types import ModuleType

from . import _loader

from ._lanes import LANES, VIDEO_ROOT, lane_dir

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

def __getattr__(name: str) -> ModuleType:
    """`from videokit import editlane` — resolve a lane alias as an attribute."""
    if name in LANES:
        return importlib.import_module(f"videokit.{name}")
    raise AttributeError(f"module 'videokit' has no attribute {name!r}")

_loader.install()
