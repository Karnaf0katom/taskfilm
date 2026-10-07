"""Author a product-motion film: one real 4K app take, edited to the music's beat grid.

Generalised from the Memos motion cut (productions/memos-product-story/motion/build_motion.py).
The format is fixed and the app fills it: a hook, a 3D window reveal, three acts (input, the key
click on the music's drop, the payoff), a recap and an end card. A film's spec.json supplies
only what differs: copy, palette, take anchors, source regions and lens framings.

HyperFrames owns playback and rendering. This module writes, per format, a HyperFrames project
in <film>/cuts/<format>/: index.html, index.motion.json, hyperframes.json, package.json,
EDIT-DECISIONS.json and assets/ (take, fonts, GSAP, mix.wav).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import ImageFont

import sfx

KIT = Path(__file__).resolve().parent
VIDEO = KIT.parents[1]
REPO = VIDEO.parents[1]
FPS = 30
SRC_W, SRC_H = 3840, 2160
HF = "hyperframes@" + os.environ.get("CAPTURE_HYPERFRAMES_VERSION", "0.8.60")

# ------------------------------------------------------------------ formats
# Canvas geometry per delivery format. Numbers are CSS px of the composition. "focus" is where a
# lens framing's centre lands inside the screen (portrait keeps the bottom free for titles).
FORMATS = {
    "landscape": {
        "W": 1920, "H": 1080, "suffix": "landscape",
        "window": [-48, -57, 2016, 1190], "chrome": 56, "radius": 30, "focus": [0.5, 0.5],
        "storm": {"spread": [1350, 760], "avoid": [380, 260], "push": [520, 0]},
        "kline": {"size": 156, "max_w": 1700}, "hero": {"size": 56, "max_w": 1700},
        "intro": {"left": 104, "top": 250, "width": 760, "wm": 176, "tag": 54},
        "hud": {"top": 44, "side": 100, "tc_res": True},
        "steps": {"left": 650, "top": 996},
        "slab": {"left": 96, "top": 760, "h2": 96, "p": 29, "max_w": 1500},
        "recap": {"cards": [[40, 380], [680, 380], [1320, 380]], "size": [560, 315], "word": 118,
                  "words": [[40, 190], [680, 190], [1320, 190]], "word_w": 560, "word_shift": -190,
                  "enter": [{"x": -1500, "rotationY": 58}, {"y": 900, "rotationX": -46}, {"x": 1500, "rotationY": -58}],
                  "rest": [{"x": 0, "rotationY": 20}, {"y": 0, "rotationX": 0}, {"x": 0, "rotationY": -20}],
                  "push": {"z": -520, "rotationX": 12}},
        "end": {"top": 190, "wm": 270, "wm_max_w": 1500, "stack_tag": False, "tag": 60, "url": 38,
                "foot_top": 994, "rays": [-340, -1000, 2600]},
        "world": "landscape",
    },
    "portrait": {
        "W": 1080, "H": 1920, "suffix": "portrait",
        "window": [40, 330, 1000, 1260], "chrome": 56, "radius": 34, "focus": [0.5, 0.42],
        "storm": {"spread": [560, 980], "avoid": [300, 330], "push": [0, 420]},
        "kline": {"size": 132, "max_w": 950}, "hero": {"size": 50, "max_w": 880},
        "intro": {"left": 70, "top": 310, "width": 940, "wm": 150, "tag": 50},   # below the HUD pills
        "hud": {"top": 150, "side": 56, "tc_res": False},
        "steps": {"left": 230, "top": 236},
        "slab": {"left": 56, "top": 1290, "h2": 84, "p": 27, "max_w": 900},   # clear of Reels' caption + buttons
        "recap": {"cards": [[200, 130], [160, 600], [200, 1070]], "size": [720, 405], "word": 96, "word_chip": True,
                  "words": [[170, 440], [130, 910], [170, 1380]], "word_w": 720, "word_shift": 0,
                  "enter": [{"x": -1300, "rotationY": 50}, {"x": 1300, "rotationY": -50}, {"y": 1400, "rotationX": -40}],
                  "rest": [{"x": 0, "rotationY": 12}, {"x": 0, "rotationY": -12}, {"y": 0, "rotationX": 0}],
                  "push": {"z": -420, "rotationX": 8}},
        "end": {"top": 480, "wm": 230, "wm_max_w": 960, "stack_tag": True, "tag": 62, "url": 34,
                "foot_top": 1470, "rays": [-760, -500, 2600]},
        "world": "portrait",
    },
}


def fmt_geometry(fmt: str) -> dict:
    lay = json.loads(json.dumps(FORMATS[fmt]))
    x, y, w, h = lay["window"]
    lay["screen"] = [w, h - lay["chrome"]]
    return lay


# ------------------------------------------------------------------ small helpers
def prand(n: float) -> float:
    x = math.sin(n * 127.1 + 311.7) * 43758.5453
    return x - math.floor(x)


def hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgba(h: str, a: float) -> str:
    r, g, b = hex_rgb(h)
    return f"rgba({r},{g},{b},{a})"


def mix_hex(a: str, b: str, t: float) -> str:
    ra, rb = hex_rgb(a), hex_rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ra, rb))


class Grid:
    """The music's beat grid. B(n) is beat n in film seconds; the bed enters at `offset`."""

    def __init__(self, music: dict):
        self.period, self.phase, self.offset = music["period"], music["phase"], music["offset"]
        self.beat0 = round((self.phase - self.offset) % self.period, 4)

    def __call__(self, n: float) -> float:
        return round(self.beat0 + self.period * n, 3)


_FONTS: dict = {}


def text_width(text: str, size: float, weight: int, tracking_em: float, font="Manrope") -> float:
    key = (font, weight)
    if key not in _FONTS:
        f = ImageFont.truetype(str(KIT / f"assets/{font}.ttf"), 200)
        if font == "Manrope":
            f.set_variation_by_axes([weight])
        _FONTS[key] = f
    return _FONTS[key].getlength(text) * size / 200 + tracking_em * size * len(text)


def fit_size(lines, size, max_w, weight, tracking_em) -> int:
    widest = max(text_width(strip_marks(t), size, weight, tracking_em) for t in lines)
    return int(min(size, size * max_w / widest)) if widest else size


def strip_marks(text: str) -> str:
    return text.replace("[", "").replace("]", "")


def accent_marks(text: str) -> str:
    """'show up [anywhere.]' -> 'show up <span class="acc">anywhere.</span>'."""
    return text.replace("[", '<span class="acc">').replace("]", "</span>")


# ------------------------------------------------------------------ take analysis
def load_take(film: Path, spec: dict) -> dict:
    take = film / spec["take"]
    session = json.loads((take / "session.json").read_text())
    assert session["session_id"] == take.name, "Review and retime a replacement take explicitly"
    assert session["screen"] == {"width": SRC_W, "height": SRC_H}
    assert session["streams"]["screen"]["dropped"] == 0
    assert session["steps"]["ok"] == session["steps"]["total"], session["steps"]
    t0 = session["t0_wallclock"]
    events = [json.loads(line) for line in (take / "input.jsonl").read_text().splitlines() if line.strip()]
    for e in events:
        e["t"] = e["ts"] - t0
    clicks = [e for e in events if e["type"] == "click" and e.get("pressed")]
    keys = [e["t"] for e in events if e["device"] == "keyboard" and e["type"] == "press"]
    moves = [(e["t"], e["x"], e["y"]) for e in events if e["type"] in ("move", "click")]
    expect = spec.get("expect", {})
    assert len(clicks) == expect.get("clicks", len(clicks)), f"{len(clicks)} clicks"
    assert len(keys) == expect.get("keys", len(keys)), f"{len(keys)} keys"
    return {"path": take, "duration": session["duration_s"], "clicks": [(c["t"], c["x"], c["y"]) for c in clicks],
            "keys": keys, "moves": sorted(moves)}


def visible_changes(take: dict, t_from: float, t_to: float, box, thresh: float = 0.35) -> list[float]:
    """Times (source seconds) at which the region `box` (x0, y0, x1, y1) visibly changes."""
    x0, y0, x1, y1 = box
    w, h = (x1 - x0) // 4 * 4, (y1 - y0) // 4 * 4
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t_from:.3f}", "-t", f"{t_to - t_from:.3f}", "-i", str(take["path"] / "screen.mp4"),
           "-vf", f"crop={w}:{h}:{x0}:{y0},scale={w // 4}:{h // 4},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h // 4, w // 4).astype(np.int16)
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    return [round(t_from + (i + 1) / FPS, 3) for i, d in enumerate(diffs) if d > thresh]


# ------------------------------------------------------------------ the edit (format-free)
def plan(spec: dict, take: dict, B: Grid) -> dict:
    e = spec["edit"]
    a1, a2, a3 = e["act1"], e["act2"], e["act3"]
    clicks = [c[0] for c in take["clicks"]]
    keys = take["keys"]
    run1 = keys[a1["keys"][0]:a1["keys"][1]]
    type_end_window = (clicks[a1["submit_click"]] - 0.12
                       if "submit_click" in a1 else run1[-1] + 3.0)
    win1 = a1.get("type_window") or [run1[0] - 0.5, type_end_window]
    typed_changes = visible_changes(take, win1[0], win1[1], a1["type_region"])
    type_end_src = max(typed_changes) + 0.1          # last visible character + a frame of rest
    c_act1, c_save, c_find = clicks[a1["click"]], clicks[a2["click"]], clicks[a3["click"]]
    save_lead = 0.4 if a2.get("instant_result") else 0.0
    save_after = c_save - 0.15 if a2.get("instant_result") else c_save + 0.1
    win2 = a2.get("result_window") or [c_save - save_lead, c_save + 3.0]
    saved_visible = next(t for t in visible_changes(take, win2[0], win2[1], a2["result_region"])
                         if t > a2.get("result_after", save_after))
    t3 = a3.get("type")
    search_changes = []
    if t3:
        run3 = keys[t3["keys"][0]:t3["keys"][1]]
        win = t3.get("window") or [run3[0] - 0.5, run3[-1] + 2.0]
        search_changes = visible_changes(take, win[0], win[1], t3["region"])
    find_lead = 0.4 if a3.get("instant_result") else 0.0
    find_after = c_find - 0.15 if a3.get("instant_result") else c_find
    win3 = a3.get("result_window") or [c_find - find_lead, c_find + 4.0]
    filtered = min(t for t in visible_changes(take, win3[0], win3[1], a3["result_region"])
                   if t > a3.get("result_after", find_after if a3.get("instant_result") else win3[0]))

    T = {"hookEnd": B(7), "reveal": B(7), "dive": B(11), "whip1": B(22), "save": B(26),
         "find": B(32), "recap": B(44), "end": B(48), "shine": B(58)}
    T["edClick"] = round(T["dive"] + 1.0, 3)
    seg = []

    def add(ident, f0, f1, s0, s1=None, rate=1.0, cursor=True):
        if s1 is not None:
            rate = (s1 - s0) / (f1 - f0)
        assert 0.25 <= rate <= 4.5, (ident, rate)
        assert 0 <= s0 and s0 + (f1 - f0) * rate <= take["duration"] + 0.05, ident
        seg.append({"id": ident, "f0": round(f0, 3), "f1": round(f1, 3), "s0": round(s0, 3),
                    "rate": round(rate, 5), "cursor": cursor})

    add("reveal", T["reveal"], T["dive"], e.get("reveal_src", 0.30), cursor=False)
    add("write-click", T["dive"], T["edClick"] + 0.22, c_act1 - (T["edClick"] - T["dive"]))
    type_f0 = T["edClick"] + 0.22
    type_f1 = round(T["whip1"] - 1.25, 3)
    add("write-type", type_f0, type_f1, run1[0] - 0.12, type_end_src)
    add("write-hold", type_f1, T["whip1"], type_end_src)
    # The click lands on the drop; one frame later, under the flash, the edit skips the app's
    # in-between state ("Saving...") to the result.
    cut = round(T["save"] + 1 / FPS, 3)
    add("save-build", T["whip1"], cut, c_save - (T["save"] - T["whip1"]))
    add("saved", cut, T["find"], saved_visible - 0.04)
    find_click_f = round(T["find"] + 0.78, 3)
    if t3:
        add("find-click", T["find"], find_click_f + 0.25, c_find - (find_click_f - T["find"]))
        f_type0 = find_click_f + 0.25
        s_type0 = clicks[t3["click"]] - 0.2
        s_type1 = filtered + 0.12
        f_type1 = round(f_type0 + (s_type1 - s_type0) / t3.get("rate", 3.0), 3)
        add("find-type", f_type0, f_type1, s_type0, s_type1)
        add("find-hold", f_type1, T["recap"], s_type1)
    else:
        add("find-click", T["find"], find_click_f + 0.25, c_find - (find_click_f - T["find"]))
        # skip_load: cut straight from the click to the rendered result, like a fast page load.
        hold_src = filtered - 0.04 if a3.get("skip_load") else c_find + 0.25
        add("find-hold", find_click_f + 0.25, T["recap"], hold_src, rate=a3.get("hold_rate", 1.0))

    def to_film(src: float):
        for g in seg:
            s1 = g["s0"] + (g["f1"] - g["f0"]) * g["rate"]
            if g["s0"] <= src < s1:
                return round(g["f0"] + (src - g["s0"]) / g["rate"], 3)
        return None

    T["type1"] = [round(type_f0, 3), type_f1]
    T["url"] = round(T["end"] + 1.75, 3)
    T["tagDone"] = to_film(type_end_src - 0.05)
    T["filtered"] = to_film(filtered)
    assert T["filtered"] is not None, "act-3 result falls outside the edit"
    T["track"] = round(T["filtered"] + 0.55, 3)
    T["lift"] = B(27.5)
    film_clicks = []
    for (t, x, y) in take["clicks"]:
        f = to_film(t)
        if f is not None:
            film_clicks.append({"t": f, "x": round(x, 1), "y": round(y, 1)})
    # Key sounds follow the visible characters, not the logged key events.
    key_times = [to_film(t) for t in typed_changes if t <= type_end_src]
    key_times += [to_film(t) for t in search_changes if t < filtered]
    key_times = sorted({k for k in key_times if k is not None})
    money = a2.get("target") or take["clicks"][a2["click"]][1:]   # measured centre, else the logged click
    return {"T": T, "seg": seg, "clicks": film_clicks, "keys": key_times, "money": [money[0], money[1]],
            "src": {"type_end": type_end_src, "saved_visible": saved_visible, "filtered": filtered,
                    "clicks": take["clicks"]}}


def cursor_track(take: dict, edit: dict, dur: float) -> list:
    """Pointer position for every film frame, from the logged moves (Catmull-Rom smoothed)."""
    mv = take["moves"]
    ts = np.array([m[0] for m in mv])
    press = [c[0] for c in take["clicks"]]

    def at(src):
        i = int(np.searchsorted(ts, src))
        if i <= 0:
            return mv[0][1], mv[0][2]
        if i >= len(mv):
            return mv[-1][1], mv[-1][2]
        p0, p1 = mv[max(i - 2, 0)], mv[i - 1]
        p2, p3 = mv[i], mv[min(i + 1, len(mv) - 1)]
        u = min(max((src - p1[0]) / max(p2[0] - p1[0], 1e-6), 0.0), 1.0)

        def cr(a, b, c, d):
            return 0.5 * ((2 * b) + (-a + c) * u + (2 * a - 5 * b + 4 * c - d) * u * u + (-a + 3 * b - 3 * c + d) * u ** 3)
        return cr(p0[1], p1[1], p2[1], p3[1]), cr(p0[2], p1[2], p2[2], p3[2])

    # Idle pointer hides (as screen recorders do): fade out after 0.9 s without input, fade back
    # in 0.3 s before the next logged move or click. Position always comes from the log.
    stamps = sorted([m[0] for m in mv] + press)

    def presence(src):
        i = int(np.searchsorted(stamps, src, side="right"))
        idle = src - stamps[i - 1] if i > 0 else 99.0
        ahead = stamps[i] - src if i < len(stamps) else 99.0
        out_ = 1.0 if idle < 0.9 else max(0.0, 1 - (idle - 0.9) / 0.3)
        in_ = max(0.0, 1 - max(0.0, ahead - 0.05) / 0.3)
        return max(out_, in_)

    out = []
    for fi in range(int(dur * FPS) + 1):
        t = fi / FPS
        g = next((g for g in edit["seg"] if g["f0"] <= t < g["f1"]), None)
        if g is None or not g["cursor"] or t >= edit["T"]["recap"]:
            out.append([0, 0, 0, 1])
            continue
        src = g["s0"] + (t - g["f0"]) * g["rate"]
        x, y = at(src)
        vis = 1 if src >= mv[0][0] else 0
        fade = min(1.0, (t - g["f0"]) / 0.2) if g["id"] == "write-click" else 1.0
        pr = 1.0
        for p in press:
            d = src - p
            if -0.02 <= d < 0.16:
                pr = 0.8 + 0.2 * min(1.0, abs(d - 0.05) / 0.11)
        out.append([round(x, 1), round(y, 1), round(vis * fade * presence(src), 3), round(pr, 3)])
    # A jump cut may change presence between two frames; ease it over about five frames instead.
    for i in range(1, len(out)):
        prev = out[i - 1][2]
        out[i][2] = round(min(max(out[i][2], prev - 0.2), prev + 0.25), 3)
    return out


# ------------------------------------------------------------------ camera (per format)
def auto_framings(spec: dict, lay: dict, take: dict) -> dict:
    """Default lens framings from the spec's measured regions; spec framings override any of them.

    Every view is clamped inside the captured frame (no empty page beyond the source edge) and
    never exceeds native pixels (s <= 1)."""
    sw, sh = lay["screen"]
    fx, fy = lay["focus"]
    e = spec["edit"]
    a1, a2, a3 = e["act1"], e["act2"], e["act3"]
    clicks = take["clicks"]
    smin = max(sw / SRC_W, sh / SRC_H)

    def frame(cx, cy, s):
        s = min(max(s, smin), 1.0)
        vw, vh = sw / s, sh / s
        x0 = min(max(cx - vw * fx, 0), SRC_W - vw) if vw < SRC_W else (SRC_W - vw) / 2
        y0 = min(max(cy - vh * fy, 0), SRC_H - vh) if vh < SRC_H else (SRC_H - vh) / 2
        return {"cx": round(x0 + vw * fx), "cy": round(y0 + vh * fy), "s": round(s, 3)}

    def box(xywh):
        x, y, w, h = xywh
        return [x, y, x + w, y + h]

    def fit(b, margin, smax):
        s = min(sw / ((b[2] - b[0]) * margin), sh / ((b[3] - b[1]) * margin), smax)
        return frame((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, s)

    ty = a1["type_region"]
    c1 = clicks[a1["click"]][1:]
    tgt = a2.get("target") or clicks[a2["click"]][1:]
    lift = box(a2["lift_region"])
    r3 = a3["result_region"]
    c3 = clicks[a3["click"]][1:]
    trk = box(a3["track_region"])
    union = [min(ty[0], lift[0], r3[0]), min(ty[1], lift[1], r3[1]), max(ty[2], lift[2], r3[2]), max(ty[3], lift[3], r3[3])]
    ucx, ucy = (union[0] + union[2]) / 2, (union[1] + union[3]) / 2
    full = frame(ucx, ucy, smin)
    vw1 = sw  # view width at s = 1
    ty_mid = (ty[1] + ty[3]) / 2
    type_in = frame(ty[0] - 0.12 * vw1 + vw1 * fx, ty_mid, 1.0)
    type_out = frame(max(ty[0] - 0.12 * vw1 + vw1 * fx + 60, ty[2] + 0.12 * vw1 - vw1 * (1 - fx)), ty_mid + 40, 1.0)
    ed = [min(c1[0] - 200, ty[0]), min(c1[1] - 150, ty[1]), max(c1[0] + 200, min(ty[2], ty[0] + 700)), max(c1[1] + 150, ty[3])]
    wide = fit(lift, 1.25, 0.7)
    return {
        "full": full,
        "revealPush": frame(full["cx"] + 30, full["cy"] - 30, full["s"] * 1.07),
        "editorWide": fit(ed, 1.2, 0.75),
        "typeIn": type_in, "typeOut": type_out,
        "save": frame(tgt[0] - 0.12 * vw1, tgt[1] - 0.1 * sh, 1.0),
        "savedWide": wide,
        "savedDrift": frame(wide["cx"] + 50, wide["cy"] + 20, wide["s"] * 1.06),
        "search": frame(c3[0], c3[1] + 0.1 * sh, 1.0),
        "foundWide": fit(r3, 1.1, 0.62),
        "foundClose": fit(trk, 2.6, 0.85),
    }


def world_plan(kind: str, B: Grid, T: dict) -> dict:
    """The 3D window's pose over time: fly-in, reveal hold, dive to screen, find nudge."""
    b7, b11, f = B(7), B(11), T["find"]
    if kind == "landscape":
        start, land, hold = [860, 40, -2600, 36, -44, 5], [640, 0, -1000, 11, -23, 1.6], [600, 0, -930, 9, -18, 1]
        nudge = [-26, -140, 7]
    else:
        start, land, hold = [0, 1150, -2600, 50, -26, 6], [0, 440, -900, 27, -11, 2], [0, 410, -850, 23, -8, 1.5]
        nudge = [-18, -140, 7]
    ch = {}
    for i, k in enumerate(("x", "y", "z", "rx", "ry", "rz")):
        keys = [[0, start[i]], [b7, start[i]], [b7 + 1.1, land[i], "power4.out"], [b11, hold[i], "sine.inOut"],
                [b11 + 0.95, 0, "power3.inOut"]]
        if k in ("x", "z", "ry"):
            n = nudge[("x", "z", "ry").index(k)]
            keys += [[f, 0], [f + 0.28, n, "power2.in"], [f + 0.7, 0, "power3.out"]]
        ch[k] = keys
    return ch


def storm_cards(copy: dict, lay: dict):
    sx_, sy_ = lay["storm"]["spread"]
    ax, ay = lay["storm"]["avoid"]
    px, py = lay["storm"]["push"]
    labels = copy.get("storm_labels", ["NOW", "2 MIN AGO", "YESTERDAY", "LAST WEEK"])
    html, data = [], []
    for i, (text, tag) in enumerate(copy["storm"]):
        x = (prand(i * 1.3 + 0.2) * 2 - 1) * sx_
        y = (prand(i * 2.7 + 0.9) * 2 - 1) * sy_
        if abs(x) < ax and abs(y) < ay:
            x += (px if x >= 0 else -px)
            y += (py if y >= 0 else -py)
        z = -3200 + prand(i * 4.1 + 2.3) * 3400
        ry = (prand(i * 5.9 + 1.1) * 2 - 1) * 24
        rx = (prand(i * 6.7 + 3.3) * 2 - 1) * 14
        rz = (prand(i * 8.3 + 0.7) * 2 - 1) * 7
        # Decorative depth texture: the cards overlap by design, so layout audits skip them.
        em = f"<em data-layout-ignore>{tag}</em>" if tag else ""
        html.append(f'<div class="scard" id="sc{i}" data-layout-ignore style="transform:translate(-50%,-50%) translate3d({x:.0f}px,{y:.0f}px,{z:.0f}px) '
                    f'rotateY({ry:.1f}deg) rotateX({rx:.1f}deg) rotateZ({rz:.1f}deg)"><small data-layout-ignore>{labels[i % len(labels)]}</small>{text}{em}</div>')
        data.append({"z": round(z), "delay": round(prand(i * 9.1) * 0.35 - 0.35, 3), "alpha": round(0.75 + 0.25 * prand(i * 3.3), 3)})
    return "\n".join(html), data


def split_chars(text: str) -> str:
    return "".join('<span class="sp"></span>' if ch == " " else f'<span class="ch">{ch}</span>' for ch in text)


def letters(word: str, attrs: str = "") -> str:
    return "".join('<span class="sp"></span>' if ch == " " else f'<span class="l"{attrs}>{ch}</span>' for ch in word)


def lens_videos(edit: dict) -> str:
    rows = []
    for g in edit["seg"]:
        rate = f' data-playback-rate="{g["rate"]}"' if abs(g["rate"] - 1) > 1e-6 else ""
        rows.append(f'<video id="v-{g["id"]}" class="clip" src="assets/take.mp4" muted playsinline data-start="{g["f0"]}" '
                    f'data-duration="{round(g["f1"] - g["f0"], 3)}" data-media-start="{g["s0"]}"{rate} data-track-index="2"></video>')
    return "\n".join(rows)


def lift_markup(edit: dict, box) -> str:
    g = next(g for g in edit["seg"] if g["id"] == "saved")
    x, y, w, h = box
    return (f'<div id="lift" class="ov" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
            # One frame earlier on both clocks: the same source mapping, not a duplicate media node.
            f'<video id="v-lift" class="clip" src="assets/take.mp4" muted playsinline data-start="{round(g["f0"] - 1 / FPS, 3)}" '
            f'data-duration="{round(g["f1"] - g["f0"] + 1 / FPS, 3)}" data-media-start="{round(g["s0"] - 1 / FPS, 3)}" data-track-index="3" '
            f'style="left:{-x}px;top:{-y}px"></video></div>')


def rings(edit: dict) -> str:
    out = []
    for i, k in enumerate(edit["clicks"]):
        for suffix, cls in (("a", "ring"), ("b", "ring lime")):
            out.append(f'<div class="{cls} ov" id="rg{i}{suffix}" style="left:{k["x"] - 95:.0f}px;top:{k["y"] - 95:.0f}px"></div>')
    return "\n".join(out)


def particles(money, pal: dict):
    html, data = [], []
    colors = [pal["hi"], pal["accent"], pal["ink"], "#ffffff", pal.get("spark", "#f2d06b")]
    sx, sy = money
    for i in range(40):
        size = 14 + prand(i * 3 + 1) * 24
        ang = -math.pi / 2 + (prand(i * 5 + 2) * 2 - 1) * 1.45
        speed = 900 + prand(i * 7 + 3) * 1900
        radius = "50%" if i % 3 == 0 else "4px"
        html.append(f'<div class="p" id="pt{i}" style="left:{sx - size / 2:.0f}px;top:{sy - size / 2:.0f}px;width:{size:.0f}px;'
                    f'height:{size * (0.62 if i % 3 else 1):.0f}px;background:{colors[i % len(colors)]};border-radius:{radius}"></div>')
        data.append({"vx": round(math.cos(ang) * speed, 1), "vy": round(math.sin(ang) * speed, 1),
                     "spin": round((prand(i * 11 + 4) * 2 - 1) * 720, 1)})
    return "\n".join(html), data


def motes(lay: dict):
    W, H = lay["W"], lay["H"]
    html, data = [], []
    for i in range(36):
        size = 3 + prand(i * 2.3) * 7
        html.append(f'<div class="mote" id="mo{i}" style="width:{size:.1f}px;height:{size:.1f}px"></div>')
        data.append({"x0": round(prand(i * 1.9) * W), "y0": round(H * 820 / 1080 + prand(i * 4.4) * H * 420 / 1080),
                     "speed": round(0.1 + prand(i * 6.1) * 0.22, 3), "phase": round(prand(i * 8.8), 3),
                     "alpha": round(0.3 + prand(i * 5.5) * 0.55, 3), "wob": round(0.6 + prand(i * 7.2), 3)})
    return "\n".join(html), data


def annot_circle(box):
    """A hand-drawn loop around a source region (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2 + 46, (y1 - y0) / 2 + 36
    pts = []
    for i in range(97):
        a = math.radians(-160) + (2 * math.pi + 0.55) * i / 96
        wob = 1 + 0.05 * math.sin(i * 0.37) + 0.035 * (i / 96)
        pts.append((cx + rx * wob * math.cos(a), cy + ry * wob * math.sin(a) - 4 * (i / 96)))
    pad = 30
    left, top = min(p[0] for p in pts) - pad, min(p[1] for p in pts) - pad
    right, bottom = max(p[0] for p in pts) + pad, max(p[1] for p in pts) + pad
    d = "M" + " L".join(f"{p[0] - left:.1f},{p[1] - top:.1f}" for p in pts)
    length = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    attr = (f'style="left:{left:.0f}px;top:{top:.0f}px;width:{right - left:.0f}px;height:{bottom - top:.0f}px" '
            f'viewBox="0 0 {right - left:.0f} {bottom - top:.0f}" width="{right - left:.0f}" height="{bottom - top:.0f}"')
    return attr, d, round(length + 4, 1)


def recap_cards(edit: dict, spec: dict, lay: dict, B: Grid, assets: Path | None = None) -> str:
    crops = spec["edit"]["recap"]   # [[source anchor, dt, crop x, crop y, crop width], ...]
    src = edit["src"]
    cw, ch = lay["recap"]["size"]
    out, receipts = [], []
    for i, (anchor, dt, x, y, w) in enumerate(crops):
        t = src[anchor] + dt
        k = cw / w
        left, top = lay["recap"]["cards"][i]
        if spec["edit"].get("recap_stills"):
            assert assets is not None
            crop_w = min(SRC_W, int(w) // 2 * 2)
            crop_h = min(SRC_H, int(crop_w * ch / cw) // 2 * 2)
            crop_x = max(0, min(int(x), SRC_W - crop_w))
            crop_y = max(0, min(int(y), SRC_H - crop_h))
            image = assets / f"recap-{i + 1}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "2", "-ss", f"{t:.3f}",
                            "-i", str(assets / "take.mp4"), "-frames:v", "1", "-vf",
                            f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={cw}:{ch}",
                            "-threads", "2", str(image)], check=True)
            receipts.append({"path": image.name, "source_time": round(t, 3),
                             "crop": [crop_x, crop_y, crop_w, crop_h], "size": [cw, ch],
                             "sha256": hashlib.sha256(image.read_bytes()).hexdigest()})
            out.append(f'<div class="rcard" id="rc{i + 1}" style="left:{left}px;top:{top}px;width:{cw}px;height:{ch}px">'
                       f'<img src="assets/{image.name}" alt="Recorded {anchor} result" '
                       f'style="display:block;width:100%;height:100%"></div>')
            continue
        out.append(f'<div class="rcard" id="rc{i + 1}" style="left:{left}px;top:{top}px;width:{cw}px;height:{ch}px">'
                   f'<video id="v-rc{i + 1}" class="clip" src="assets/take.mp4" '
                   f'muted playsinline data-start="{round(B(44 + i) - 0.1 * (i > 0), 3)}" data-duration="{round(B(48) - B(44 + i) + 0.1 * (i > 0), 3)}" '
                   f'data-media-start="{round(t, 3)}" '
                   f'data-playback-rate="0.25" data-track-index="{4 + i}" style="left:{-x * k:.1f}px;top:{-y * k:.1f}px;'
                   f'width:{SRC_W * k:.1f}px;height:{SRC_H * k:.1f}px"></video></div>')
    if receipts:
        (assets / "recap.json").write_text(json.dumps(receipts, indent=2) + "\n")
    return "\n".join(out)


# ------------------------------------------------------------------ palette + layout CSS
def palette(spec: dict) -> dict:
    p = dict(spec["palette"])
    ink, deep, accent, hi, paper = p["ink"], p["deep"], p["accent"], p["hi"], p["paper"]
    d = {
        "card": "#fbfaf6", "cardsmall": mix_hex(ink, paper, 0.55), "tag": mix_hex(accent, ink, 0.35),
        "herob": mix_hex(accent, ink, 0.4), "mute": mix_hex(ink, paper, 0.3), "page": paper,
        "hook": [mix_hex(ink, "#ffffff", 0.03), mix_hex(ink, deep, 0.6), mix_hex(deep, "#000000", 0.4)],
        "recapbg": [mix_hex(ink, "#ffffff", 0.05), mix_hex(ink, deep, 0.6), mix_hex(deep, "#000000", 0.33)],
        "endbg": [mix_hex(ink, "#ffffff", 0.1), mix_hex(ink, "#ffffff", 0.02), mix_hex(deep, "#000000", 0.15)],
        "chrome": mix_hex(paper, ink, 0.05), "chromeline": mix_hex(paper, ink, 0.12),
        "chromedot": mix_hex(paper, ink, 0.17), "chrometext": mix_hex(paper, ink, 0.78),   # >= 4.5:1 on the chrome bar
        "slabp": mix_hex(paper, accent, 0.35), "savep": mix_hex(ink, deep, 0.3),
        "limit": mix_hex(paper, accent, 0.4), "foot": mix_hex(paper, accent, 0.55),
        "ex": [mix_hex(hi, accent, 0.5), accent, mix_hex(accent, ink, 0.2), mix_hex(accent, ink, 0.4)],
        "flash": "#fffdf6", "rec": "#d24b4b", "spark": "#f2d06b", "hookacc": hi,
    }
    for k, v in d.items():
        p.setdefault(k, v)
    return p


def layout_css(lay: dict, pal: dict, fit: dict) -> str:
    W, H = lay["W"], lay["H"]
    wx, wy, ww, wh = lay["window"]
    sw, sh = lay["screen"]
    it, hud, st, sl, rc, en = lay["intro"], lay["hud"], lay["steps"], lay["slab"], lay["recap"], lay["end"]
    rx, ry, rs = en["rays"]
    css = [
        f":root{{--paper:{pal['paper']};--ink:{pal['ink']};--deep:{pal['deep']};--accent:{pal['accent']};--lime:{pal['hi']};"
        f"--mute:{pal['mute']};--page:{pal['page']};--card:{pal['card']};--cardsmall:{pal['cardsmall']};--tag:{pal['tag']};"
        f"--herob:{pal['herob']};--flash:{pal['flash']};--rec:{pal['rec']};--slabp:{pal['slabp']};--savep:{pal['savep']};"
        f"--limit:{pal['limit']};--foot:{pal['foot']};--chrome:{pal['chrome']};--chromeline:{pal['chromeline']};"
        f"--chromedot:{pal['chromedot']};--chrometext:{pal['chrometext']}}}",
        f".hook-bg{{background:radial-gradient(120% 95% at 50% 42%,{pal['hook'][0]} 0%,{pal['hook'][1]} 48%,{pal['hook'][2]} 100%)}}",
        f".hook-glow{{left:{W / 2 - 500:.0f}px;top:{H / 2 - 500:.0f}px;background:radial-gradient(closest-side,{rgba(pal['accent'], .45)},{rgba(pal['accent'], 0)})}}",
        f".storm-world{{left:{W / 2:.0f}px;top:{H / 2:.0f}px}}",
        f".kline{{font-size:{fit['k1']}px;letter-spacing:{-0.045 * fit['k1']:.1f}px}}",
        f".kline .acc{{color:{pal['hookacc']}}}",
        f"#kg2 .kline{{font-size:{fit['k2']}px;letter-spacing:{-0.045 * fit['k2']:.1f}px}}",
        f".hero{{font-size:{fit['hero']}px;max-width:{lay['hero']['max_w']}px;white-space:{'nowrap' if fit['hero_nowrap'] else 'normal'};text-align:center}}",
        f".dots{{width:{W + 240}px;height:{H + 280}px;background-image:radial-gradient({rgba(pal['ink'], .17)} 1.7px,transparent 2px)}}",
        f".blob.b1{{left:{W * 0.43:.0f}px;top:{-H * 0.39:.0f}px;width:{max(W, H) * 0.78:.0f}px;height:{max(W, H) * 0.68:.0f}px;"
        f"background:radial-gradient(closest-side,{rgba(pal['hi'], .85)},{rgba(pal['hi'], 0)})}}",
        f".blob.b2{{left:{-W * 0.27:.0f}px;top:{H * 0.39:.0f}px;width:{max(W, H) * 0.68:.0f}px;height:{max(W, H) * 0.57:.0f}px;"
        f"background:radial-gradient(closest-side,{rgba(pal['accent'], .32)},{rgba(pal['accent'], 0)})}}",
        f".window{{left:{wx}px;top:{wy}px;width:{ww}px;height:{wh}px;border-radius:{lay['radius']}px;"
        f"box-shadow:0 70px 140px {rgba(pal['deep'], .32)},0 16px 38px {rgba(pal['deep'], .16)}}}",
        f".chrome{{width:{ww}px;height:{lay['chrome']}px}}",
        f".screen{{top:{lay['chrome']}px;width:{sw}px;height:{sh}px}}",
        f".sheen{{height:{sh + 400}px}}",
        f"#spot{{background:radial-gradient(circle,{rgba(pal['deep'], 0)} 0,{rgba(pal['deep'], 0)} 330px,{rgba(pal['deep'], .58)} 1150px)}}",
        f"#stamp{{box-shadow:0 22px 56px {rgba(pal['ink'], .35)}}}",
        f"#scan i{{background:linear-gradient(to top,{rgba(pal['hi'], .55)},{rgba(pal['hi'], 0)})}}",
        f"#marker{{background:{rgba(pal['hi'], .95)}}}",
        f".intro{{left:{it['left']}px;top:{it['top']}px;width:{it['width']}px}}",
        f".wm{{font-size:{fit['wm']}px;letter-spacing:{-0.051 * fit['wm']:.1f}px}}",
        f".intro .tag span{{font-size:{fit['itag']}px;letter-spacing:{-0.037 * fit['itag']:.1f}px}}",
        f"#hud .corner{{border-color:{rgba(pal['ink'], .55)}}}",
        f".intro .chips span{{border-color:{rgba(pal['ink'], .35)}}}",
        f"#hud .tl{{left:{hud['side']}px;top:{hud['top']}px;background:{rgba(pal['paper'], .88)}}}",
        f"#hud .tr{{right:{hud['side']}px;top:{hud['top']}px;background:{rgba(pal['paper'], .88)}}}",
        f"#steps{{left:{st['left']}px;top:{st['top']}px;background:{rgba(pal['paper'], .94)};box-shadow:0 12px 34px {rgba(pal['ink'], .2)}}}",
        f".slab{{left:{sl['left']}px;top:{sl['top']}px}}",
        f".slab .bg{{box-shadow:0 26px 60px {rgba(pal['deep'], .34)}}}",
        f".slab h2{{font-size:{fit['h2']}px;letter-spacing:{-0.047 * fit['h2']:.1f}px}}",
        f".slab p{{font-size:{sl['p']}px}}",
        f".recap-bg{{background:radial-gradient(110% 90% at 50% 45%,{pal['recapbg'][0]} 0%,{pal['recapbg'][1]} 55%,{pal['recapbg'][2]} 100%)}}",
        f".rl{{width:{rc['word_w']}px;font-size:{fit['rl']}px;letter-spacing:{-0.042 * fit['rl']:.1f}px}}",
        # Portrait lays the words over the cards: a dark chip keeps them readable on a white app.
        (f".rl{{width:auto;text-align:left;padding:2px 30px 12px;border-radius:24px;background:{rgba(pal['deep'], .9)};"
         f"box-shadow:0 18px 44px rgba(0,0,0,.4);text-shadow:none}}" if rc.get("word_chip") else ""),
        f".end-bg{{background:radial-gradient(120% 100% at 50% 38%,{pal['endbg'][0]} 0%,{pal['endbg'][1]} 45%,{pal['endbg'][2]} 100%)}}",
        f".rays{{left:{rx}px;top:{ry}px;width:{rs}px;height:{rs}px;"
        f"background:repeating-conic-gradient(from 0deg,{rgba(pal['hi'], .08)} 0deg 5deg,{rgba(pal['hi'], 0)} 5deg 15deg)}}",
        f".end-inner{{top:{en['top']}px;width:{W}px}}",
        f".ewm{{font-size:{fit['ewm']}px;letter-spacing:{-0.0556 * fit['ewm']:.1f}px}}",
        f".ewm .l{{text-shadow:0 4px 0 {pal['ex'][0]},0 8px 0 {pal['ex'][1]},0 12px 0 {pal['ex'][2]},0 16px 0 {pal['ex'][3]},0 40px 60px rgba(0,0,0,.45)}}",
        f".ewm .dot{{text-shadow:0 0 40px {rgba(pal['hi'], .8)}}}",
        f".etag{{flex-direction:{'column' if en['stack_tag'] else 'row'};align-items:center;gap:{8 if en['stack_tag'] else 26}px}}",
        f".etag span{{font-size:{fit['etag']}px;letter-spacing:{-0.04 * fit['etag']:.1f}px}}",
        f".url{{font-size:{en['url']}px}}",
        f".echips{{flex-wrap:wrap;justify-content:center;max-width:{W - 120}px}}",
        f".echips span{{border-color:{rgba(pal['hi'], .5)}}}",
        f".limit{{max-width:{W - 160}px;text-align:center}}",
        f".efoot{{top:{en['foot_top']}px;width:{W}px}}",
        f"#grain{{width:{W + 400}px;height:{H + 400}px}}",
    ]
    return "\n".join(css)


def fit_sizes(copy: dict, lay: dict) -> dict:
    hk = copy.get("hook_" + lay["suffix"], copy["hook"])
    hero_text = f"{copy['hero']['text']} {copy['hero'].get('accent', '')}".strip()
    hero_nowrap = text_width(hero_text, lay["hero"]["size"], 720, -0.025) <= lay["hero"]["max_w"] - 92
    wordmark = copy["brand"]["wordmark"] + copy["brand"].get("dot", "")
    end = copy["end"]
    etag_lines = end["tagline"] if lay["end"]["stack_tag"] else [" ".join(end["tagline"])]
    return {
        "k1": fit_size(hk["a"], lay["kline"]["size"], lay["kline"]["max_w"], 800, -0.045),
        "k2": fit_size(hk["b"], lay["kline"]["size"], lay["kline"]["max_w"], 800, -0.045),
        "hero": lay["hero"]["size"], "hero_nowrap": hero_nowrap,
        "wm": fit_size([wordmark], lay["intro"]["wm"], lay["intro"]["width"] - 20, 800, -0.051),
        "itag": fit_size(copy["intro"]["tagline"], lay["intro"]["tag"], lay["intro"]["width"] - 20, 750, -0.037),
        "h2": fit_size([s["title"] for s in copy["steps"]], lay["slab"]["h2"], lay["slab"]["max_w"] - 84, 800, -0.047),
        "rl": fit_size(copy["recap"], lay["recap"]["word"], lay["recap"]["word_w"] - 20, 800, -0.042),
        "ewm": fit_size([wordmark], lay["end"]["wm"], lay["end"]["wm_max_w"], 800, -0.0556),
        "etag": fit_size(etag_lines, lay["end"]["tag"], lay["W"] - 140, 750, -0.04),
    }


# ------------------------------------------------------------------ audio
def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        assert w.getframerate() == sfx.SR and w.getsampwidth() == 2
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, w.getnchannels())
    return x.astype(np.float32) / 32768.0


def write_wav(path: Path, x: np.ndarray):
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sfx.SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def loudnorm(src: Path, out: Path, target: float = -16.0):
    """Two-pass EBU R128 through FFmpeg; true peak below -1.5 dBTP."""
    first = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af",
                            f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, check=True).stderr
    m = json.loads(first[first.rindex("{"):first.rindex("}") + 1])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af",
                    f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                    f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true",
                    "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out)], check=True)


def stems(spec: dict, edit: dict, B: Grid, dur: float, film: Path | None = None):
    """The owned music bed (eased and ducked under hits) and the synthesized sound design, as arrays."""
    sr, n = sfx.SR, int(dur * sfx.SR)
    T = edit["T"]
    # Existing films keep their video-owner-relative paths. Standalone films
    # explicitly resolve supplied music beside their own spec, never the cwd.
    off = spec["music"]["offset"]
    if spec["music"].get("synthesis") == "pulse":
        music = sfx.pulse_bed(dur, B.period)
    else:
        base = film if spec["music"].get("relative_to") == "film" else VIDEO
        music_file = base / spec["music"]["file"]
        music = read_wav(music_file)[int(off * sr):int(off * sr) + n]
    music = np.pad(music, ((0, n - len(music)), (0, 0)))
    t = np.arange(n) / sr
    # A hard onset on the first sample makes AAC priming overshoot by ~5 dB, so the bed eases in.
    env = np.clip((t - 0.01) / 0.06, 0, 1) * np.clip((dur - t) / 1.4, 0, 1) ** 1.5
    duck = np.ones(n)
    fx = np.zeros((n, 2), np.float32)

    def place(at, snd, db=0.0, duck_db=0.0):
        if at is None:
            return
        i = int(round(at * sr))
        if i >= n:
            return
        j = min(n, i + len(snd))
        ramp = np.minimum(1.0, np.arange(len(snd)) / 48.0)[:, None]  # 1 ms attack: no step edges
        fx[max(i, 0):j] += (snd * ramp)[max(0, -i):j - i] * (10 ** (db / 20))
        if duck_db:
            k = np.arange(n)
            d = (k - i) / sr
            shape = np.where(d < 0, 0, np.where(d < 0.18, 1, np.exp(-(d - 0.18) / 0.35)))
            np.minimum(duck, 1 - (1 - 10 ** (-duck_db / 20)) * shape, out=duck)

    place(B(0), sfx.impact(0.7, seed=21), -3, 4)
    place(B(1) - 0.05, sfx.swish(seed=22), -7)
    place(B(2.6), sfx.glitch(seed=23), -9)
    place(B(3.1), sfx.impact(0.45, seed=24), -6, 2)
    place(B(3.9) - 0.05, sfx.swish(seed=25), -9)
    place(B(4.8) - 0.02, sfx.sparkle(0.7, seed=26, n=10), -14)
    place(B(5.2), sfx.shine(0.8, seed=20), -12)
    place(B(7) - 0.34, sfx.whoosh(0.4, seed=27, bright=1.3), -4)
    place(B(7), sfx.impact(0.85, seed=28), -2, 5)
    place(B(8.6) - 0.1, sfx.shine(seed=29), -8)
    place(B(9.2), sfx.pop(seed=30, base=700), -6)
    for i in range(2):
        place(B(10.1) + i * 0.08, sfx.pop(seed=31 + i, base=900 + 150 * i), -12)
    place(T["dive"] - 0.05, sfx.whoosh(0.9, seed=33, bright=0.8), -6)
    place(B(12), sfx.swish(seed=34), -10)
    for k in edit["clicks"]:
        place(k["t"], sfx.mouse_click(seed=int(k["t"] * 100)), -4)
    for i, k in enumerate(edit["keys"]):
        place(k, sfx.key(seed=100 + i), -13)
    if spec["edit"]["act1"].get("annotate"):
        place(T["tagDone"] + 0.1, sfx.swish(0.3, seed=35), -12)
        place(T["tagDone"] + 0.35, sfx.pop(seed=36, base=820), -8)
    place(T["whip1"] - 0.02, sfx.whoosh(0.55, seed=37, bright=1.4), -3)
    place(T["save"] - 1.9, sfx.riser(1.9, seed=38), -5)
    place(T["save"] - 0.55, sfx.tick(seed=75), -7)
    place(T["save"] - 0.45, sfx.tick(seed=76), -7)
    place(T["save"], sfx.impact(1.0, seed=39), 0, 7)
    place(T["save"] + 0.02, sfx.sparkle(1.0, seed=40, n=22), -6)
    place(T["save"] + 0.05, sfx.pop(seed=41, base=560), -7)
    place(T["save"] + 0.16, sfx.whoosh(0.8, seed=42, bright=0.7), -9)
    place(T["lift"], sfx.shine(0.6, seed=43), -10)
    place(T["save"] + 0.75, sfx.swish(seed=44), -10)
    place(T["find"] - 0.04, sfx.glitch(0.36, seed=45), -5)
    place(T["find"], sfx.whoosh(0.55, seed=46, bright=1.4), -4)
    place(T["find"] + 0.5, sfx.swish(seed=47), -10)
    place(T["filtered"] - 0.05, sfx.scan(seed=48), -5)
    place(T["track"], sfx.tick(seed=49), -6)
    place(T["track"] + 0.18, sfx.pop(seed=50, base=760), -7)
    place(T["track"] + 0.4, sfx.swish(0.25, seed=51), -13)
    for i in range(3):
        place(B(44 + i), sfx.impact(0.45, seed=52 + i), -5, 2)
        place(B(44 + i) - 0.12, sfx.swish(0.22, seed=55 + i), -9)
    place(B(47), sfx.whoosh(0.5, seed=58), -6)
    place(T["end"] - 0.25, sfx.whoosh(0.35, seed=59, bright=1.5), -6)
    place(T["end"], sfx.impact(0.9, seed=60), -2, 5)
    for i in range(5):
        place(T["end"] + 0.15 + i * 0.065 + 0.2, sfx.tick(seed=61 + i), -14)
    place(T["end"] + 0.65 + 0.3, sfx.pop(seed=66, base=620), -6)
    for i in range(len(spec["copy"]["end"]["url"])):
        place(T["url"] + i * 0.045, sfx.key(seed=200 + i), -18)
    for i in range(3):
        place(T["url"] + 1.25 + i * 0.09, sfx.pop(seed=70 + i, base=880 + 90 * i), -13)
    place(T["shine"] - 0.05, sfx.shine(1.0, seed=73), -6)
    place(T["shine"], sfx.boom_tail(seed=74), -3, 6)

    return music * (env * duck)[:, None] * 0.82, fx * 0.9


def soften_aac_attack(path: Path, seconds: float = 0.12):
    """Keep the opening synthetic impact from ringing during AAC priming."""
    samples = read_wav(path)
    count = min(len(samples), round(seconds * sfx.SR))
    samples[:count] *= np.linspace(0, 1, count, dtype=np.float32)[:, None] ** 2
    write_wav(path, samples)


def mix(spec: dict, edit: dict, B: Grid, dur: float, out: Path, film: Path | None = None):
    """Owned music bed + synthesized sound design, normalised to -16 LUFS / -1.5 dBTP."""
    bed, fx = stems(spec, edit, B, dur, film)
    premix = bed + fx
    tmp = out.with_suffix(".premix.wav")
    write_wav(tmp, premix / max(1.0, float(np.max(np.abs(premix)))))
    loudnorm(tmp, out)
    if spec["music"].get("synthesis") == "pulse":
        soften_aac_attack(out)
    tmp.unlink()


# ------------------------------------------------------------------ assemble
def prepare_take(source: Path, destination: Path) -> dict:
    """Make a seekable render copy while retaining the original recording."""
    def digest(path):
        value = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(block)
        return value.hexdigest()

    recipe = {"fps": FPS, "keyframe_interval": FPS, "crf": 16, "preset": "veryfast"}
    source_hash = digest(source)
    receipt_path = destination.with_suffix(".json")
    if destination.is_file() and receipt_path.is_file():
        previous = json.loads(receipt_path.read_text())
        if (previous.get("source_sha256") == source_hash and previous.get("recipe") == recipe
                and previous.get("render_sha256") == digest(destination)):
            return previous
    temporary = destination.with_name("take.preparing.mp4")
    try:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", "2",
                        "-i", str(source), "-an", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "16", "-r", str(FPS), "-g", str(FPS), "-keyint_min", str(FPS),
                        "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-threads", "2",
                        "-movflags", "+faststart", "-y", str(temporary)], check=True)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = {"source_sha256": source_hash, "render_sha256": digest(destination), "recipe": recipe}
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def build(film: Path, fmt: str, audio: bool = True, take_override: Path | None = None) -> Path:
    spec = json.loads((film / "spec.json").read_text())
    if take_override is not None:
        spec["take"] = os.path.relpath(take_override.resolve(), film.resolve())
    lay = fmt_geometry(fmt)
    slab = spec.get("layout", {}).get(fmt, {}).get("slab")
    if slab:
        lay["slab"].update(slab)
    copy = spec["copy"]
    B = Grid(spec["music"])
    dur = spec.get("duration", 31.0)
    take = load_take(film, spec)
    edit = plan(spec, take, B)
    out = film / "cuts" / fmt
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    src_take = take["path"] / "screen.mp4"
    render_source = None
    if spec.get("source", {}).get("prepare_for_seek"):
        render_source = prepare_take(src_take, assets / "take.mp4")
    elif not (assets / "take.mp4").exists() or (assets / "take.mp4").stat().st_size != src_take.stat().st_size:
        shutil.copy2(src_take, assets / "take.mp4")
    for name in ("Manrope.ttf", "Manrope-OFL.txt", "GeistMono.ttf", "GeistMono-OFL.txt"):
        shutil.copy2(KIT / "assets" / name, assets / name)
    gsap_source = "assets/gsap.min.js"
    if (KIT / gsap_source).is_file():
        shutil.copy2(KIT / gsap_source, assets / "gsap.min.js")
    else:
        gsap_source = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
    for extra in spec.get("assets", []):             # e.g. the app's licence, kept beside the film
        shutil.copy2(film / extra, assets / Path(extra).name)
    pal = palette(spec)
    fit = fit_sizes(copy, lay)
    storm_html, storm_data = storm_cards(copy, lay)
    parts_html, parts_data = particles(edit["money"], pal)
    motes_html, motes_data = motes(lay)
    a1, a2, a3 = spec["edit"]["act1"], spec["edit"]["act2"], spec["edit"]["act3"]
    ann = a1.get("annotate")
    tag_attr, tag_path, tag_len = annot_circle(ann["region"]) if ann else ('style="left:0;top:0;width:10px;height:10px" viewBox="0 0 10 10"', "M0,0", 1)
    sx, sy = edit["money"]
    lx, ly, lw, lh = a2["lift_region"]
    fx0, fy0, fw, fh = a3["track_region"]
    wx, wy, ww, wh = a3.get("marker_region") or [fx0, fy0, 1, 1]
    scan_top, scan_bottom = a3.get("scan") or [fy0 - 300, fy0 + fh + 300]
    def pick(d, key, default):
        """A per-format override (key_portrait / key_landscape) wins over the shared value."""
        return (d or {}).get(f"{key}_{fmt}", (d or {}).get(key, default))
    st_dx, st_dy = pick(a2, "stamp_offset", [-560, -300])
    lk_dx, lk_dy = pick(a2, "label_offset", [-122, -158])
    ax0, ay0, ax1, ay1 = ann["region"] if ann else [0, 0, 0, 0]
    an_dx, an_dy = pick(ann, "note_offset", [-40, 70])
    side = pick(a3, "label_side", "right")   # "right" or "below" the tracking box
    cur = cursor_track(take, edit, dur)
    frames = {**auto_framings(spec, lay, take), **spec.get("framings", {}).get(fmt, {})}
    hk = copy.get("hook_" + lay["suffix"], copy["hook"])
    wordmark = copy["brand"]["wordmark"]
    dot = copy["brand"].get("dot", ".")
    tl = f"{lay['W']}x{lay['H']}"
    plan_json = {
        "dur": dur, "beat0": B.beat0, "period": B.period, "t": edit["T"], "seg": edit["seg"], "clicks": edit["clicks"],
        "cur": cur, "storm": storm_data, "parts": parts_data, "motes": motes_data, "frames": frames,
        "tagLen": tag_len, "annot": bool(ann), "url": copy["end"]["url"], "L": {"scanTravel": scan_bottom - scan_top},
        "world": world_plan(lay["world"], B, edit["T"]), "screen": lay["screen"], "focus": lay["focus"],
        "tcRes": lay["hud"]["tc_res"], "recap": lay["recap"], "W": lay["W"], "H": lay["H"],
        "kgExplode": [280, 220] if fmt == "landscape" else [200, 300],
    }
    overlay_css = (
        f"#tagnote{{left:{ax0 + an_dx}px;top:{ay1 + an_dy}px}}"
        f"#spot{{left:{sx - 4500}px;top:{sy - 4500}px}}"
        f"#stamp{{left:{sx + st_dx}px;top:{sy + st_dy}px}}"
        f"#lock{{left:{sx - 122}px;top:{sy - 83}px;width:244px;height:166px}}"
        f"#locklabel{{left:{sx + lk_dx}px;top:{sy + lk_dy}px}}"
        f"#liftglow{{left:{lx - 10}px;top:{ly - 10}px;width:{lw + 20}px;height:{lh + 20}px}}"
        f"#scan{{left:{min(lx, fx0) - 40}px;top:{scan_top}px;width:{max(lw, fw) + 80}px}}"
        f"#track{{left:{fx0}px;top:{fy0}px;width:{fw}px;height:{fh}px}}"
        f"#tlabel{{left:{fx0 + fw + 36 if side == 'right' else fx0}px;"
        f"top:{fy0 + 6 if side == 'right' else fy0 + fh + 30}px}}"
        f"#marker{{left:{wx}px;top:{wy}px;width:{ww}px;height:{wh}px}}"
        f"#parts{{width:1px;height:1px}}"
    )
    rc = lay["recap"]
    recap_words = "\n".join(
        f'<div class="rl{" acc" if i == 1 else ""}" id="rl{i + 1}" style="left:{rc["words"][i][0]}px;top:{rc["words"][i][1]}px">{w}</div>'
        for i, w in enumerate(copy["recap"]))
    steps = copy["steps"]
    slabs = "\n".join(
        f'<div class="slab{" save" if i == 1 else ""}" id="slab{i + 1}"><div class="bg"></div><div class="in"><div class="eb">{s["eyebrow"]}</div>'
        f'<div class="mask"><h2>{s["title"]}</h2></div><p>{s["sub"]}</p></div></div>' for i, s in enumerate(steps))
    pills = "".join(f'<span id="st{i + 1}" style="left:{7 + 204 * i}px">{s["pill"]}</span>' for i, s in enumerate(steps))
    etag = end_tag(copy["end"]["tagline"])
    chips = lambda xs: "".join(f"<span>{c}</span>" for c in xs)  # noqa: E731
    hero = copy["hero"]
    tokens = {
        "__TITLE__": f"{copy['brand']['name']} — motion cut ({fmt})", "__COMP_ID__": f"{spec['id']}-motion-{fmt}",
        "__GSAP_SRC__": gsap_source,
        "__W__": str(lay["W"]), "__H__": str(lay["H"]), "__DUR__": str(dur), "__HOOK_DUR__": str(round(B(7) + 0.3, 3)),
        "__LAYOUT_CSS__": layout_css(lay, pal, fit),
        "__STORM__": storm_html,
        "__K1__": accent_marks(hk["a"][0]), "__K2__": accent_marks(hk["a"][1]),
        "__K3__": split_chars(hk["b"][0]), "__K4__": split_chars(hk["b"][1]),
        "__HERO__": f'<small>{hero["eyebrow"]}</small>{hero["text"]}' + (f' <b>{hero["accent"]}</b>' if hero.get("accent") else ""),
        "__WINDOW_TITLE__": copy["window_title"],
        "__VIDEOS__": lens_videos(edit), "__TAGC_ATTR__": tag_attr, "__TAGC_PATH__": tag_path,
        "__TAG_NOTE__": (ann or {}).get("label", ""), "__LIFT__": lift_markup(edit, a2["lift_region"]),
        "__TRACK_LABEL__": a3["track_label"], "__LOCK_LABEL__": a2["lock_label"], "__STAMP__": a2["stamp"],
        "__RINGS__": rings(edit), "__PARTS__": parts_html,
        "__INTRO_EB__": copy["intro"]["eyebrow"], "__WM__": letters(wordmark), "__DOT__": dot,
        "__ITAG__": "".join(f"<div><span>{line}</span></div>" for line in copy["intro"]["tagline"]),
        "__ICHIPS__": chips(copy["intro"]["chips"]),
        "__PILLS__": pills, "__SLABS__": slabs,
        "__RECAP__": recap_cards(edit, spec, lay, B, assets), "__RECAP_WORDS__": recap_words,
        "__END_START__": str(edit["T"]["end"]), "__END_DUR__": str(round(dur - edit["T"]["end"], 3)),
        "__MOTES__": motes_html, "__EWM__": letters(wordmark, " data-layout-allow-occlusion"),
        "__GLINT__": "".join('<span class="sp" data-layout-ignore></span>' if ch == " " else f"<span data-layout-ignore>{ch}</span>" for ch in wordmark),
        "__ETAG__": etag, "__ECHIPS__": chips(copy["end"]["chips"]), "__LIMIT__": copy["end"]["limit"],
        "__FOOT__": copy["end"]["foot"], "__REC_LABEL__": copy.get("hud_label", "Taskfilm &middot; REAL CAPTURE"),
        "__PLAN__": json.dumps(plan_json, separators=(",", ":")),
        "</style></head>": overlay_css + "\n</style></head>",
    }
    html = (KIT / "template.tpl").read_text()
    for k, v in tokens.items():
        assert k in html, k
        html = html.replace(k, v)
    assert "__" not in html.split("<script>")[0].replace("__timelines", ""), "unfilled token"
    (out / "index.html").write_text(html)
    (out / "index.motion.json").write_text(json.dumps({"duration": dur, "assertions": [
        {"kind": "appearsBy", "selector": "#k1", "bySec": 0.6},
        {"kind": "appearsBy", "selector": "#slab1", "bySec": round(B(12) + 0.6, 2)},
        {"kind": "appearsBy", "selector": "#stamp", "bySec": round(edit["T"]["save"] + 0.6, 2)},
        {"kind": "appearsBy", "selector": "#tlabel", "bySec": round(edit["T"]["track"] + 0.8, 2)},
        {"kind": "appearsBy", "selector": "#ewm .dot", "bySec": round(edit["T"]["end"] + 1.6, 2)},
    ]}, indent=2) + "\n")
    (out / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
        "media": {"autoProxy": True}}, indent=2) + "\n")
    (out / "package.json").write_text(json.dumps({
        "name": f"{spec['id']}-motion-{fmt}", "private": True, "type": "module",
        "scripts": {"check": f"npx --yes {HF} check", "render": f"npx --yes {HF} render"}}, indent=2) + "\n")
    if audio:
        mix(spec, edit, B, dur, assets / "mix.wav", film)
    decisions = {
        "film": spec["id"], "format": fmt, "canvas": [lay["W"], lay["H"]], "accepted_take": take["path"].name,
        "time_unit": "seconds", "fps": FPS, "duration": dur,
        "capture": {"size": [SRC_W, SRC_H], "css_zoom": spec.get("source", {}).get("css_zoom"),
                    "maximum_lens_scale": max(f["s"] for f in frames.values()),
                    "pointer": "drawn by the film from input.jsonl (recorder overlay hidden)"},
        "music": {"file": spec["music"].get("file"), "offset": spec["music"]["offset"], "bpm": round(60 / B.period, 2),
                  "rights": spec["music"].get("rights", "")},
        "beat0": B.beat0, "period": B.period, "times": edit["T"], "segments": edit["seg"],
        "source_events": edit["src"], "lens_framings": frames,
        "sound_design": "sfx.py, deterministic NumPy/SciPy synthesis; keys follow visible characters",
        "kit": "apps/video/hyperframes-lane/product-motion",
    }
    if spec["music"].get("synthesis"):
        decisions["music"]["synthesis"] = spec["music"]["synthesis"]
    if render_source:
        decisions["capture"]["render_source"] = render_source
    if spec["edit"].get("recap_stills"):
        decisions["recap_frames"] = json.loads((assets / "recap.json").read_text())
    (out / "EDIT-DECISIONS.json").write_text(json.dumps(decisions, indent=2) + "\n")
    digest = hashlib.sha256((out / "index.html").read_bytes()).hexdigest()[:12]
    print(f"{fmt}: index.html {digest} · {len(edit['seg'])} segments · {len(edit['clicks'])} clicks · "
          f"{len(edit['keys'])} key sounds · fit {fit}")
    return out


def main() -> int:
    """The portable authoring surface; rendering stays with HyperFrames."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("film", type=Path, help="directory containing spec.json and the accepted 4K take")
    parser.add_argument("--format", choices=tuple(FORMATS), default="landscape")
    parser.add_argument("--no-audio", action="store_true", help="author visuals without building the supplied music/SFX mix")
    parser.add_argument("--take", type=Path, help="use this explicitly selected take instead of spec.json's take path")
    args = parser.parse_args()
    build(args.film.resolve(), args.format, audio=not args.no_audio, take_override=args.take)
    return 0


def end_tag(lines) -> str:
    acc = ' class="acc"'
    return "".join(f'<div><span{acc if i == len(lines) - 1 else ""}>{t}</span></div>' for i, t in enumerate(lines))



if __name__ == "__main__":
    raise SystemExit(main())
