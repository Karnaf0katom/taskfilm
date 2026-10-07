#!/usr/bin/env python3
"""pixels — what changed on screen, where, and how much.

One measurement, two questions, and they were about to become two copies:

* ``learn.py`` asks it of a *control*: press this, and was the consequence worth filming?
* ``plan.py`` asks it of a *click*: the app answered somewhere — point the camera at the answer.

Both are "diff two frames and describe the difference", so it lives here once. Nothing in this file
knows about browsers, plans or takes; it takes two grey arrays and returns arithmetic.

numpy and PIL are imported inside the functions on purpose. `plan.py` must stay runnable on a box
that has neither — a take still plans, it just keeps pointing the camera at the click and says so.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# The diff resolution. Finer than this and the measurement is of the video codec, not of the app:
# h264 rewrites a few LSBs everywhere on every frame, and at full resolution that reads as "the
# whole screen changed".
PROBE_W, PROBE_H = 320, 180

# Below this a per-pixel delta is compression and antialiasing, not the app doing something.
DELTA_FLOOR = 16


def available() -> bool:
    """Can this box measure pixels at all? Callers degrade rather than crash."""
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def grid(png: bytes):
    """A screenshot as a small grey array — small enough that a diff is a fact, not a render."""
    import io

    import numpy as np
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("L").resize((PROBE_W, PROBE_H))
    return np.asarray(img, dtype=np.float32)


def frame(video: Path, t: float):
    """One frame of a recording, at video second ``t``, as the same grey array.

    Piped rather than written: aiming a take's punch-ins asks for two frames per zoom, and twenty
    temp PNGs on the way to twenty numbers is a mess somebody has to clean up.
    """
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(t, 0.0):.3f}",
         "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    return grid(proc.stdout)


def compare(before, after) -> dict:
    """What changed between two frames, as a fraction and as a box."""
    import numpy as np
    delta = np.abs(after - before)
    hit = delta > DELTA_FLOOR
    fraction = float(hit.mean())
    box = {"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.0}
    if hit.any():
        ys, xs = np.where(hit)
        x0, x1 = xs.min() / PROBE_W, (xs.max() + 1) / PROBE_W
        y0, y1 = ys.min() / PROBE_H, (ys.max() + 1) / PROBE_H
        box = {"x": round((x0 + x1) / 2, 4), "y": round((y0 + y1) / 2, 4),
               "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}
    return {"changed": round(fraction, 4), "box": box,
            "luma_after": round(float(after.mean()), 2)}


def densest_change(before, after, cells: int = 12, window: int = 4) -> dict | None:
    """**Where** the change is concentrated — not the box that contains all of it.

    ``compare``'s box is the min/max extent of every changed pixel, which is the right answer for
    "did this control do something" and the wrong one for "where do I point the camera". Press an
    engine chip in a side panel and three things repaint at once: the chip, the whole parameter list
    under it, and the preview. The extent of all three is most of the window, so its centre is the
    middle of the screen — which is exactly where the camera should *not* go.

    So this scores by **magnitude**, not by hit count, over a sliding window of cells, and returns
    the window carrying the most of it. A preview swapping from a wireframe to falling code moves
    every pixel in it a long way; a row of slider labels re-rendering moves a few pixels a little.
    The former wins, which is the shot.

    ``share`` is how much of all the change that window holds — the caller's confidence. A change
    smeared evenly over the screen gives a low share, and a low share should be ignored rather than
    aimed at.
    """
    import numpy as np
    delta = np.abs(after - before)
    delta[delta <= DELTA_FLOOR] = 0.0
    total = float(delta.sum())
    if total <= 0.0:
        return None

    # Sum into a coarse grid, then find the heaviest window×window block of it.
    ch, cw = PROBE_H // cells, PROBE_W // cells
    coarse = delta[:ch * cells, :cw * cells].reshape(cells, ch, cells, cw).sum(axis=(1, 3))
    window = max(1, min(window, cells))
    best, best_weight = (0, 0), -1.0
    for row in range(cells - window + 1):
        for col in range(cells - window + 1):
            weight = float(coarse[row:row + window, col:col + window].sum())
            if weight > best_weight:
                best, best_weight = (row, col), weight

    row, col = best
    block = delta[row * ch:(row + window) * ch, col * cw:(col + window) * cw]
    # Centre of mass inside the winning block, so the aim lands on the busy part of it rather than
    # on the middle of an arbitrary rectangle.
    ys, xs = np.nonzero(block)
    if len(xs) == 0:
        return None
    weights = block[ys, xs]
    cx = (col * cw + float((xs * weights).sum() / weights.sum())) / PROBE_W
    cy = (row * ch + float((ys * weights).sum() / weights.sum())) / PROBE_H
    # The extent of the change *inside* the winning block, not the block itself — the caller sets
    # its zoom depth from this, and a fixed-size window would make every answer the same size.
    return {"x": round(cx, 4), "y": round(cy, 4),
            "w": round(float(xs.max() - xs.min() + 1) / PROBE_W, 4),
            "h": round(float(ys.max() - ys.min() + 1) / PROBE_H, 4),
            "share": round(best_weight / total, 4),
            "changed": round(float((delta > 0).mean()), 4)}
