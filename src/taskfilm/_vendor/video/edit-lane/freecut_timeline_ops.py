"""Place already-rendered assets onto a FreeCut timeline as ops — the multi-engine door.

`freecut_ops.py` translates ONE clip plus its speaker-crop track into crop/transform keyframes.
This module answers the other half of the border: given N assets that different ENGINES produced
(Manim via motion-lane, HyperFrames via hyperframes-lane, plain camera footage, anything later),
emit the ops that lay them out as real FreeCut timeline items.

Why ops and not a rendered mp4 — EDITLANE-FREECUT-BORDER-BRIEF.md §3, decided by the operator:
what crosses the border is neither a baked mp4 nor a project file, but ops that build timeline
items, because once a beat IS a timeline item every FreeCut capability applies to it for free —
trim, split, ducking, keyframes, effects, subtitles, export. One app, one URL.

The engine is deliberately NOT encoded in the ops. FreeCut only ever sees "workspace media on a
track at a frame". That is what lets engines be mixed and swapped without FreeCut learning about
any of them.

Op shapes are fixed by `freecut/headless/lib/contract.mjs` (Zod, `.strict()`):
    addTrack  {op, kind?, order?}
    addClip   {op, mediaId, from?, trackId?, durationInFrames?}
    trimStart {op, id, amount}
    moveItem  {op, id, from, trackId?}

Two contract facts drive the shape of what this module emits, and getting either wrong is silent
rather than loud:

1. **`callerId` is mandatory on every op** for the edit that PERSISTS (`lifecycleEditRequestSchema`
   — `agent.mjs project edit`, `POST /v1/projects/{id}/edit`). The older stateless `POST /edit`
   accepts ops without one, so ops that look fine there are rejected the moment they are asked to
   land in a workspace. A callerId is also the only way to name an item an earlier op created:
   `{"$ref": "<callerId>#/detail/created/0/id"}` (0 = video, 1 = its linked audio).

2. **`addClip` has no source in-point.** It places the media from ITS frame 0. A beat that uses a
   window of a longer source (a shot at 4:22 of a film) is therefore addClip + `trimStart`, and
   the trim is what makes the length final — so nothing is placed at its real position until
   after it is trimmed (see STAGE_BASE). `trimStart`'s `amount` is in TIMELINE frames, not source
   frames: FreeCut clamps it against the timeline fps and the item's neighbours, then converts to
   the source's own fps itself (`applySynchronizedTrim`). A 24 fps source in a 30 fps project
   needs no arithmetic here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, TypeAlias

FreeCutOp: TypeAlias = dict[str, Any]

#: Beats laid end to end share this track; overlays (alpha) go above it.
BASE_TRACK_ORDER = 0
OVERLAY_TRACK_ORDER = 1

#: Clips are added far past the end of any real timeline and only then moved into place. Trimming
#: an item's head changes its length where it sits, so placing first and trimming after lets a
#: clip collide with the neighbour it has not been separated from yet. Staging keeps every item
#: alone until its length is final. Same trick as the long-form builder that lays 100+ shots this
#: way, in a client production's own script (since removed from the tree).
STAGE_BASE = 200_000
STAGE_GAP = 1_000


@dataclass(frozen=True)
class Placement:
    """One rendered asset and where it belongs on the timeline.

    ``media_id`` is FreeCut's workspace media id — the asset must already be in the workspace;
    this module never uploads. ``start_sec`` is on the OUTPUT timeline, ``source_start_sec`` is
    inside the media (0 for a beat an engine rendered to length; 262.0 for a shot taken from
    4:22 of a film). ``overlay`` puts the item on the overlay track (an alpha beat composited
    over the base).

    ``has_audio`` must come from FreeCut's own probe (`metadata.audioCodec`), never a guess:
    addClip creates a linked audio item only for media that has an audio stream, and this flag is
    what decides whether that second item is moved off the staging offset. Claim audio that isn't
    there and the op fails on a missing item; miss audio that is there and a silent item is left
    parked ~1.8 h into the timeline, which is not visible but is very much exported.
    """

    media_id: str
    start_sec: float
    duration_sec: float
    overlay: bool = False
    label: str = ""
    source_start_sec: float = 0.0
    has_audio: bool = False

    def __post_init__(self) -> None:
        if not self.media_id:
            raise ValueError("media_id is required")
        if self.start_sec < 0 or not math.isfinite(self.start_sec):
            raise ValueError(f"{self.label or self.media_id}: start_sec must be finite and >= 0")
        if self.duration_sec <= 0 or not math.isfinite(self.duration_sec):
            raise ValueError(f"{self.label or self.media_id}: duration_sec must be finite and > 0")
        if self.source_start_sec < 0 or not math.isfinite(self.source_start_sec):
            raise ValueError(
                f"{self.label or self.media_id}: source_start_sec must be finite and >= 0"
            )


def _start_frame(seconds: float, fps: int) -> int:
    """Seconds -> a start offset. Frame 0 is a legal position: the beginning of the timeline."""
    return max(0, round(seconds * fps))


def _duration_frames(seconds: float, fps: int) -> int:
    """Seconds -> a length. Never zero — a clip that occupies no frames is not a clip."""
    return max(1, round(seconds * fps))


def build_timeline_ops(
    placements: list[Placement],
    *,
    fps: int,
    base_track: str | None = None,
    overlay_track: str | None = None,
) -> list[FreeCutOp]:
    """Return the ops that lay every placement out as real FreeCut timeline items.

    Beats share one lane and are laid end to end; an overlay beat goes on a second video track,
    added only when some placement needs it.

    The base lane is FreeCut's OWN first video track: a project always opens with an empty V1, and
    an `addTrack` for the base beats would leave that V1 stranded above the work with nothing on
    it. `addClip` without a `trackId` resolves to exactly that track (`getOrCreateTrack`), so the
    base lane is expressed by saying nothing. Only the overlay lane, which must be a DIFFERENT
    track, is added. Pass ``base_track``/``overlay_track`` to name tracks explicitly instead.

    Per placement: `addClip` at the staging offset for head+body frames -> `trimStart` the head
    away (only when the beat starts inside its source) -> `moveItem` to the real position, plus
    the linked audio item when the media has an audio stream.
    """
    if not (1 <= fps <= 240):
        raise ValueError(f"fps must be within FreeCut's 1..240 (got {fps})")
    if not placements:
        return []

    ops: list[FreeCutOp] = []
    #: None == "whatever track FreeCut resolves to", which is the project's own first video track.
    tracks: dict[bool, object | None] = {False: base_track}
    if any(p.overlay for p in placements):
        if overlay_track:
            tracks[True] = overlay_track
        else:
            ops.append({"callerId": "over", "op": "addTrack", "kind": "video",
                        "order": OVERLAY_TRACK_ORDER})
            tracks[True] = {"$ref": "over#/detail/trackId"}

    for i, p in enumerate(placements):
        track = tracks[p.overlay]
        head = _start_frame(p.source_start_sec, fps)
        at = _start_frame(p.start_sec, fps)
        clip = f"c{i}"
        ops.append({
            "callerId": clip,
            "op": "addClip",
            "mediaId": p.media_id,
            **({"trackId": track} if track else {}),
            "from": STAGE_BASE + i * STAGE_GAP,
            "durationInFrames": head + _duration_frames(p.duration_sec, fps),
        })
        if head:
            ops.append({
                "callerId": f"t{i}",
                "op": "trimStart",
                "id": {"$ref": f"{clip}#/detail/created/0/id"},
                "amount": head,
            })
        ops.append({
            "callerId": f"m{i}",
            "op": "moveItem",
            "id": {"$ref": f"{clip}#/detail/created/0/id"},
            "from": at,
            **({"trackId": track} if track else {}),
        })
        if p.has_audio:
            # created/1 is the audio item addClip links to the video one. It rides its own audio
            # track, so it is moved without a trackId — only off the staging offset.
            ops.append({
                "callerId": f"a{i}",
                "op": "moveItem",
                "id": {"$ref": f"{clip}#/detail/created/1/id"},
                "from": at,
            })
    return ops


def sequence(beats: list[dict], *, start_sec: float = 0.0) -> list[Placement]:
    """Lay non-overlay beats end to end; overlays keep their own explicit `start`.

    ``beats`` is the conductor's rendered-beat list: ``{media_id, duration, overlay?, label?,
    start?, source_start?, has_audio?}``. Returning Placements (not ops) keeps timing decisions
    testable without touching the op vocabulary.
    """
    out: list[Placement] = []
    cursor = start_sec
    for b in beats:
        overlay = bool(b.get("overlay"))
        dur = float(b["duration"])
        start = float(b["start"]) if overlay and "start" in b else cursor
        out.append(Placement(
            media_id=str(b["media_id"]),
            start_sec=start,
            duration_sec=dur,
            overlay=overlay,
            label=str(b.get("label", "")),
            source_start_sec=float(b.get("source_start", 0.0)),
            has_audio=bool(b.get("has_audio")),
        ))
        if not overlay:
            cursor += dur
    return out
