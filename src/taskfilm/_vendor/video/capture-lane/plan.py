#!/usr/bin/env python3
"""plan — turn a recorded session bundle into an explainer edit plan.

This is the step that separates an explainer from a screen recording. It reads the two streams a
flat mp4 cannot carry — where the operator clicked, and which app was in front — and emits:

  * **zooms**   — punch-ins on click clusters, each starting *before* the click so the move reads
                  as intent rather than reaction.
  * **chapters** — one per foreground-app change, the natural title-card boundaries.
  * **typing**   — stretches where the operator was typing, which want a hold, not a cut.

The output is deliberately framework-neutral (normalised 0..1 coordinates, seconds). Freecut turns
it into timeline ops, hyperframes turns it into keyframes; neither has to know about pynput.

Usage:
    python plan.py <session-dir> [--screen 2560x1440] [--json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import pixels

# A punch-in that starts on the click looks like a reaction. Leading it by ~0.6 s reads as a
# camera operator who knew what was coming, which is the whole illusion.
LEAD_S = 0.6
TAIL_S = 1.2

# Clicks belong to one move when they are close in BOTH time and space. Two clicks 4 s apart in
# the same button are two moments; two clicks 0.3 s apart across the screen are a drag-and-drop.
CLUSTER_GAP_S = 2.5
CLUSTER_RADIUS = 0.18          # fraction of the screen diagonal

# Below this a zoom is a flinch. Above the merge gap, two zooms in a row strobe.
MIN_ZOOM_S = 1.8
MERGE_GAP_S = 1.2

# A camera that punches in, pulls out and punches back to the same place is not emphasising it, it
# is fidgeting. Measured on the FreeCut take: 19 punch-ins, seven of them onto the same strip of
# timeline within half a minute. So once the camera is somewhere, a press in the same neighbourhood
# *holds the shot* instead of buying a new move — the camera only travels when the target does.
SETTLE_RADIUS = 0.14           # fraction of the screen diagonal: "near enough to already be framed"
SETTLE_GAP_S = 6.0             # after this long the viewer has forgotten; a fresh move is honest
MAX_SETTLE_S = 14.0            # nobody holds one punch-in forever — past this, pull out and re-punch

# Deep enough to read a label, shallow enough not to lose context.
MAX_SCALE = 2.0
MIN_SCALE = 1.3

# Aim — a punch-in frames the app's ANSWER, not the operator's hand.
#
# A zoom is built from a click because for most of an editor the click *is* the subject: you press
# the razor and the razor is what to look at. That stops being true the moment a control and its
# consequence live in different parts of the screen — press a chip in a side rail and the thing
# worth seeing is the preview above it. Measured on the Block Studio take: eleven punch-ins, all of
# them correctly on the chip that was pressed, and several of them framing a column of sliders while
# the narration described an effect playing somewhere else in the window.
#
# So the click says *when*; two frames of the recording say *where*.
AIM_AFTER_S = 0.9              # how long the app is given to answer before the second frame
AIM_MIN_SHARE = 0.30           # below this the change is smeared: keep the click, it is honest
AIM_MIN_CHANGE = 0.004         # a change this small is a hover state, not an answer
AIM_MIN_MOVE = 0.10            # fraction of the diagonal: closer than this and the click was right

# Typing arrives as a burst of key events; a gap this long ends the burst.
TYPING_GAP_S = 1.5
MIN_TYPING_KEYS = 4

# Dead air. A stretch where nothing moves, nothing is pressed and nothing is said is the stretch
# a viewer leaves during. Longer than this and it gets compressed — not deleted, because a pause
# after a click is the app answering, and the answer is the point of the shot.
DEAD_AIR_S = 2.2
HOLD_PAD_S = 0.6               # how much of the pause survives on each side of a cut
MIN_CUT_S = 0.4                # below this a cut is a hiccup, not a saving

# Narration read at an explainer pace. Used to say how much slack a beat has, never to speed a
# voice up: the number exists so the *picture* can be cut to the words.
WORDS_PER_S = 2.6
# Hebrew packs more meaning per word than English, so the same idea is fewer, longer words. Used
# only until an audio file exists for the beat; after that the file is measured.
WORDS_PER_S_BY_LANG = {"he": 2.1, "ar": 2.1, "ru": 2.2}
BREATH_S = 0.4                 # the silence a line is allowed to land in before the next one
VO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".opus")

# Retime — the voice is the clock, not the recording.
#
# Cutting can only delete a stretch where *nothing* happened. It cannot help the far more common
# failure: a beat where plenty happens, slowly, under one short line. Measured on the FreeCut take,
# 206 s of picture carried 70 s of voice — a third of the video had anybody talking over it, and two
# beats alone (a colour grade and an export) spent 96 s illustrating 7.8 s of narration. No amount
# of dead-air removal fixes that, because none of it is dead.
#
# So a beat is *ramped* to its line: whatever is left after the cuts is played fast enough to end
# when the sentence does. Speeding a demo up is not a compromise, it is the grammar of the form —
# the drag, the scrub, the slider crawl are all things the viewer understands at 4x and is bored by
# at 1x.
MAX_SPEED_X = 4.0              # past this a gesture stops reading as a gesture
MIN_RAMP_S = 0.5               # a ramp shorter than this is a stutter, not a compression
SILENT_HOLD_S = 2.5            # how long a beat nobody narrates is allowed to sit at full speed


@dataclass
class Zoom:
    start: float
    end: float
    x: float
    y: float
    scale: float
    clicks: int
    # Why the camera is here: the click that caused it, or the pixels that answered it. Written into
    # the plan so nobody downstream has to guess whether a move was measured or assumed.
    aim: str = "click"


@dataclass
class Chapter:
    t: float
    title: str


@dataclass
class Typing:
    start: float
    end: float
    keys: int


@dataclass
class Cut:
    start: float
    end: float
    reason: str


@dataclass
class Retime:
    start: float
    end: float
    speed: float
    beat: str
    reason: str


@dataclass
class Beat:
    id: str
    start: float
    end: float
    vo: str
    explain: str
    show: str
    vo_s: float
    slack_s: float
    vo_from: str
    lang: str


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue                               # a torn last line beats losing the take
    return rows


def cluster_clicks(clicks: list[dict], diagonal: float) -> list[list[dict]]:
    """Group clicks that are one gesture. Clicks must already be sorted by time."""
    clusters: list[list[dict]] = []
    for click in clicks:
        if clusters:
            last = clusters[-1][-1]
            near_in_time = click["t"] - last["t"] <= CLUSTER_GAP_S
            distance = ((click["x"] - last["x"]) ** 2 + (click["y"] - last["y"]) ** 2) ** 0.5
            near_in_space = distance <= CLUSTER_RADIUS * diagonal
            if near_in_time and near_in_space:
                clusters[-1].append(click)
                continue
        clusters.append([click])
    return clusters


def cluster_to_zoom(cluster: list[dict]) -> Zoom:
    """Centre on the cluster, and open the shot wider the more spread out it is."""
    xs = [c["x"] for c in cluster]
    ys = [c["y"] for c in cluster]
    spread = max(max(xs) - min(xs), max(ys) - min(ys))
    # spread 0 -> MAX_SCALE, spread >= CLUSTER_RADIUS -> MIN_SCALE
    ratio = min(spread / CLUSTER_RADIUS, 1.0) if CLUSTER_RADIUS else 1.0
    scale = MAX_SCALE - (MAX_SCALE - MIN_SCALE) * ratio
    # Round before enforcing the minimum, so the invariant holds on the numbers actually emitted:
    # LEAD_S + TAIL_S lands a hair under MIN_ZOOM_S in binary float, and a consumer checking the
    # plan would see a zoom one microsecond too short.
    start = round(max(cluster[0]["t"] - LEAD_S, 0.0), 3)
    end = round(cluster[-1]["t"] + TAIL_S, 3)
    if round(end - start, 3) < MIN_ZOOM_S:
        end = round(start + MIN_ZOOM_S, 3)
    return Zoom(
        start=start,
        end=end,
        x=round(sum(xs) / len(xs), 4),
        y=round(sum(ys) / len(ys), 4),
        scale=round(scale, 3),
        clicks=len(cluster),
    )


def merge_zooms(zooms: list[Zoom]) -> list[Zoom]:
    """Two punch-ins separated by a blink are one punch-in that covers both.

    Merging widens the shot (weighted centre, shallower scale) rather than picking a winner —
    cutting back and forth between two nearby targets is the thing that makes auto-zoom look
    machine-made.
    """
    merged: list[Zoom] = []
    for zoom in zooms:
        if merged and zoom.start - merged[-1].end <= MERGE_GAP_S:
            prev = merged[-1]
            total = prev.clicks + zoom.clicks
            merged[-1] = Zoom(
                start=prev.start,
                end=max(prev.end, zoom.end),
                x=round((prev.x * prev.clicks + zoom.x * zoom.clicks) / total, 4),
                y=round((prev.y * prev.clicks + zoom.y * zoom.clicks) / total, 4),
                scale=round(min(prev.scale, zoom.scale), 3),
                clicks=total,
            )
        else:
            merged.append(zoom)
    return merged


def aim_zooms(zooms: list[Zoom], video: Path, clicks: list[dict], diagonal: float,
              enabled: bool = True) -> tuple[list[Zoom], list[str]]:
    """Re-point each punch-in at where the app answered, when that is not where it was pressed.

    The click is kept as the *timing*: it is the only thing that says when the moment is. What moves
    is the frame. Two samples of the take — one just before the press, one ``AIM_AFTER_S`` later —
    and ``pixels.densest_change`` says where the weight of the change landed.

    Four ways this refuses to move the camera, and each of them was a way to make the shot worse:

    * **no numpy or PIL on the box** — the plan is built anyway, aiming is skipped, and the summary
      says so. A take that fails to plan is worse than one aimed at the click.
    * **the change is tiny** (``AIM_MIN_CHANGE``) — that is a hover or a focus ring, not an answer.
    * **the change is smeared** (``AIM_MIN_SHARE``) — a route change repaints everything, and the
      centre of everything is the middle of the screen, which is not a shot.
    * **the change is where the click already was** (``AIM_MIN_MOVE``) — the common case, and moving
      the frame a few pixels for it would be noise.

    Depth follows the region: a punch-in onto a large answer opens wider, because a 2x crop of a
    half-screen preview shows a quarter of the thing being talked about.
    """
    notes: list[str] = []
    if not enabled or not zooms:
        return zooms, notes
    if not video.exists():
        return zooms, ["no screen.mp4 to sample — punch-ins stay on the clicks"]
    if not pixels.available():
        return zooms, ["numpy/PIL missing — punch-ins stay on the clicks, unaimed"]

    aimed: list[Zoom] = []
    moved = 0
    for zoom in zooms:
        # The click this zoom was built around: its own start plus the lead the camera was given.
        when = next((c["t"] for c in clicks if zoom.start <= c["t"] <= zoom.end), zoom.start + LEAD_S)
        before = pixels.frame(video, when - 0.15)
        after = pixels.frame(video, when + AIM_AFTER_S)
        found = pixels.densest_change(before, after) if before is not None and after is not None else None
        if not found or found["changed"] < AIM_MIN_CHANGE or found["share"] < AIM_MIN_SHARE:
            aimed.append(zoom)
            continue
        distance = ((found["x"] - zoom.x) ** 2 + (found["y"] - zoom.y) ** 2) ** 0.5
        if distance < AIM_MIN_MOVE * diagonal:
            aimed.append(zoom)
            continue
        # Never deeper than the click would have gone, and shallower when the answer is too big to
        # fit that frame — a punch-in that crops two thirds off a half-screen preview shows a
        # quarter of the thing being talked about. Most answers are small, so most of the time this
        # is the click's own depth.
        fits = 1.0 / max(found["w"], found["h"], 1e-6)
        aimed.append(Zoom(start=zoom.start, end=zoom.end, x=found["x"], y=found["y"],
                          scale=round(min(max(fits, MIN_SCALE), zoom.scale), 3),
                          clicks=zoom.clicks, aim="change"))
        moved += 1
    if moved:
        notes.append(f"{moved} of {len(zooms)} punch-in(s) re-aimed from the click to the change "
                     f"it caused")
    return aimed, notes


def settle_zooms(zooms: list[Zoom], diagonal: float) -> list[Zoom]:
    """Let the camera stay where it already is when the next press lands nearby.

    ``merge_zooms`` fixes strobing between two punch-ins a blink apart. This fixes the slower
    version of the same fault: a demo that works one region — a timeline, a toolbar, a panel of
    sliders — presses in it a dozen times, and each press was buying its own punch-in. The result
    reads as a camera with a twitch.

    A press within ``SETTLE_RADIUS`` of where the camera already is simply extends the shot. The
    move is kept honest three ways: the shot cannot be held past ``MAX_SETTLE_S``, a gap longer
    than ``SETTLE_GAP_S`` re-earns the move, and the held shot opens to the *shallower* of the two
    depths so a second target never falls outside a frame chosen for the first.
    """
    settled: list[Zoom] = []
    for zoom in zooms:
        if settled:
            prev = settled[-1]
            near = ((prev.x - zoom.x) ** 2 + (prev.y - zoom.y) ** 2) ** 0.5 <= SETTLE_RADIUS * diagonal
            soon = zoom.start - prev.end <= SETTLE_GAP_S
            room = zoom.end - prev.start <= MAX_SETTLE_S
            if near and soon and room:
                total = prev.clicks + zoom.clicks
                settled[-1] = Zoom(
                    start=prev.start, end=max(prev.end, zoom.end),
                    x=round((prev.x * prev.clicks + zoom.x * zoom.clicks) / total, 4),
                    y=round((prev.y * prev.clicks + zoom.y * zoom.clicks) / total, 4),
                    scale=round(min(prev.scale, zoom.scale), 3), clicks=total)
                continue
        settled.append(zoom)
    return settled


def typing_runs(keys: list[float]) -> list[Typing]:
    runs: list[list[float]] = []
    for t in keys:
        if runs and t - runs[-1][-1] <= TYPING_GAP_S:
            runs[-1].append(t)
        else:
            runs.append([t])
    return [Typing(start=round(r[0], 3), end=round(r[-1], 3), keys=len(r))
            for r in runs if len(r) >= MIN_TYPING_KEYS]


def subtract(span: tuple[float, float], protect: list[tuple[float, float]]
             ) -> list[tuple[float, float]]:
    """What is left of ``span`` once every protected interval is carved out of it."""
    pieces = [span]
    for lo, hi in protect:
        nxt: list[tuple[float, float]] = []
        for a, b in pieces:
            if hi <= a or lo >= b:
                nxt.append((a, b))
                continue
            if a < lo:
                nxt.append((a, lo))
            if hi < b:
                nxt.append((hi, b))
        pieces = nxt
    return pieces


def dead_air_cuts(marks: list[float], duration: float,
                  protect: list[tuple[float, float]]) -> list[Cut]:
    """Every stretch of the take where nothing happened, minus what must stay on screen.

    The web lane does not need a transcript to find dead air: the take is *instrumented*. Every
    glide sample, press, scroll and beat is a timestamp, so a gap between two of them is, by
    construction, a gap in which the demo said nothing. What survives a cut is ``HOLD_PAD_S`` on
    each side, because a pause immediately after a click is the app answering — remove that and
    the video shows a cause with no effect.
    """
    cuts: list[Cut] = []
    marks = sorted(t for t in marks if 0.0 <= t <= duration)
    if not marks:
        return cuts

    # The head is pure waste: the recorder is rolling and the demo has not started.
    if marks[0] > DEAD_AIR_S:
        cuts.append(Cut(start=0.0, end=round(marks[0] - HOLD_PAD_S, 3), reason="head: nothing yet"))

    for a, b in zip(marks, marks[1:]):
        if b - a <= DEAD_AIR_S:
            continue
        for lo, hi in subtract((a + HOLD_PAD_S, b - HOLD_PAD_S), protect):
            if hi - lo >= MIN_CUT_S:
                cuts.append(Cut(start=round(lo, 3), end=round(hi, 3),
                                reason=f"dead air ({b - a:.1f}s with nothing happening)"))
    # The tail is left alone on purpose — it is the last thing the app did, which is the payoff.
    return cuts


def budget_by_beat(cuts: list[Cut], beats: list[Beat]) -> list[Cut]:
    """Let a cut spend only the seconds its beat has left over after the narration.

    Dead-air removal and narration pull in opposite directions, and dead air must lose. A shot
    trimmed to the last frame of activity is a shot the voice runs off the end of — so the budget
    for a beat is exactly its slack, and a beat whose line already overruns its picture is a beat
    that gets cut by nothing at all. Stretches belonging to no beat keep the full trim: nobody is
    talking over them.
    """
    if not beats:
        return cuts
    out: list[Cut] = []
    for beat in beats:
        inside = [c for c in cuts if beat.start <= (c.start + c.end) / 2 < beat.end]
        if not inside:
            continue
        allowed = max(beat.end - beat.start - beat.vo_s - BREATH_S, 0.0) if beat.vo_s else None
        total = sum(c.end - c.start for c in inside)
        if allowed is None or total <= allowed:
            out.extend(inside)
            continue
        if allowed < MIN_CUT_S:
            continue                                   # the line needs every frame of this shot
        factor = allowed / total                       # shrink evenly: an even trim keeps the pace
        for cut in inside:
            end = round(cut.start + (cut.end - cut.start) * factor, 3)
            if end - cut.start >= MIN_CUT_S:
                out.append(Cut(start=cut.start, end=end,
                               reason=f"{cut.reason}, trimmed to fit the narration"))
    covered = [c for c in cuts if any(b.start <= (c.start + c.end) / 2 < b.end for b in beats)]
    out.extend(c for c in cuts if c not in covered)
    return sorted(out, key=lambda c: c.start)


def intersect(span: tuple[float, float], spans: list[tuple[float, float]]
              ) -> list[tuple[float, float]]:
    """The parts of ``span`` that ``spans`` also covers."""
    a, b = span
    out = []
    for lo, hi in spans:
        left, right = max(a, lo), min(b, hi)
        if right - left > 1e-6:
            out.append((round(left, 3), round(right, 3)))
    return sorted(out)


def kept_spans(cuts: list[Cut], duration: float) -> list[tuple[float, float]]:
    """The complement of the cuts — what the viewer will actually be shown, in source time."""
    return [sp for sp in subtract((0.0, duration), [(c.start, c.end) for c in cuts])
            if sp[1] - sp[0] > 1e-6]


def select_beats(beats: list[Beat], zooms: list[Zoom], target_s: float,
                 keep: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Which beats survive a cut down to ``target_s``, and which are dropped.

    A 2.5-minute walkthrough and a 45-second reel are not the same film at different lengths — the
    reel has to *drop points*, not shorten them, because a point made in half a sentence is not
    made. So this picks beats rather than trimming them.

    Nothing here judges whether a beat is *interesting*; a script that scores its own footage for
    quality is a machine marking its own homework. It ranks on one thing that is actually measured:
    how much the demo **did** during the beat — presses per second of shot, and whether the camera
    found anything worth punching in on. A beat where the operator worked is a beat that shows the
    product working. The opening and closing beats are kept regardless: they are the frame, not a
    point, and a reel that starts mid-thought reads as a clip somebody stole.

    Returns ``(kept_ids, dropped_ids)`` in script order. Pass ``keep`` to pin ids by hand — the
    operator's ear beats the ranking every time it disagrees.
    """
    if not beats:
        return [], []
    pinned = set(keep) | {beats[0].id, beats[-1].id}

    def worth(beat: Beat) -> float:
        span = max(beat.end - beat.start, 0.1)
        presses = sum(z.clicks for z in zooms if beat.start <= z.start < beat.end)
        framed = any(beat.start <= z.start < beat.end for z in zooms)
        return presses / span + (0.5 if framed else 0.0)

    # Each beat costs its line, because a kept beat is played at the pace of its own narration.
    cost = {b.id: (b.vo_s + BREATH_S if b.vo_s else SILENT_HOLD_S) for b in beats}
    kept = {b.id for b in beats}
    order = sorted((b for b in beats if b.id not in pinned), key=worth)
    for beat in order:
        if sum(cost[i] for i in kept) <= target_s:
            break
        kept.discard(beat.id)
    return ([b.id for b in beats if b.id in kept],
            [b.id for b in beats if b.id not in kept])


def retimed_duration(cuts: list[Cut], retime: list[Retime], duration: float) -> float:
    """How long the take runs once the cuts are spent and the ramps applied."""
    kept = kept_spans(cuts, duration)
    total = sum(b - a for a, b in kept)
    for r in retime:
        for a, b in intersect((r.start, r.end), kept):
            total -= (b - a) - (b - a) / r.speed
    return round(total, 2)


def retime_to_voice(beats: list[Beat], zooms: list[Zoom], cuts: list[Cut], duration: float,
                    max_speed: float = MAX_SPEED_X) -> list[Retime]:
    """Play each beat fast enough that it ends when its sentence does.

    The cut can only remove stretches where nothing happened. This removes the other kind of
    slack — the beat where plenty happens, slowly, under one short line — by *ramping* it instead
    of deleting it, so the gesture is still shown and the words still land on top of it.

    Two spans of a beat are not equal, so they are not ramped equally:

    * a **punch-in stays at 1x**. A zoom already brackets the click and the app's answer, and that
      answer is the shot. Speeding it up throws away the only frames that prove the thing worked.
    * everything else — the glide across the screen, the slider crawl, the long scrub — carries the
      compression, at exactly the rate that makes the beat land on its line.

    When the punch-ins alone already outlast the narration there is nothing left to trade, so the
    whole beat is compressed uniformly rather than pretending it fits. Otherwise the ramps carry
    all of it, clamped at ``max_speed`` — a beat that cannot quite reach its line then runs a
    little long around punch-ins that still read, which is the trade worth making.
    """
    if not beats:
        return []
    kept = kept_spans(cuts, duration)
    holds = [(z.start, z.end) for z in zooms]
    out: list[Retime] = []

    for beat in beats:
        windows = intersect((beat.start, beat.end), kept)
        kept_s = sum(b - a for a, b in windows)
        if kept_s <= 0.05:
            continue
        target = (beat.vo_s + BREATH_S) if beat.vo_s else min(kept_s, SILENT_HOLD_S)
        if kept_s <= target + 0.05:
            continue                                   # the line already fills this shot

        ramps = [sp for w in windows for sp in subtract(w, holds) if sp[1] - sp[0] > 1e-6]
        ramp_s = sum(b - a for a, b in ramps)
        hold_s = kept_s - ramp_s

        # Is there anything left to trade once the punch-ins are paid for? If so the ramps carry
        # the whole compression, clamped — a beat that still runs a little long around a held
        # punch-in is a slow shot, which is survivable; a sped-up punch-in is a lost one.
        if ramp_s >= MIN_RAMP_S and hold_s < target - MIN_RAMP_S / max_speed:
            speed = round(min(max(ramp_s / max(target - hold_s, 1e-6), 1.0), max_speed), 2)
            spans, reason = ramps, "ramped to the line; punch-ins held at 1x"
        else:
            speed = round(min(max(kept_s / target, 1.0), max_speed), 2)
            spans, reason = windows, "whole beat compressed — the punch-ins alone outlast the line"
        if speed <= 1.01:
            continue
        for a, b in spans:
            if b - a >= 0.15:
                out.append(Retime(start=a, end=b, speed=speed, beat=beat.id, reason=reason))
    return sorted(out, key=lambda r: r.start)


def spoken_seconds(session_dir: Path, beat_id: str) -> float:
    """How long the line actually takes, once somebody (or something) has said it.

    A word count is a guess, and the two readers this pipeline has — ElevenLabs and a person —
    are nowhere near each other on pace. So the moment a real file exists it wins: the edit is
    budgeted against the performance, not against an average of English.
    """
    for ext in VO_EXTS:
        path = session_dir / "vo" / f"{beat_id}{ext}"
        if not path.exists():
            continue
        proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                               "-of", "default=nw=1:nk=1", str(path)],
                              capture_output=True, text=True)
        try:
            return round(float(proc.stdout.strip()), 3)
        except ValueError:
            return 0.0
    return 0.0


def read_beats(session_dir: Path, duration: float) -> list[Beat]:
    """The authored spine of the take: what each stretch of it is *saying*.

    A beat is written by the recorder at the moment it starts, so its window runs to the next
    beat. ``slack_s`` is the number the edit turns on — seconds of picture with no words over
    them. Positive slack is what ``cuts`` may spend; negative slack means the line is longer than
    the shot and the shot has to be held, not the voice hurried.
    """
    rows = [r for r in read_jsonl(session_dir / "beats.jsonl") if r.get("video_t") is not None]
    rows.sort(key=lambda r: r["video_t"])
    beats: list[Beat] = []
    for i, row in enumerate(rows):
        start = round(float(row["video_t"]), 3)
        end = round(float(rows[i + 1]["video_t"]), 3) if i + 1 < len(rows) else round(duration, 3)
        vo = (row.get("vo") or "").strip()
        beat_id = row.get("id") or f"beat-{i + 1}"
        spoken = spoken_seconds(session_dir, beat_id) if vo else 0.0
        lang = (row.get("lang") or "en").lower()
        pace = WORDS_PER_S_BY_LANG.get(lang.split("-")[0], WORDS_PER_S)
        vo_s = spoken or (round(len(vo.split()) / pace, 2) if vo else 0.0)
        beats.append(Beat(id=beat_id, start=start, end=max(end, start),
                          vo=vo, explain=(row.get("explain") or "").strip(),
                          show=(row.get("show") or "").strip(), vo_s=vo_s,
                          slack_s=round(max(end, start) - start - vo_s, 2),
                          vo_from="recorded" if spoken else ("estimate" if vo else "silent"),
                          lang=(row.get("lang") or "en").lower()))
    return beats


def build_plan(session_dir: Path, screen: tuple[int, int] | None = None,
               max_speed: float = MAX_SPEED_X, target_s: float = 0.0,
               pick: tuple[str, ...] = (), aim: bool = True) -> dict:
    manifest = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    t0 = manifest["t0_wallclock"]

    width, height = screen or (manifest.get("screen", {}).get("width", 0),
                               manifest.get("screen", {}).get("height", 0))
    if not width or not height:
        raise SystemExit(
            "screen size unknown — the recorder could not detect it. Re-run with "
            "--screen WIDTHxHEIGHT (the display OBS captured)."
        )
    diagonal = (1.0 ** 2 + (height / width) ** 2) ** 0.5

    events = read_jsonl(session_dir / "input.jsonl")
    clicks, key_times, off_screen = [], [], 0
    for event in events:
        if "ts" not in event:
            continue
        t = event["ts"] - t0
        if t < 0:
            continue                                   # keystrokes from before OBS went active
        if event.get("device") == "mouse" and event.get("type") == "click" and event.get("pressed"):
            x, y = event["x"] / width, event["y"] / height
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                off_screen += 1                        # second monitor, or the wrong screen size
                continue
            clicks.append({"t": t, "x": x, "y": y})
        elif event.get("device") == "keyboard" and event.get("type") == "press":
            key_times.append(t)

    clicks.sort(key=lambda c: c["t"])
    key_times.sort()

    # Two different questions, two different lists. `reactions` is where the app answered a press
    # — the seconds the retime must never speed up. `zooms` is where the *camera* goes, which is
    # allowed to sit still across several of them.
    reactions = merge_zooms([cluster_to_zoom(c) for c in cluster_clicks(clicks, diagonal)])
    # Aim before settling: two presses whose *answers* land in the same place are one held shot even
    # when the buttons are at opposite ends of a rail, and settling on the un-aimed points would
    # never see that.
    reactions, aim_notes = aim_zooms(reactions, session_dir / "screen.mp4", clicks, diagonal, aim)
    zooms = settle_zooms(reactions, diagonal)
    chapters = [Chapter(t=round(w["video_t"], 3), title=w["title"])
                for w in read_jsonl(session_dir / "windows.jsonl")
                if w.get("video_t", -1) >= 0]

    duration = float(manifest.get("duration_s") or 0.0)
    beats = read_beats(session_dir, duration)
    # Anything with a timestamp is something happening — including a beat mark, so the cutter can
    # never swallow the moment a line of narration starts.
    marks = ([e["ts"] - t0 for e in events if "ts" in e]
             + [b.start for b in beats] + [c.t for c in chapters])
    # A punch-in already on screen is not dead air, whatever the input log says: cutting inside a
    # camera move jumps the frame.
    cuts = budget_by_beat(
        dead_air_cuts(marks, duration, protect=[(z.start, z.end) for z in zooms]), beats)

    # A reel is not the walkthrough trimmed — it is fewer points, each still made in full. So a
    # length target drops whole beats before anything else is spent, and everything after this
    # plans the short film rather than a squeezed long one.
    dropped: list[str] = []
    if target_s or pick:
        keep_ids, dropped = select_beats(beats, zooms, target_s or 1e9, keep=pick)
        if pick:
            keep_ids = [b.id for b in beats if b.id in set(pick) | {beats[0].id, beats[-1].id}]
            dropped = [b.id for b in beats if b.id not in keep_ids]
        gone = [b for b in beats if b.id in set(dropped)]
        cuts = [c for c in cuts
                if not any(g.start <= (c.start + c.end) / 2 < g.end for g in gone)]
        cuts += [Cut(start=g.start, end=g.end,
                     reason=f"cut down to {round(target_s, 1)}s: beat {g.id!r} dropped")
                 for g in gone]
        cuts.sort(key=lambda c: c.start)
        beats = [b for b in beats if b.id not in set(dropped)]

    saved = round(sum(c.end - c.start for c in cuts), 2)
    # Cutting removes the seconds where nothing happened. Retiming pays for the seconds where
    # something happened too slowly for the sentence over it — which, measured, is the larger half.
    retime = retime_to_voice(beats, reactions, cuts, duration, max_speed)

    return {
        "session_id": manifest.get("session_id"),
        "name": manifest.get("name"),
        "duration_s": manifest.get("duration_s"),
        "clock_source": manifest.get("clock_source"),
        "screen": {"width": width, "height": height},
        "coordinates": "normalised 0..1 of the captured display; seconds are video time",
        "zooms": [asdict(z) for z in zooms],
        "chapters": [asdict(c) for c in chapters],
        "typing": [asdict(t) for t in typing_runs(key_times)],
        "beats": [asdict(b) for b in beats],
        "lang": (beats[0].lang if beats else (manifest.get("lang") or "en")),
        "beats_source": ("script (webrec beat marks)" if beats
                         else "none — this take was recorded without a beat spine"),
        "warnings": ([f"{off_screen} clicks fell outside the screen — wrong display or "
                      f"multi-monitor take"] if off_screen else []),
        "aim_notes": aim_notes,
        "aimed": sum(1 for z in zooms if z.aim == "change"),
        "cuts": [asdict(c) for c in cuts],
        # The web lane is instrumented, so dead air is a fact about the log, not a guess about
        # speech. A *narrated desktop* take still wants word timings on top of this to catch the
        # pauses a speaker leaves while the mouse keeps moving; course-watcher owns those.
        "cuts_source": ("instrumented: gaps in input, beats and chapters — budgeted against the "
                        "narration" if beats else
                        "instrumented: gaps in input, beats and chapters"),
        "selected": [b.id for b in beats],
        "dropped": dropped,
        "target_s": target_s or None,
        "cuts_saving_s": saved,
        "duration_after_cuts_s": round(duration - saved, 2) if duration else None,
        "retime": [asdict(r) for r in retime],
        "retime_source": ("the measured read: each beat is played fast enough to end when its "
                          "line does, punch-ins held at 1x" if retime else
                          "none — every beat already ends close to its line"),
        "retime_max_speed": max_speed,
        "duration_after_retime_s": (retimed_duration(cuts, retime, duration) if duration
                                    else None),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an explainer edit plan from a session bundle.")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--screen", default="", help="override detected desktop size, e.g. 2560x1440")
    parser.add_argument("--json", action="store_true", help="print the plan instead of a summary")
    parser.add_argument("--max-speed", type=float, default=MAX_SPEED_X,
                        help=f"fastest a beat may be ramped to reach its line (default {MAX_SPEED_X})")
    parser.add_argument("--target", type=float, default=0.0, metavar="SECONDS",
                        help="cut down to a reel: drop the least-eventful beats until the read "
                             "fits this length (the first and last beat are always kept)")
    parser.add_argument("--no-aim", action="store_true",
                        help="do not sample the footage — leave every punch-in on its click")
    parser.add_argument("--pick", default="", metavar="IDS",
                        help="comma-separated beat ids to keep, instead of the ranking")
    parser.add_argument("--no-retime", action="store_true",
                        help="plan the cuts only — leave every beat at its recorded pace")
    args = parser.parse_args()

    screen = None
    if args.screen:
        w, h = args.screen.lower().split("x")
        screen = (int(w), int(h))

    plan = build_plan(args.session_dir, screen,
                      max_speed=1.0 if args.no_retime else args.max_speed,
                      target_s=args.target,
                      pick=tuple(i.strip() for i in args.pick.split(",") if i.strip()),
                      aim=not args.no_aim)
    (args.session_dir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(f"{plan['name']}  ({plan['duration_s']}s, clock={plan['clock_source']})")
        print(f"  zooms    : {len(plan['zooms'])}"
              + (f"  ({plan['aimed']} aimed at the change, not the click)" if plan.get("aimed")
                 else ""))
        for note in plan.get("aim_notes", []):
            print(f"      {note}")
        print(f"  chapters : {len(plan['chapters'])}")
        print(f"  typing   : {len(plan['typing'])} runs")
        voiced = sum(1 for b in plan["beats"] if b["vo_from"] == "recorded")
        print(f"  beats    : {len(plan['beats'])}  ({plan['beats_source']})"
              + (f" · {voiced} timed against a real read" if voiced else ""))
        print(f"  cuts     : {len(plan['cuts'])} · {plan['cuts_saving_s']}s out "
              f"→ {plan['duration_after_cuts_s']}s")
        if plan["dropped"]:
            print(f"  selected : {len(plan['selected'])} beat(s) kept for a "
                  f"{plan['target_s'] or '—'}s cut · dropped {', '.join(plan['dropped'])}")
        if plan["retime"]:
            ramped = sorted({r["beat"] for r in plan["retime"]})
            fastest = max(r["speed"] for r in plan["retime"])
            print(f"  retime   : {len(ramped)} of {len(plan['beats'])} beats ramped "
                  f"(up to {fastest}x) → {plan['duration_after_retime_s']}s")
            for beat in plan["beats"]:
                spans = [r for r in plan["retime"] if r["beat"] == beat["id"]]
                if spans:
                    print(f"      {beat['id']:14} {round(beat['end'] - beat['start'], 1):>6}s of "
                          f"picture on a {beat['vo_s']}s line → {spans[0]['speed']}x")
        for beat in plan["beats"]:
            if beat["slack_s"] < 0:
                print(f"  ! beat {beat['id']!r}: the line needs {beat['vo_s']}s and the shot is "
                      f"{round(beat['end'] - beat['start'], 2)}s — hold the picture, not the voice")
        for warning in plan["warnings"]:
            print(f"  ! {warning}")
        print(f"  written  : {args.session_dir / 'plan.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
