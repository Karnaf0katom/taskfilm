#!/usr/bin/env python3
"""reel — the same take, cut vertical.

`hfcomp.py` writes the landscape cut. This writes the 9:16 one, and it is a different *film*, not
the same film with the sides chopped off. Everything before the layout is shared with hfcomp and
imported from it: the cut, the time map, the punch-in list, the narration and the voice files.
Only the frame is new.

Three decisions carry the format:

  * **A window, not a letterbox.** A 16:9 recording pillar-boxed into 9:16 leaves 70% of the frame
    empty. Instead the recording lives in a rounded window on a designed field, and the window
    itself is animated — wide while a line is describing the app, tall and tight around one
    control the moment a line is describing that control. The beats already say which is which:
    a beat with a click under it is a beat about a control.
  * **The words carry the frame.** A reel is watched muted first. Each narration line arrives
    word by word at speech pace, big, in the half of the frame the window does not use, so the
    piece reads with no sound and is merely *better* with it.
  * **Nothing sits still.** A screen recording of a static UI dies on a vertical feed, so every
    shot ends on a slow push. The push is on the window's camera, never on the video element:
    HyperFrames forbids animating timed media's own geometry, and a non-timed wrapper is the one
    arrangement that satisfies that and still lets the frame move.

Usage:
    python reel.py <session-dir> [--out DIR] [--no-title] [--check]
"""

from __future__ import annotations

import argparse
import html
import json
import shlex
import shutil
import subprocess
from pathlib import Path

import hfcomp
from hfcomp import (GSAP_CDN, HYPERFRAMES_VERSION, TITLE_CARD_S, TITLE_OUT_S, is_edited,
                    kept_segments,
                    load_bundle, narration, place_voice, punches, remap_plan, tighten, time_map,
                    write_vo_script)
from hfcomp import copy_font_asset
from provenance import ArtifactSpec, build_receipt, write_receipt

REEL_W, REEL_H = 1080, 1920
CARD_W = 1000                      # the window's width is fixed; only its height moves
CARD_WIDE_H = round(CARD_W * 9 / 16)
CARD_TALL_MAX = 900                # measured: past this the crop is mostly whatever is beside
                                   # the click, and in an editor that is usually an empty canvas
CARD_CENTER_Y = 1090               # low enough to leave the top half of the frame to the words
REFRAME_S = 0.7                    # a window morphing wide -> tall reads as a camera, not a cut
WORD_STAGGER_S = 0.055             # words arrive at speech pace, not like a slide bullet
DRIFT_SCALE = 1.05
MAX_REEL_SCALE = 1.75
# How hard the framing is pulled back toward the thing that was clicked. Pure detail-seeking
# frames the busiest corner of the app instead of the part the demo is talking about.
CLICK_PULL = 0.55
INTEREST_W, INTEREST_H = 192, 108  # the detail map's resolution; finer buys nothing at this scale
# A smaller window always wins on *mean* detail, so a straight comparison would pick the wide
# shape every time and the window would never morph. The tall shape wins ties and near-ties: it is
# the more striking frame, and it only loses when it would be materially emptier.
TALL_KEEP = 0.85
# One label on screen at a time. A fade-out that is still running when the next fade-in starts is
# two texts in one place, which is exactly as unreadable as it sounds.
LABEL_GAP_S = 0.2

# Languages that read right to left. The frame is absolutely positioned, so the page stays LTR and
# only the type flips — flipping the document would mirror the window and the progress bar too.
RTL_LANGS = {"he", "ar", "fa", "ur", "yi"}
# Already installed on the render box (`fc-list :lang=he`), so a Hebrew reel needs no webfont and
# no network: the render stays deterministic and frame 1 is never a row of fallback boxes.
HEBREW_STACK = "Heebo, Assistant"
HEBREW_FONT_FILES = ("Heebo.ttf", "Assistant.ttf")
FONT_DIRS = (Path.home() / ".local/share/fonts", Path("/usr/share/fonts"))


def detail_map(video: Path, at: float):
    """Where the picture actually has content, one frame, cheap.

    A click tells you what the demo *pressed*; it does not tell you what is worth putting in a
    vertical window. In an editor the pixels beside a button are very often an empty canvas, and
    a window centred on the click then spends two thirds of the frame on black. Gradient energy
    is a blunt but honest stand-in for "there is something here to look at": UI chrome, text and
    thumbnails have edges, an empty preview does not.
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:                                          # pragma: no cover
        return None
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(at, 0):.3f}",
         "-i", str(video), "-frames:v", "1", "-vf",
         f"scale={INTEREST_W}:{INTEREST_H},format=gray", "-f", "rawvideo", "-"],
        capture_output=True)
    if proc.returncode != 0 or len(proc.stdout) < INTEREST_W * INTEREST_H:
        return None
    frame = np.frombuffer(proc.stdout[:INTEREST_W * INTEREST_H], dtype=np.uint8) \
              .reshape(INTEREST_H, INTEREST_W).astype(np.float32)
    energy = np.zeros_like(frame)
    energy[:, 1:] += np.abs(np.diff(frame, axis=1))
    energy[1:, :] += np.abs(np.diff(frame, axis=0))
    return energy


def best_frame(energy, cw: float, ch: float, click: tuple[float, float]) -> tuple[float, float]:
    """The window of this shape with the most to look at, pulled back toward the click."""
    import numpy as np
    h, w = energy.shape
    box_w, box_h = max(int(cw * w), 1), max(int(ch * h), 1)
    integral = np.pad(energy, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    sums = (integral[box_h:, box_w:] - integral[:-box_h, box_w:]
            - integral[box_h:, :-box_w] + integral[:-box_h, :-box_w])
    if sums.size == 0:
        return click
    ys, xs = np.mgrid[0:sums.shape[0], 0:sums.shape[1]]
    cx = (xs + box_w / 2.0) / w
    cy = (ys + box_h / 2.0) / h
    # Distance is measured in frame widths, so a 2:1 frame does not silently prefer verticals.
    dist = np.hypot(cx - click[0], cy - click[1])
    score = sums / max(sums.max(), 1e-6) - CLICK_PULL * dist
    i = int(np.argmax(score))
    return float(cx.flat[i]), float(cy.flat[i])


def _density(energy, cw: float, ch: float, fx: float, fy: float) -> float:
    """Detail per pixel inside one candidate window — the number the two shapes compete on."""
    import numpy as np
    h, w = energy.shape
    x0 = int(round(max(fx - cw / 2, 0) * w)); x1 = min(int(round((fx + cw / 2) * w)), w)
    y0 = int(round(max(fy - ch / 2, 0) * h)); y1 = min(int(round((fy + ch / 2) * h)), h)
    patch = energy[y0:max(y1, y0 + 1), x0:max(x1, x0 + 1)]
    return float(np.mean(patch)) if patch.size else 0.0


def shots(plan: dict, lines: list[dict], moves: list[dict], video: Path | None = None
          ) -> list[dict]:
    """One framing per beat, derived from the plan rather than from somebody's taste."""
    duration = float(plan["duration_s"])
    beats = plan.get("beats") or [{"id": "all", "start": 0.0, "vo": "", "explain": ""}]
    voice = {line["id"]: line for line in lines}

    out: list[dict] = []
    for i, beat in enumerate(beats):
        start = float(beat["start"])
        end = float(beats[i + 1]["start"]) if i + 1 < len(beats) else duration
        inside = [m for m in moves if start - 0.35 <= m["start"] < end]
        if inside:
            move = max(inside, key=lambda m: m["scale"])       # the deepest move is the subject
            scale = round(min(float(move["scale"]), MAX_REEL_SCALE), 3)
            click = (float(move["ox"]) / 100.0, float(move["oy"]) / 100.0)
            at = round(max(float(move["start"]) - 0.25, start), 3)
        else:
            scale, click, at = 1.0, (0.5, 0.5), round(start, 3)

        # Two window shapes are on the table for every shot, and the picture decides between them:
        # wide when the interesting pixels are spread across the app, tall when they are stacked in
        # one column. Forcing one shape is what puts an empty preview canvas in two thirds of the
        # frame.
        energy = detail_map(video, (at + end) / 2.0) if (video and inside) else None
        heights = [CARD_WIDE_H]
        tall_h = min(CARD_TALL_MAX, round(CARD_WIDE_H * scale))
        if inside and tall_h > CARD_WIDE_H:
            heights.append(tall_h)

        options = []
        for card_h in heights:
            cw = min(1.0 / scale, 1.0)
            ch = min(card_h / (CARD_WIDE_H * scale), 1.0)
            if energy is None:
                fx, fy, quality = click[0], click[1], 0.0
            else:
                fx, fy = best_frame(energy, cw, ch, click)
                quality = _density(energy, cw, ch, fx, fy)
            options.append({"q": quality, "card_h": card_h, "cw": cw, "ch": ch,
                            "fx": fx, "fy": fy})

        pick = options[0]
        if len(options) > 1 and options[1]["q"] >= TALL_KEEP * options[0]["q"]:
            pick = options[1]
        card_h, cw, ch, fx, fy = (pick["card_h"], pick["cw"], pick["ch"], pick["fx"], pick["fy"])

        # Keep the crop inside the picture. A window hanging off the edge of the source shows the
        # designed background where the app should be, which reads as a bug and not as a style.
        fx = min(max(fx, cw / 2), 1.0 - cw / 2) if cw < 1.0 else 0.5
        fy = min(max(fy, ch / 2), 1.0 - ch / 2) if ch < 1.0 else 0.5

        line = voice.get(beat.get("id"), {})
        out.append({
            "id": beat.get("id") or f"shot-{i + 1}", "at": at, "end": round(end, 3),
            "scale": scale, "card_h": card_h,
            # GSAP maps a point to (x, y) + scale * p, so the offset that brings the focus point
            # to the window centre is -scale * (focus - centre), in unscaled pixels.
            "x": round(-scale * (fx - 0.5) * CARD_W, 2),
            "y": round(-scale * (fy - 0.5) * CARD_WIDE_H, 2),
            "vo": (beat.get("vo") or "").strip(),
            "explain": (beat.get("explain") or "").strip(),
            "vo_at": round(float(line.get("at", start)), 3),
            "vo_s": round(float(line.get("est_s", 0)) or (end - start), 3),
        })

    for i, shot in enumerate(out):
        shot["end"] = round(out[i + 1]["at"] if i + 1 < len(out) else duration, 3)
        # The label belongs to the whole shot, so it arrives with whichever came first: the line
        # or the reframe.
        shot["show_from"] = round(min(shot["at"], shot["vo_at"]), 3)
    return out


def _nodes_and_tweens(shot_list: list[dict], duration: float, title: str | None):
    esc = html.escape
    words, explains, tweens = [], [], []

    for i, shot in enumerate(shot_list):
        nxt = shot_list[i + 1] if i + 1 < len(shot_list) else None
        line_room = ((nxt["vo_at"] if nxt and nxt["vo"] else duration)
                     - shot["vo_at"] - LABEL_GAP_S)
        ex_room = (nxt["show_from"] if nxt else duration) - shot["show_from"] - LABEL_GAP_S

        if shot["vo"]:
            spans = "".join('<span class="w">%s</span>' % esc(w) for w in shot["vo"].split())
            hold = max(min(shot["vo_s"] + 0.9, line_room), 1.2)
            words.append(
                '      <div class="overlay clip" id="line-%d" data-start="%.3f" '
                'data-duration="%.3f" data-track-index="2"><div class="line" id="line-%d-visual"><p>%s</p></div></div>'
                % (i, shot["vo_at"], hold, i, spans))
            tweens.append(
                '  tl.fromTo("#line-%d .w", { yPercent: 42, autoAlpha: 0 }, '
                '{ yPercent: 0, autoAlpha: 1, duration: 0.42, ease: "power3.out", '
                'stagger: %s }, %.3f);' % (i, WORD_STAGGER_S, shot["vo_at"]))
            tweens.append(
                '  tl.to("#line-%d-visual", { autoAlpha: 0, duration: 0.35, ease: "power2.in" }, %.3f);'
                % (i, shot["vo_at"] + hold - 0.35))
            # A fade that lands exactly on the next clip's boundary is not enough: a seek can
            # arrive after it and inherit stale visibility. The hard kill is what makes the
            # timeline seek-safe, which is the whole reason a deterministic render can trust it.
            tweens.append('  tl.set("#line-%d-visual", { autoAlpha: 0 }, %.3f);'
                          % (i, shot["vo_at"] + hold))

        if shot["explain"]:
            head = shot["show_from"]
            span = max(ex_room, 1.0)
            explains.append(
                '      <div class="overlay clip" id="ex-%d" data-start="%.3f" data-duration="%.3f" '
                'data-track-index="3"><div class="ex" id="ex-%d-visual"><span class="ex-dot"></span>%s</div></div>'
                % (i, head, span, i, esc(shot["explain"])))
            tweens.append(
                '  tl.fromTo("#ex-%d-visual", { y: 16, autoAlpha: 0 }, { y: 0, autoAlpha: 1, '
                'duration: 0.4, ease: "power3.out" }, %.3f);' % (i, head))
            ex_out = max(head + span - 0.3, head + 0.6)
            tweens.append(
                '  tl.to("#ex-%d-visual", { autoAlpha: 0, duration: 0.3, ease: "power2.in" }, %.3f);'
                % (i, ex_out))
            tweens.append('  tl.set("#ex-%d-visual", { autoAlpha: 0 }, %.3f);' % (i, ex_out + 0.3))

        # The reframe. Window height and camera move together — that IS the gesture; split them
        # and the window looks like it is resizing around a picture that stayed behind.
        first = i == 0
        dur, ease = (0.001, "none") if first else (REFRAME_S, "power2.inOut")
        tweens.append('  tl.to(card, { height: %d, duration: %s, ease: "%s" }, %.3f);'
                      % (shot["card_h"], dur, ease, shot["at"]))
        tweens.append('  tl.to(cam, { x: %s, y: %s, scale: %s, duration: %s, ease: "%s" }, %.3f);'
                      % (shot["x"], shot["y"], shot["scale"], dur, ease, shot["at"]))
        # Stop the drift a beat before the next reframe takes the camera: two tweens meeting on
        # the same property at the same instant is a race the renderer should never have to win.
        # Leave a gap between the reframe and the drift. Two tweens on the same property that
        # merely *touch* is a race the renderer should never have to win.
        gap = 0.06
        rest = round(shot["end"] - shot["at"] - dur - 2 * gap, 3)
        if rest > 0.8:
            tweens.append(
                '  tl.to(cam, { scale: %s, x: %s, y: %s, duration: %s, ease: "none" }, %.3f);'
                % (round(shot["scale"] * DRIFT_SCALE, 3), round(shot["x"] * DRIFT_SCALE, 2),
                   round(shot["y"] * DRIFT_SCALE, 2), rest, shot["at"] + dur + gap))

    title_node = ""
    if title:
        title_node = (
            '      <div class="overlay clip" id="tc" data-start="0" data-duration="%.3f" '
            'data-track-index="4"><div class="tc" id="tc-visual"><div class="tc-in">'
            '<span class="tc-k">screen recording</span><h1>%s</h1></div></div></div>'
            % (TITLE_CARD_S, esc(title)))
        tweens.append('  tl.fromTo("#tc .tc-in", { y: 30, autoAlpha: 0 }, '
                      '{ y: 0, autoAlpha: 1, duration: 0.7, ease: "power3.out" }, 0.15);')
        tweens.append('  tl.to("#tc-visual", { autoAlpha: 0, duration: %s, ease: "power2.inOut" }, %.3f);'
                      % (TITLE_OUT_S, TITLE_CARD_S - TITLE_OUT_S))
        tweens.append('  tl.set("#tc-visual", { autoAlpha: 0 }, %.3f);' % TITLE_CARD_S)

    tweens.append('  tl.fromTo("#bar", { scaleX: 0 }, { scaleX: 1, duration: %.3f, '
                  'ease: "none" }, 0);' % duration)
    return words, explains, tweens, title_node


def build_html(plan: dict, video_name: str, shot_list: list[dict], title: str | None,
               voice: list[dict] | None = None, lang: str = "en", font_file: str | None = None) -> str:
    duration = round(float(plan["duration_s"]), 3)
    rtl = lang.split("-")[0].lower() in RTL_LANGS
    words, explains, tweens, title_node = _nodes_and_tweens(shot_list, duration, title)
    voice_nodes = "\n".join(
        '      <audio id="vo-%s" src="%s" data-start="%.3f" data-duration="%.3f" '
        'data-track-index="%d"></audio>'
        % (html.escape(v["id"]), v["file"], v["at"], v["s"], 5 + i)
        for i, v in enumerate(voice or []))

    faces = ""
    if rtl:
        faces = "\n".join(
            '      @font-face {{ font-family: "%s"; src: url("assets/fonts/%s") format("truetype"); '
            'font-weight: 100 900; font-display: block; }}'.replace("{{", "{").replace("}}", "}")
            % (f.rsplit(".", 1)[0], f) for f in HEBREW_FONT_FILES)
    if font_file:
        faces = (f'      @font-face {{ font-family: CaptureFont; src: url("assets/{font_file}"); '
                 'font-weight: 100 900; font-display: block; }')

    css = CSS_TEMPLATE.format(
        w=REEL_W, h=REEL_H, card_w=CARD_W, card_h=CARD_WIDE_H, card_left=(REEL_W - CARD_W) // 2,
        card_top=CARD_CENTER_Y, neg_w=-CARD_W // 2, neg_h=-CARD_WIDE_H // 2,
        ex_top=CARD_CENTER_Y + CARD_TALL_MAX // 2 + 44,
        font="CaptureFont" if font_file else ((HEBREW_STACK + ", Inter") if rtl else "Inter"),
        text_dir="rtl" if rtl else "ltr", text_align="right" if rtl else "left",
        # The pill grows from whichever edge the language starts at, or it points the wrong way.
        ex_side="right: 72px; left: auto; flex-direction: row-reverse;" if rtl else "left: 72px;",
        leading="1.34" if rtl else "1.12", faces=faces)

    return HTML_TEMPLATE.format(
        lang_title=html.escape(plan.get("name") or "reel"), gsap=GSAP_CDN, css=css,
        w=REEL_W, h=REEL_H, duration=duration, video=video_name, lang=lang,
        words="\n".join(words), explains="\n".join(explains), voice=voice_nodes,
        title_node=title_node, tweens="\n".join(tweens))


CSS_TEMPLATE = """
{faces}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {w}px; height: {h}px; overflow: hidden; background: #04060b; }}
      body {{ font-family: {font}, ui-sans-serif, system-ui, -apple-system, "Segoe UI",
        sans-serif; }}
      .overlay {{ position: absolute; inset: 0; pointer-events: none; }}
      #root {{ position: relative; width: {w}px; height: {h}px; overflow: hidden;
        background:
          radial-gradient(80% 46% at 50% 12%, rgba(56,189,248,.16), transparent 70%),
          radial-gradient(70% 40% at 50% 92%, rgba(99,102,241,.15), transparent 72%),
          linear-gradient(180deg, #060a13 0%, #04060b 55%, #070b14 100%); }}

      /* A faint grid stops the half of the frame the window does not use from reading as a
         rendering failure rather than as a designed field. */
      .grid {{ position: absolute; inset: 0; opacity: .30; pointer-events: none;
        background-image: linear-gradient(rgba(148,163,184,.07) 1px, transparent 1px),
                          linear-gradient(90deg, rgba(148,163,184,.07) 1px, transparent 1px);
        background-size: 60px 60px; }}

      .card {{ position: absolute; left: {card_left}px; width: {card_w}px; height: {card_h}px;
        top: {card_top}px; transform: translateY(-50%); overflow: hidden; border-radius: 22px;
        background: #05070c; border: 1px solid rgba(148,163,184,.22);
        box-shadow: 0 40px 120px rgba(0,0,0,.62), 0 0 0 1px rgba(255,255,255,.03) inset; }}
      .cam {{ position: absolute; left: 50%; top: 50%; width: {card_w}px; height: {card_h}px;
        margin-left: {neg_w}px; margin-top: {neg_h}px; will-change: transform; }}
      .cam video {{ width: 100%; height: 100%; object-fit: cover; display: block; }}

      .line {{ position: absolute; left: 72px; right: 72px; top: 420px; }}
      .line p {{ font-size: 66px; line-height: {leading}; font-weight: 700; letter-spacing: -.028em;
        color: #f8fafc; direction: {text_dir}; text-align: {text_align}; unicode-bidi: isolate; }}
      .line .w {{ display: inline-block; will-change: transform, opacity;
        unicode-bidi: isolate; margin-inline-end: .26em; }}

      .ex {{ position: absolute; {ex_side} top: {ex_top}px; display: flex; align-items: center;
        gap: 14px; padding: 16px 30px; border-radius: 999px; background: rgba(8,13,22,.82);
        border: 1px solid rgba(125,211,252,.30); font-size: 30px; font-weight: 500;
        color: #dbeafe; direction: {text_dir}; }}
      .ex-dot {{ width: 10px; height: 10px; border-radius: 50%; background: #38bdf8;
        box-shadow: 0 0 0 6px rgba(56,189,248,.16); flex: none; }}

      .barwrap {{ position: absolute; left: 72px; right: 72px; bottom: 86px; height: 5px;
        border-radius: 3px; background: rgba(148,163,184,.16); overflow: hidden; }}
      #bar {{ width: 100%; height: 100%; transform-origin: 0 50%;
        background: linear-gradient(90deg, #38bdf8, #6366f1); }}

      .tc {{ position: absolute; inset: 0; display: grid; place-items: center;
        background: linear-gradient(165deg, rgba(4,6,11,.97), rgba(9,14,26,.95)); }}
      .tc-in {{ text-align: center; padding: 0 90px; direction: {text_dir}; }}
      .tc-k {{ display: block; font-size: 24px; letter-spacing: .36em; text-transform: uppercase;
        color: #7dd3fc; margin-bottom: 30px; }}
      .tc h1 {{ font-size: 88px; line-height: 1.05; font-weight: 700; letter-spacing: -.03em;
        color: #f8fafc; }}
"""

HTML_TEMPLATE = """<!doctype html>
<html lang="{lang}" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={w}, height={h}" />
    <title>{lang_title}</title>
    <script src="{gsap}"></script>
    <style>{css}</style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="{duration}"
      data-width="{w}"
      data-height="{h}"
    >
      <div class="grid"></div>
      <div class="card" id="card" data-layout-allow-overflow>
        <div class="cam" id="cam">
          <video
            id="screen"
            src="assets/{video}"
            data-start="0"
            data-duration="{duration}"
            data-track-index="0"
            muted
            playsinline
          ></video>
        </div>
      </div>

{words}
{explains}
{voice}
      <div class="barwrap"><div id="bar"></div></div>
{title_node}
    </div>

    <script>
      const tl = gsap.timeline({{ paused: true }});
      const cam = document.getElementById("cam");
      const card = document.getElementById("card");
{tweens}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


def emit(session_dir: Path, out_dir: Path, want_title: bool,
         keep_dead_air: bool = False, vo_dir: Path | None = None,
         command: str | None = None, silent: bool = False, font_file: Path | None = None) -> dict:
    plan, manifest = load_bundle(session_dir)
    video = session_dir / "screen.mp4"
    if not video.exists():
        raise SystemExit(f"no screen.mp4 in {session_dir} — the take never encoded")

    source_video = video
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assets").mkdir(exist_ok=True)
    font_asset = copy_font_asset(out_dir, font_file)

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
    video = out_dir / "assets" / "screen.mp4"

    here = time_map([(0.0, float(plan["duration_s"]))])
    lines = narration(plan, here)
    moves = punches(plan, MAX_REEL_SCALE)
    shot_list = shots(plan, lines, moves, video)
    voice = [] if silent else (place_voice(lines, vo_dir or (session_dir / "vo"), out_dir)
                               if lines else [])
    title = (plan.get("name") or "").strip() if want_title else None

    lang = (plan.get("lang") or manifest.get("lang") or "en")
    if lang.split("-")[0].lower() in RTL_LANGS:
        (out_dir / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
        for name in HEBREW_FONT_FILES:
            found = next((d / name for d in FONT_DIRS if (d / name).exists()), None)
            if found:
                shutil.copy2(found, out_dir / "assets" / "fonts" / name)
    (out_dir / "index.html").write_text(
        build_html(plan, video.name, shot_list, title, voice, lang, font_asset), encoding="utf-8")
    (out_dir / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
        "paths": {"blocks": "compositions", "components": "compositions/components",
                  "assets": "assets"},
        "media": {"autoProxy": True},
    }, indent=2) + "\n", encoding="utf-8")
    (out_dir / "package.json").write_text(json.dumps({
        "name": (session_dir.name[:52].strip("-") or "capture-lane") + "-reel",
        "private": True, "type": "module",
        "scripts": {
            "dev": f"npx --yes hyperframes@{HYPERFRAMES_VERSION} preview",
            "check": f"npx --yes hyperframes@{HYPERFRAMES_VERSION} check",
            "render": f"npx --yes hyperframes@{HYPERFRAMES_VERSION} render",
        },
    }, indent=2) + "\n", encoding="utf-8")
    write_vo_script(out_dir, plan, lines)
    source_manifest = out_dir / "SOURCE.json"
    source_manifest.write_text(json.dumps({
        "session": str(session_dir), "format": f"{REEL_W}x{REEL_H}", "lang": lang,
        "target": (manifest.get("source") or {}).get("url"),
        "cut_s": cut_s, "ramp_s": ramp_s, "shots": shot_list, "narration": lines, "voice": voice,
    }, indent=2) + "\n", encoding="utf-8")

    screen = plan.get("screen") or {}
    receipt_command = command or shlex.join([
        "python", "reel.py", session_dir.name, "--out", out_dir.name,
        *(["--no-title"] if not want_title else []),
        *(["--keep-dead-air"] if keep_dead_air else []),
        *(["--silent"] if silent else []),
        *(["--vo", vo_dir.name] if vo_dir else []),
    ])
    # Retain the effective clock hashed below, including any successful retiming.
    (out_dir / "PLAN.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_receipt(build_receipt(
        plan,
        [source_video],
        out_dir / "VO.md",
        [
            ArtifactSpec(aspect="16:9", width=int(screen.get("width") or 1920),
                         height=int(screen.get("height") or 1080),
                         duration_s=float(plan["duration_s"]), path=str(video),
                         artifact_id="landscape", kind=("edited_source_media" if cut_s or ramp_s
                                                        else "source_copy"),
                         role="landscape_composition_input"),
            ArtifactSpec(aspect="9:16", width=REEL_W, height=REEL_H,
                         duration_s=float(plan["duration_s"]), path=str(out_dir / "index.html"),
                         artifact_id="reel", kind="composition",
                         role="vertical_render_input"),
        ],
        vo_dir=None if silent else (vo_dir or (session_dir / "vo")),
        silent=silent,
        command=receipt_command,
    ), out_dir / "PROVENANCE.json")

    tall = sum(1 for s in shot_list if s["card_h"] > CARD_WIDE_H)
    return {"out": out_dir, "duration": plan["duration_s"], "shots": len(shot_list),
            "tall": tall, "lines": len(lines), "voice": len(voice), "cut_s": cut_s,
            "ramp_s": ramp_s, "lang": lang, "silent": silent}


def main() -> int:
    parser = argparse.ArgumentParser(description="Cut a capture-lane bundle vertical (9:16).")
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None,
                        help="project directory (default: <session-dir>/reel)")
    parser.add_argument("--vo", type=Path, default=None, help="folder of narration, one per beat")
    parser.add_argument("--silent", action="store_true",
                        help="ship a declared caption-led cut with no read (records "
                             "narration_policy=silent instead of demanding one voice file per beat)")
    parser.add_argument("--no-title", action="store_true", help="skip the opening title card")
    parser.add_argument("--keep-dead-air", action="store_true", help="do not spend plan.cuts")
    parser.add_argument("--font-file", type=Path, help="portable licensed font for composition labels")
    parser.add_argument("--check", action="store_true", help="run `hyperframes check` on it")
    args = parser.parse_args()

    if args.silent and args.vo:
        parser.error("--silent and --vo are opposites: pick a read or declare there is none")

    out_dir = args.out or (args.session_dir / "reel")
    command = shlex.join([
        "python", "reel.py", args.session_dir.name, "--out", out_dir.name,
        *(["--vo", args.vo.name] if args.vo else []),
        *(["--silent"] if args.silent else []),
        *(["--no-title"] if args.no_title else []),
        *(["--keep-dead-air"] if args.keep_dead_air else []),
        *(["--check"] if args.check else []),
    ])
    r = emit(args.session_dir, out_dir, not args.no_title, args.keep_dead_air, args.vo,
             command=command, silent=args.silent, font_file=args.font_file)

    read = ("silent (caption-led)" if r["silent"]
            else f"{r['voice']}/{r['lines']} line(s) voiced")
    rtl = r["lang"].split("-")[0].lower() in RTL_LANGS
    print(f"reel {REEL_W}x{REEL_H} · {r['duration']}s · {r['shots']} shot(s), "
          f"{r['tall']} framed tall · {read} · "
          f"{r['lang']}{' (rtl)' if rtl else ''}")
    if r["cut_s"]:
        print(f"  cut     : {r['cut_s']}s of dead air removed")
    print(f"  written : {r['out']}/index.html")
    if args.check:
        proc = subprocess.run(["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "check"],
                              cwd=r["out"], capture_output=True, text=True)
        print("\n".join(f"    {line}" for line in
                        (proc.stdout or proc.stderr).strip().splitlines()[-16:]))
        return proc.returncode
    print(f"  render  : cd {r['out']} && npm run render")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
