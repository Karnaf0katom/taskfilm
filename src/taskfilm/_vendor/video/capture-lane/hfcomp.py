#!/usr/bin/env python3
"""hfcomp — turn a recorded session bundle into a HyperFrames composition.

`plan.py` ends at a description of the edit: punch in here, at this point, this deep; a chapter
starts here. It deliberately stops short of any framework. This is the step that spends that plan
— it writes a real HyperFrames project whose timeline already carries the moves, so the take
arrives as something to *direct* rather than something to cut from scratch.

What it emits, and why each piece is shaped that way:

  * **the recording as the base track** — one `<video>` carrying its own `data-start`/`data-duration`,
    wrapped in a *non-timed* camera div. HyperFrames rejects a timed wrapper around timed media
    (the clip then shows the wrong source frames and vanishes mid-slot), and it forbids animating
    a timed media element's own geometry. A non-timed wrapper is the one shape that satisfies both.
  * **punch-ins** — `transformOrigin` is snapped to the click point while the camera is at rest, and
    only `scale` is tweened. Interpolating an origin *and* a scale at once slides the frame sideways
    on the way in, which reads as a camera fighting itself.
  * **chapter chips** — a lower third, not a full card. The point of a software explainer is the
    software; a chapter marker that covers it defeats the take.

Usage:
    python hfcomp.py <session-dir> [--out DIR] [--max-scale 1.8] [--no-title] [--check]
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
from pathlib import Path

# A punch-in that snaps is a jump cut; one that takes a full second is a documentary. These are the
# in/out lengths, and they compress rather than overlap when a zoom's window is short.
PUNCH_IN_S = 0.55
PUNCH_OUT_S = 0.5
MIN_HOLD_S = 0.25

CHIP_IN_S = 0.45
CHIP_OUT_S = 0.35
CHIP_HOLD_S = 2.6          # long enough to read a five-word title, short enough not to nag

# An explain is the beat's *label* — the words the picture cannot say. Opposite corner from the
# chapter chip on purpose: two pieces of text in the same corner read as one broken one.
NOTE_IN_S = 0.5
NOTE_OUT_S = 0.4
NOTE_HOLD_S = 3.2

TITLE_CARD_S = 2.8
TITLE_OUT_S = 0.7

HYPERFRAMES_VERSION = os.environ.get("CAPTURE_HYPERFRAMES_VERSION", "0.8.17")

# Right-to-left languages. Only the type flips: the page stays LTR so the camera, the vignette and
# the chip's own anchor are not mirrored along with the words.
RTL_LANGS = {"he", "ar", "fa", "ur", "yi"}
# Installed on the render box already (`fc-list :lang=he`), so a Hebrew cut needs no webfont and
# the render stays deterministic — frame 1 is never a row of fallback boxes.
HEBREW_STACK = 'Heebo, Assistant, Rubik, "Noto Sans Hebrew"'
# ...but "installed" is not something the renderer can infer. Without a declaration it assumes the
# family is a webfont it failed to fetch and falls back, so a Hebrew cut silently renders in the
# wrong face. local() names the installed file and asks for no download.
HEBREW_FACES = "\n".join(
    f"""      @font-face {{ font-family: {family}; src: local('{local}');
        font-display: swap; }}"""
    for family, local in (("Heebo", "Heebo"), ("Assistant", "Assistant"), ("Rubik", "Rubik"),
                          ('"Noto Sans Hebrew"', "Noto Sans Hebrew")))
GSAP_CDN = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"


def load_bundle(session_dir: Path) -> tuple[dict, dict]:
    plan_path = session_dir / "plan.json"
    if not plan_path.exists():
        raise SystemExit(f"no plan.json in {session_dir} — run plan.py on the bundle first")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    manifest_path = session_dir / "session.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    return plan, manifest


def kept_segments(plan: dict) -> list[tuple[float, float, float]]:
    """What survives the edit, in source time: ``(start, end, speed)`` per segment.

    Two passes decide it and they are different problems. ``plan.cuts`` **removes** the stretches
    where nothing happened; ``plan.retime`` **ramps** the stretches where something happened too
    slowly for the sentence over it. Both arrive here as source-time spans and leave as one list,
    so everything downstream — the punch-ins, the chips, the narration, the render — sees a single
    take that simply *is* shorter and never has to know which pass paid for it.
    """
    duration = float(plan["duration_s"])
    cuts = sorted(((float(c["start"]), float(c["end"])) for c in plan.get("cuts", [])),
                  key=lambda c: c[0])
    kept: list[tuple[float, float]] = []
    head = 0.0
    for lo, hi in cuts:
        lo, hi = max(lo, 0.0), min(hi, duration)
        if hi <= head:
            continue
        if lo > head:
            kept.append((round(head, 3), round(lo, 3)))
        head = hi
    if head < duration:
        kept.append((round(head, 3), round(duration, 3)))

    ramps = sorted(((float(r["start"]), float(r["end"]), float(r.get("speed", 1.0)))
                    for r in plan.get("retime", []) if float(r.get("speed", 1.0)) > 1.0),
                   key=lambda r: r[0])
    out: list[tuple[float, float, float]] = []
    for a, b in kept:
        # Split the kept span wherever a ramp starts or ends, so each piece carries one speed.
        edges = sorted({a, b} | {e for lo, hi, _ in ramps for e in (lo, hi) if a < e < b})
        for lo, hi in zip(edges, edges[1:]):
            mid = (lo + hi) / 2
            speed = next((sp for rl, rh, sp in ramps if rl <= mid < rh), 1.0)
            out.append((round(lo, 3), round(hi, 3), speed))
    return [seg for seg in out if seg[1] - seg[0] > 0.04]


def is_edited(segments: list) -> bool:
    """Does this edit actually change the file? More than one piece, or any piece not at 1x."""
    return len(segments) > 1 or any(len(s) > 2 and s[2] != 1.0 for s in segments)


def time_map(segments: list):
    """Source second → cut second. A time inside a removed stretch lands on the seam.

    Every number in the plan — a punch-in, a chapter, the moment a line of narration starts — was
    measured against the *recording*. The cut renumbers the video, so all of them have to be
    renumbered through the same function or the moves drift off the clicks that caused them.
    """
    spans = [(s[0], s[1], (s[2] if len(s) > 2 else 1.0)) for s in segments]
    offsets, run = [], 0.0
    for a, b, speed in spans:
        offsets.append(run)
        run += (b - a) / speed

    def to_cut(t: float) -> float:
        for (a, b, speed), off in zip(spans, offsets):
            if t < a:
                return round(off, 3)                    # inside a removed stretch: snap to the seam
            if t <= b:
                return round(off + (t - a) / speed, 3)
        return round(run, 3)

    to_cut.total = round(run, 3)                        # type: ignore[attr-defined]
    return to_cut


def tighten(video: Path, out_path: Path, segments: list) -> bool:
    """Write the cut as a real file rather than as timeline arithmetic.

    One video element with one continuous source is the shape HyperFrames is happiest with, and a
    deterministic render cannot be asked to skip inside a clip. So the cuts are spent here, once,
    and everything downstream sees a take that simply *is* shorter.
    """
    filters, streams = [], ""
    for i, seg in enumerate(segments):
        a, b = seg[0], seg[1]
        speed = seg[2] if len(seg) > 2 else 1.0
        pts = "PTS-STARTPTS" if speed == 1.0 else f"(PTS-STARTPTS)/{speed}"
        filters.append(f"[0:v]trim=start={a}:end={b},setpts={pts}[v{i}]")
        streams += f"[v{i}]"
    filters.append(f"{streams}concat=n={len(segments)}:v=1:a=0[out]")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
         "-filter_complex", ";".join(filters), "-map", "[out]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         str(out_path)],
        capture_output=True, text=True)
    return proc.returncode == 0 and out_path.exists()


def explains(plan: dict, to_cut, under_title_until: float = 0.0) -> list[dict]:
    """A beat's label, placed where the beat starts and gone before it outstays the point."""
    beats = [b for b in plan.get("beats", []) if (b.get("explain") or "").strip()]
    heads: list[dict] = []
    for i, beat in enumerate(beats):
        # A label behind the opening card is a label nobody sees. It waits for the card rather
        # than being thrown away — the first beat is usually the one that earns the watch.
        head = max(to_cut(float(beat["start"])), under_title_until)
        heads.append({"t": round(head, 3), "text": beat["explain"].strip(),
                      "id": beat.get("id") or f"beat-{i + 1}"})
    heads = drop_crowded(heads, to_cut.total, NOTE_IN_S + 0.8 + NOTE_OUT_S)
    notes: list[dict] = []
    for i, note in enumerate(heads):
        head = note["t"]
        nxt = heads[i + 1]["t"] if i + 1 < len(heads) else to_cut.total
        # Gone before the next one arrives: two of these on screen at once is one unreadable one.
        hold = max(min(NOTE_HOLD_S, nxt - head - NOTE_IN_S - NOTE_OUT_S - 0.15), 0.8)
        notes.append({**note, "hold": round(hold, 3)})
    return [n for n in notes if n["t"] < to_cut.total - 0.4]


def narration(plan: dict, to_cut) -> list[dict]:
    """The read, with the timing already decided by the picture.

    This is emitted as a script rather than spoken here on purpose: the voice is a person, and a
    person needs to see where each line lands and how long it has. ``over_s`` is the honest
    number — how much longer the line will take to read than the shot it sits on.
    """
    lines: list[dict] = []
    beats = [b for b in plan.get("beats", []) if (b.get("vo") or "").strip()]
    for i, beat in enumerate(beats):
        head = to_cut(float(beat["start"]))
        nxt = to_cut(float(beats[i + 1]["start"])) if i + 1 < len(beats) else to_cut.total
        shot = round(nxt - head, 2)
        lines.append({"id": beat.get("id") or f"beat-{i + 1}", "at": round(head, 3),
                      "shot_s": shot, "est_s": float(beat.get("vo_s") or 0.0),
                      "over_s": round(float(beat.get("vo_s") or 0.0) - shot, 2),
                      "text": beat["vo"].strip()})
    return lines


def remap_plan(plan: dict, to_cut) -> dict:
    """The same edit, renumbered against the tightened take."""
    out = dict(plan)
    out["duration_s"] = to_cut.total
    out["zooms"] = []
    for zoom in plan.get("zooms", []):
        start, end = to_cut(float(zoom["start"])), to_cut(float(zoom["end"]))
        if end - start < 0.4:
            continue                                   # the whole move fell inside a removed stretch
        out["zooms"].append({**zoom, "start": start, "end": end})
    out["chapters"] = [{**c, "t": to_cut(float(c["t"]))} for c in plan.get("chapters", [])]
    out["beats"] = [{**b, "start": to_cut(float(b["start"])), "end": to_cut(float(b["end"]))}
                    for b in plan.get("beats", [])]
    return out


def drop_crowded(items: list[dict], duration: float, min_window: float) -> list[dict]:
    """Keep only the labels that have room to be read, latest-wins."""
    kept: list[dict] = []
    for item in reversed(items):
        nxt = kept[0]["t"] if kept else duration
        if nxt - item["t"] >= min_window:
            kept.insert(0, item)
    return kept


def chapter_chips(plan: dict, drop_title: str | None) -> list[dict]:
    """The chapters worth putting on screen.

    Three kinds get dropped: the opening title (it is already the title card), a raw URL (a route
    is a chapter boundary, not a caption an audience wants to read), and a repeat of the title
    already on screen — an SPA can re-announce the same view twice in four seconds.
    """
    chips: list[dict] = []
    for chapter in plan.get("chapters", []):
        title = (chapter.get("title") or "").strip()
        head = float(chapter["t"])
        if not title or title.startswith(("http://", "https://")):
            continue
        if drop_title and title == drop_title and not chips:
            continue
        if chips and chips[-1]["title"] == title:
            continue
        # A chip under the title card is a caption nobody can read. The opening chapter is what
        # the card is *for*, so it is the card's job, not a second label behind it.
        if drop_title and head < TITLE_CARD_S:
            continue
        chips.append({"t": head, "title": title})
    # A chip must not outlive the take, and two chips must not stack on top of each other.
    duration = float(plan["duration_s"])
    # Two chapters a second apart are two chips nobody can read. The *later* one is the better
    # label for what is on screen after it, so the crowded one to drop is the earlier.
    chips = drop_crowded(chips, duration, CHIP_IN_S + 0.9 + CHIP_OUT_S)
    for i, chip in enumerate(chips):
        nxt = chips[i + 1]["t"] if i + 1 < len(chips) else duration
        chip["hold"] = max(min(CHIP_HOLD_S,
                               nxt - chip["t"] - CHIP_IN_S - CHIP_OUT_S - 0.15), 0.9)
    return [c for c in chips if c["t"] < duration - 0.4]


def punches(plan: dict, max_scale: float) -> list[dict]:
    out: list[dict] = []
    duration = float(plan["duration_s"])
    for zoom in plan.get("zooms", []):
        start, end = float(zoom["start"]), min(float(zoom["end"]), duration)
        span = end - start
        if span < PUNCH_IN_S + PUNCH_OUT_S + MIN_HOLD_S:
            # Too short to breathe. Compress the move rather than dropping the moment.
            in_s = out_s = max(span * 0.35, 0.2)
        else:
            in_s, out_s = PUNCH_IN_S, PUNCH_OUT_S
        out.append({
            "start": round(start, 3),
            "in_s": round(in_s, 3),
            "out_at": round(max(end - out_s, start + in_s), 3),
            "out_s": round(out_s, 3),
            "scale": round(min(float(zoom["scale"]), max_scale), 3),
            "ox": round(float(zoom["x"]) * 100, 2),
            "oy": round(float(zoom["y"]) * 100, 2),
            "clicks": zoom.get("clicks", 1),
        })
    return out


def copy_font_asset(out_dir: Path, font_file: Path | None = None) -> str | None:
    """Optional portable font, copied once by this adapter and reused by reel."""
    configured = font_file or os.environ.get("CAPTURE_COMPOSITION_FONT")
    if not configured:
        return None
    source = Path(configured)
    if not source.is_file() or source.suffix.lower() not in {".ttf", ".otf", ".woff", ".woff2"}:
        raise ValueError("composition font must be an existing TTF/OTF/WOFF/WOFF2 file")
    target = out_dir / "assets" / ("capture-font" + source.suffix.lower())
    shutil.copy2(source, target)
    if notice := os.environ.get("CAPTURE_COMPOSITION_FONT_NOTICE"):
        shutil.copy2(notice, out_dir / "assets/FONT-LICENSE.txt")
    return target.name


def build_html(plan: dict, video_name: str, chips: list[dict], moves: list[dict],
               width: int, height: int, title: str | None, notes: list[dict] | None = None,
               voice: list[dict] | None = None, lang: str = "en", font_file: str | None = None,
               note_top: int = 68) -> str:
    duration = round(float(plan["duration_s"]), 3)
    esc = html.escape
    rtl = lang.split("-")[0].lower() in RTL_LANGS
    font_head = (HEBREW_STACK + ", ") if rtl else ""
    font_faces = (HEBREW_FACES + "\n") if rtl else ""
    primary_font = font_head + "Inter"
    if font_file:
        primary_font = "CaptureFont"
        font_faces = (f'      @font-face {{ font-family: CaptureFont; src: url("assets/{font_file}"); '
                      'font-weight: 100 900; font-display: block; }\n')
    text_dir = "rtl" if rtl else "ltr"

    chip_nodes = "\n".join(
        f'''      <div class="overlay clip" id="chip-{i}" data-start="{chip['t']:.3f}"
           data-duration="{chip['hold'] + CHIP_IN_S + CHIP_OUT_S:.3f}" data-track-index="2">
        <div class="chip" id="chip-{i}-visual">
        <span class="chip-rule"></span><span class="chip-text">{esc(chip['title'])}</span>
        </div>
      </div>'''
        for i, chip in enumerate(chips))

    notes = notes or []
    note_nodes = "\n".join(
        f'''      <div class="overlay clip" id="note-{i}" data-start="{note['t']:.3f}"
           data-duration="{note['hold'] + NOTE_IN_S + NOTE_OUT_S:.3f}" data-track-index="4">
        <div class="note" id="note-{i}-visual">
        <span class="note-dot"></span><span class="note-text">{esc(note['text'])}</span>
        </div>
      </div>'''
        for i, note in enumerate(notes))

    # One track per line. Two reads sharing a track is how a line that overran gets *mixed* into
    # the next one instead of being heard as the overrun it is.
    voice_nodes = "\n".join(
        f'''      <audio id="vo-{esc(v['id'])}" src="{v['file']}" data-start="{v['at']:.3f}"
           data-duration="{v['s']:.3f}" data-track-index="{5 + i}"></audio>'''
        for i, v in enumerate(voice or []))

    title_node = ""
    if title:
        title_node = f'''      <div class="overlay clip" id="titlecard" data-start="0"
           data-duration="{TITLE_CARD_S:.3f}" data-track-index="3">
        <div class="titlecard" id="titlecard-visual">
        <div class="titlecard-inner">
          <span class="titlecard-kicker">screen recording</span>
          <h1 class="titlecard-h">{esc(title)}</h1>
        </div>
        </div>
      </div>'''

    tweens = []
    for i, move in enumerate(moves):
        # The origin is snapped, not tweened: the camera is at rest here, so the jump is invisible,
        # and tweening an origin alongside a scale drifts the frame sideways on the way in.
        tweens.append(
            f'  tl.set(cam, {{ transformOrigin: "{move["ox"]}% {move["oy"]}%" }}, {move["start"]});')
        tweens.append(
            f'  tl.to(cam, {{ scale: {move["scale"]}, duration: {move["in_s"]}, '
            f'ease: "power2.out" }}, {move["start"]});')
        tweens.append(
            f'  tl.to(cam, {{ scale: 1, duration: {move["out_s"]}, ease: "power2.inOut" }}, '
            f'{move["out_at"]});')
    for i, chip in enumerate(chips):
        head = chip["t"]
        tweens.append(
            f'  tl.fromTo("#chip-{i}-visual", {{ xPercent: -14, autoAlpha: 0 }}, '
            f'{{ xPercent: 0, autoAlpha: 1, duration: {CHIP_IN_S}, ease: "power3.out" }}, {head:.3f});')
        tweens.append(
            f'  tl.to("#chip-{i}-visual", {{ autoAlpha: 0, duration: {CHIP_OUT_S}, ease: "power2.in" }}, '
            f'{head + CHIP_IN_S + chip["hold"]:.3f});')
    for i, note in enumerate(notes):
        head = note["t"]
        tweens.append(
            f'  tl.fromTo("#note-{i}-visual", {{ xPercent: 12, autoAlpha: 0 }}, '
            f'{{ xPercent: 0, autoAlpha: 1, duration: {NOTE_IN_S}, ease: "power3.out" }}, '
            f'{head:.3f});')
        tweens.append(
            f'  tl.to("#note-{i}-visual", {{ autoAlpha: 0, y: -10, duration: {NOTE_OUT_S}, '
            f'ease: "power2.in" }}, {head + NOTE_IN_S + note["hold"]:.3f});')
    if title:
        tweens.append(
            f'  tl.fromTo("#titlecard .titlecard-inner", {{ y: 26, autoAlpha: 0 }}, '
            f'{{ y: 0, autoAlpha: 1, duration: 0.7, ease: "power3.out" }}, 0.15);')
        tweens.append(
            f'  tl.to("#titlecard-visual", {{ autoAlpha: 0, duration: {TITLE_OUT_S}, ease: "power2.inOut" }}, '
            f'{TITLE_CARD_S - TITLE_OUT_S:.3f});')

    tween_block = "\n".join(tweens) if tweens else "  // no zooms and no chapters in this plan"

    return f'''<!doctype html>
<html lang="{lang}" data-resolution="landscape">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <title>{esc(plan.get("name") or "capture-lane take")}</title>
    <script src="{GSAP_CDN}"></script>
    <style>
{font_faces}      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {width}px; height: {height}px; overflow: hidden; background: #05070c; }}
      body {{ font-family: {primary_font}, ui-sans-serif, system-ui, -apple-system,
        "Segoe UI", sans-serif; }}
      #root {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; }}
      .overlay {{ position: absolute; inset: 0; pointer-events: none; }}

      /* The stage clips the punch-in; the camera is the thing that moves. Neither is timed, so
         neither fights the framework for ownership of the video clip's window. */
      .stage {{ position: absolute; inset: 0; overflow: hidden; background: #05070c; }}
      .camera {{ position: absolute; inset: 0; will-change: transform; }}
      .camera video {{ width: 100%; height: 100%; object-fit: cover; display: block; }}

      /* A screen recording is a rectangle of UI on a flat field; the vignette is what stops it
         reading as a screenshot someone left playing. */
      .vignette {{ position: absolute; inset: 0; pointer-events: none;
        background: radial-gradient(120% 92% at 50% 46%, rgba(0,0,0,0) 55%, rgba(0,0,0,.42) 100%); }}

      .chip {{ position: absolute; left: 64px; bottom: 76px; display: flex; align-items: center;
        gap: 18px; padding: 18px 30px 18px 24px; border-radius: 14px;
        background: rgba(8,13,22,.86); border: 1px solid rgba(148,163,184,.26);
        box-shadow: 0 22px 60px rgba(0,0,0,.5); backdrop-filter: blur(10px); }}
      .chip-rule {{ width: 5px; height: 30px; border-radius: 3px;
        background: linear-gradient(180deg, #38bdf8, #6366f1); }}
      .chip-text {{ font-size: 34px; font-weight: 600; letter-spacing: -.012em; color: #f1f5f9;
        line-height: 1.15; direction: {text_dir}; }}

      /* Opposite corner from the chapter chip, and quieter than it: the chip says where we
         are, the note says what to notice. Same voice, half the weight. */
      .note {{ position: absolute; right: 64px; top: {note_top}px; display: flex; align-items: center;
        gap: 14px; padding: 14px 24px; border-radius: 999px;
        background: rgba(8,13,22,.78); border: 1px solid rgba(125,211,252,.28);
        box-shadow: 0 16px 44px rgba(0,0,0,.42); backdrop-filter: blur(10px); }}
      .note-dot {{ width: 9px; height: 9px; border-radius: 50%; background: #38bdf8;
        box-shadow: 0 0 0 5px rgba(56,189,248,.16); flex: none; }}
      .note-text {{ font-size: 26px; font-weight: 500; letter-spacing: -.008em; color: #dbeafe;
        line-height: 1.15; white-space: nowrap; direction: {text_dir}; }}

      .titlecard {{ position: absolute; inset: 0; display: grid; place-items: center;
        background: linear-gradient(160deg, rgba(5,7,12,.96), rgba(9,14,26,.93)); }}
      .titlecard-inner {{ text-align: center; padding: 0 140px; direction: {text_dir}; }}
      .titlecard-kicker {{ display: block; font-size: 20px; letter-spacing: .34em;
        text-transform: uppercase; color: #7dd3fc; margin-bottom: 26px; }}
      .titlecard-h {{ font-size: 84px; line-height: 1.06; font-weight: 700; letter-spacing: -.03em;
        color: #f8fafc; }}
    </style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="{duration}"
      data-width="{width}"
      data-height="{height}"
    >
      <div class="stage">
        <div class="camera" id="camera" data-layout-allow-overflow>
          <video
            id="screen"
            src="assets/{video_name}"
            data-start="0"
            data-duration="{duration}"
            data-track-index="0"
            muted
            playsinline
          ></video>
        </div>
      </div>
      <div class="vignette"></div>

{chip_nodes}
{note_nodes}
{voice_nodes}
{title_node}
    </div>

    <script>
      const tl = gsap.timeline({{ paused: true }});
      const cam = document.getElementById("camera");
{tween_block}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
'''


VO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".opus")


def audio_seconds(path: Path) -> float:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=nw=1:nk=1", str(path)],
                          capture_output=True, text=True)
    try:
        return round(float(proc.stdout.strip()), 3)
    except ValueError:
        return 0.0


def place_voice(lines: list[dict], vo_dir: Path, out_dir: Path) -> list[dict]:
    """Lay a recorded read onto the timeline at the times the picture already decided.

    One file per beat id, so a line can be re-read on its own without re-recording the whole
    script — the thing that actually happens when a narrator flubs one sentence. A read longer
    than its shot is reported rather than squeezed: the picture is what moves.
    """
    placed: list[dict] = []
    if not vo_dir.is_dir():
        return placed
    for line in lines:
        found = next((vo_dir / f"{line['id']}{ext}" for ext in VO_EXTS
                      if (vo_dir / f"{line['id']}{ext}").exists()), None)
        if found is None:
            continue
        (out_dir / "assets" / "vo").mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, out_dir / "assets" / "vo" / found.name)
        length = audio_seconds(found) or line["est_s"]
        placed.append({"id": line["id"], "file": f"assets/vo/{found.name}",
                       "at": line["at"], "s": round(length, 3),
                       "over_s": round(length - line["shot_s"], 2)})
    return placed


def write_vo_script(out_dir: Path, plan: dict, lines: list[dict]) -> None:
    """The read, as a person can actually perform it.

    A narrator needs three things the JSON does not give them: the line, when it lands, and
    whether it fits. ``over`` is the one that changes the take — a line the shot cannot hold is
    a line to shorten, not a voice to hurry.
    """
    rows = ["| # | at | shot | line | fits? |", "|---|---|---|---|---|"]
    for i, line in enumerate(lines, 1):
        fits = "yes" if line["over_s"] <= 0 else f"**{line['over_s']}s too long**"
        rows.append(f"| {i} | {line['at']:.1f}s | {line['shot_s']:.1f}s | {line['text']} | {fits} |")
    (out_dir / "VO.md").write_text(
        f"# Narration — {plan.get('name') or 'take'}\n\n"
        f"Read against the cut in `assets/screen.mp4`. Times are seconds from the first frame.\n"
        f"A line marked *too long* is a line to cut words from — never a line to read faster.\n\n"
        + "\n".join(rows) + "\n", encoding="utf-8")
    (out_dir / "narration.json").write_text(json.dumps(lines, indent=2) + "\n", encoding="utf-8")


def emit(session_dir: Path, out_dir: Path, max_scale: float | None, want_title: bool,
         width: int, height: int, keep_dead_air: bool = False,
         vo_dir: Path | None = None, font_file: Path | None = None, note_top: int = 68) -> dict:
    if type(note_top) is not int or not 0 <= note_top < height:
        raise ValueError("note offset must be inside the output height")
    plan, manifest = load_bundle(session_dir)
    video = session_dir / "screen.mp4"
    if not video.exists():
        raise SystemExit(f"no screen.mp4 in {session_dir} — the take never encoded")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assets").mkdir(exist_ok=True)
    font_asset = copy_font_asset(out_dir, font_file)

    # Spend the cuts on the file, then renumber the edit against it. Doing it in this order means
    # nothing downstream — the punch-ins, the chips, the notes, the render — has to know that a
    # cut ever happened.
    segments = [] if keep_dead_air else kept_segments(plan)
    cut_s = ramp_s = 0.0
    if is_edited(segments) and tighten(video, out_dir / "assets" / "screen.mp4", segments):
        to_cut = time_map(segments)
        cut_s = round(sum(float(c["end"]) - float(c["start"])
                          for c in plan.get("cuts", [])), 2)
        ramp_s = round(float(plan["duration_s"]) - to_cut.total - cut_s, 2)
        plan = remap_plan(plan, to_cut)
    else:
        shutil.copy2(video, out_dir / "assets" / video.name)
        to_cut = time_map([(0.0, float(plan["duration_s"]))])
    video = out_dir / "assets" / "screen.mp4"

    # How deep a punch-in may go depends on whether there are real pixels behind it. A take
    # recorded at the output size is magnifying native pixels; one recorded smaller was already
    # upscaled once before the zoom, and 2x on top of that is mush.
    if max_scale is None:
        native = int(plan.get("screen", {}).get("width", 0)) >= width
        max_scale = 2.0 if native else 1.8

    title = (plan.get("name") or "").strip() if want_title else None
    chips = chapter_chips(plan, drop_title=title)
    moves = punches(plan, max_scale)
    # The plan is already renumbered, so an identity map is the right thing to read it with.
    here = time_map([(0.0, float(plan["duration_s"]))])
    notes = explains(plan, here, under_title_until=(TITLE_CARD_S + 0.1) if title else 0.0)
    lines = narration(plan, here)

    voice = place_voice(lines, vo_dir or (session_dir / "vo"), out_dir) if lines else []

    lang = plan.get("lang") or manifest.get("lang") or "en"
    (out_dir / "index.html").write_text(
        build_html(plan, video.name, chips, moves, width, height, title, notes, voice, lang, font_asset, note_top),
        encoding="utf-8")
    if lines:
        write_vo_script(out_dir, plan, lines)
    (out_dir / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
        "paths": {"blocks": "compositions", "components": "compositions/components",
                  "assets": "assets"},
        "media": {"autoProxy": True},
    }, indent=2) + "\n", encoding="utf-8")
    (out_dir / "package.json").write_text(json.dumps({
        "name": session_dir.name[:60].strip("-") or "capture-lane-take",
        "private": True,
        "type": "module",
        "scripts": {
            "dev": f"npx --yes hyperframes@{HYPERFRAMES_VERSION} preview",
            "check": f"npx --yes hyperframes@{HYPERFRAMES_VERSION} check",
            "render": f"npx --yes hyperframes@{HYPERFRAMES_VERSION} render",
        },
    }, indent=2) + "\n", encoding="utf-8")
    # Everything the edit came from, in one place — so the next person can see that a punch-in is
    # a click and not a taste decision somebody made and forgot.
    (out_dir / "SOURCE.json").write_text(json.dumps({
        "session": str(session_dir),
        "recorded_by": (manifest.get("streams", {}).get("input", {}) or {}).get("tool"),
        "target": (manifest.get("source") or {}).get("url"),
        "clock_source": plan.get("clock_source"),
        "punches": moves,
        "chips": chips,
        "notes": notes,
        "narration": lines,
        "voice": voice,
        "cut_s": cut_s, "ramp_s": ramp_s,
        "cuts": plan.get("cuts", []),
    }, indent=2) + "\n", encoding="utf-8")

    return {"chips": len(chips), "punches": len(moves), "duration": plan["duration_s"],
            "max_scale": max_scale, "out": out_dir, "notes": len(notes), "lines": len(lines),
            "cut_s": cut_s, "ramp_s": ramp_s, "voice": voice}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Turn a capture-lane bundle into a HyperFrames composition.")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None,
                        help="project directory (default: <session-dir>/hyperframes)")
    parser.add_argument("--max-scale", type=float, default=None,
                        help="cap the punch-in depth. Default follows the footage: 2.0 when the "
                             "take was recorded at the output size, 1.8 when it has to be upscaled "
                             "first")
    parser.add_argument("--no-title", action="store_true", help="skip the opening title card")
    parser.add_argument("--vo", type=Path, default=None,
                        help="a folder of recorded narration, one file per beat id "
                             "(default: <session-dir>/vo)")
    parser.add_argument("--keep-dead-air", action="store_true",
                        help="do not spend plan.cuts — emit the take at its recorded length")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--font-file", type=Path, help="portable licensed font for composition labels")
    parser.add_argument("--note-top", type=int, default=68, help="top offset for explanatory labels; avoid recorded toolbars")
    parser.add_argument("--check", action="store_true",
                        help="run `hyperframes check` on the emitted project")
    args = parser.parse_args()

    out_dir = args.out or (args.session_dir / "hyperframes")
    result = emit(args.session_dir, out_dir, args.max_scale, not args.no_title,
                  args.width, args.height, args.keep_dead_air, args.vo, args.font_file, args.note_top)

    print(f"composition · {result['duration']}s · {result['punches']} punch-in(s) up to "
          f"{result['max_scale']}x · {result['chips']} chapter chip(s) · "
          f"{result['notes']} note(s)")
    if result["cut_s"]:
        print(f"  cut     : {result['cut_s']}s of dead air removed from the footage")
    if result["ramp_s"]:
        print(f"  ramp    : {result['ramp_s']}s more paid for by playing each beat at the pace "
              f"of its own line")
    if result["lines"]:
        voiced = len(result["voice"])
        print(f"  narrate : {result['lines']} line(s) → {result['out']}/VO.md"
              + (f" · {voiced} already voiced" if voiced else " · no voice recorded yet"))
        for v in result["voice"]:
            if v["over_s"] > 0.15:
                print(f"  ! vo {v['id']!r} runs {v['over_s']}s past its shot — shorten the line "
                      f"or lengthen the shot in the demo script")
    print(f"  written : {result['out']}/index.html")
    if args.check:
        print("  check   : running hyperframes check…")
        proc = subprocess.run(["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "check"],
                              cwd=result["out"], capture_output=True, text=True)
        print("\n".join(f"    {line}" for line in
                        (proc.stdout or proc.stderr).strip().splitlines()[-14:]))
        return proc.returncode
    print(f"  preview : cd {result['out']} && npm run dev")
    print(f"  render  : cd {result['out']} && npm run render")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
