"""Make the hyphenated lanes importable, without moving a single file.

Modules inside `edit-lane/` import their siblings flat — `from content_score import …`,
351 times, zero relative imports. That is a fact of the tree, not something this loader
tries to change: rewriting 351 import statements across 1,009 files would break the 278
frozen-oracle tests for no product gain.

So the loader does the one thing that makes flat imports legal *and* namespaced:

1. it puts the lane directory on ``sys.path`` (once, centrally — instead of 375 times,
   scattered), so ``from content_score import …`` still resolves, and
2. it exposes the same module object under ``videokit.<lane>.<module>``.

Point 2 is deliberately an *alias*, not a second import. ``videokit.editlane.reframe``
and flat ``reframe`` are the identical object in ``sys.modules``, so a dataclass built
by one side passes an ``isinstance`` check on the other. Importing the same file twice
under two names is the classic way to get two incompatible copies of one class; this
loader exists partly to prevent that.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
from pathlib import Path
from types import ModuleType

from ._lanes import LANES, VIDEO_ROOT, lane_dir

_PREFIX = "videokit."


def ensure_path(alias: str) -> Path:
    """Put a lane (and `apps/video` itself) at the FRONT of sys.path.

    Front, not merely present: ten flat module names exist in two lanes at once
    (`narration.py` in both director and edit-lane, `providers.py` in both
    captions-service and spine, …). With the requested lane first, the lane you asked
    for wins deterministically instead of whichever lane happened to be imported first.
    """
    directory = lane_dir(alias)
    for entry in (str(VIDEO_ROOT), str(directory)):
        if entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)
    return directory


class _AliasLoader(importlib.abc.Loader):
    """Import a lane module under its flat name, then publish it under the alias."""

    def __init__(self, alias: str, flat_name: str) -> None:
        self._alias = alias
        self._flat_name = flat_name

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        directory = ensure_path(self._alias)
        # import_module returns the already-loaded object on a second call, which is
        # exactly what we want: one file, one module object, two names.
        module = importlib.import_module(self._flat_name)
        _reject_shadowed(module, directory, self._alias, self._flat_name)
        return module

    def exec_module(self, module: ModuleType) -> None:
        # create_module handed back a fully executed module. Re-running it here would
        # double every import side effect.
        return None


class _LaneFinder(importlib.abc.MetaPathFinder):
    """Resolve `videokit.<alias>` and `videokit.<alias>.<module>`."""

    def find_spec(self, fullname, path=None, target=None):  # noqa: D102 - stdlib protocol
        if not fullname.startswith(_PREFIX):
            return None
        parts = fullname[len(_PREFIX):].split(".")
        alias = parts[0]
        if alias not in LANES:
            return None

        directory = ensure_path(alias)

        if len(parts) == 1:
            spec = importlib.machinery.ModuleSpec(fullname, _LanePackageLoader(alias), is_package=True)
            spec.submodule_search_locations = [str(directory)]
            return spec

        flat_name = ".".join(parts[1:])
        if not _resolvable(directory, parts[1:]):
            return None
        return importlib.machinery.ModuleSpec(fullname, _AliasLoader(alias, flat_name))


class _LanePackageLoader(importlib.abc.Loader):
    """The `videokit.<alias>` package itself — a namespace over the lane folder."""

    def __init__(self, alias: str) -> None:
        self._alias = alias

    def create_module(self, spec):
        module = ModuleType(spec.name)
        module.__path__ = list(spec.submodule_search_locations)
        module.__lane__ = LANES[self._alias]
        module.__file__ = None
        return module

    def exec_module(self, module: ModuleType) -> None:
        return None


def _resolvable(directory: Path, parts: list[str]) -> bool:
    """True when `parts` names a real .py file or package under `directory`."""
    head = directory / parts[0]
    if len(parts) == 1:
        return head.with_suffix(".py").is_file() or (head / "__init__.py").is_file()
    return head.is_dir()


class ShadowedModuleError(ImportError):
    """Asked for one lane's module, sys.modules already held another lane's file of that name."""


def _reject_shadowed(module: ModuleType, directory: Path, alias: str, flat_name: str) -> None:
    """Fail loudly when a flat name was already claimed by a different lane.

    Without this the caller silently gets the wrong lane's module — the exact failure the
    flat-import layout makes possible, and the hardest kind to debug because nothing raises.
    """
    origin = getattr(module, "__file__", None)
    if origin is None:
        return  # namespace package or builtin; nothing to compare
    resolved = Path(origin).resolve()
    if resolved.is_relative_to(directory.resolve()):
        return
    raise ShadowedModuleError(
        f"videokit.{alias}.{flat_name} resolved to {resolved}, which is not in "
        f"{directory}. Another lane already imported a module named {flat_name!r}. "
        "Import the lane you need FIRST, or rename one of the two files "
        "(tools/capability-map-check.sh lists every cross-lane name clash)."
    )


_FINDER = _LaneFinder()


def install() -> None:
    """Register the finder FIRST. Idempotent — safe to call from every entry point.

    Position 0 is load-bearing, not tidiness. `videokit.editlane` carries a `__path__`, so
    the stdlib PathFinder can resolve `videokit.editlane.video_ffmpeg` on its own — and it
    sits ahead of anything appended, so it would win and load the file a SECOND time under
    a second name. Two module objects from one file means two copies of every class in it,
    and an `isinstance` check that fails for no visible reason. Ahead of PathFinder, the
    alias loader runs and both names share one object.

    The cost is one `str.startswith` per import in the process; everything not named
    `videokit.*` returns None immediately.
    """
    if not any(isinstance(f, _LaneFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _FINDER)
