#!/usr/bin/env python3
"""webrec — let an agent drive one of our web apps and record the take as a capture-lane bundle.

The desktop path (``hfrec.py``) needs a real screen: OBS, a logged-in Windows box, a human or
humanflow moving a physical mouse. Every app we would demo — freecut, the trading terminal, the
dashboards — is a *browser* app, and for those that whole apparatus is the wrong shape:

  * **it knows where to press.** Selectors come from the DOM, not from guessing at pixels, so a
    step either resolves or fails loudly. ``discover`` dumps the same map a model reads to write
    the script in the first place.
  * **the clock is exact.** Frames and input events are stamped by one process, so ``video_t``
    is arithmetic, not a five-sample median guess at OBS's timecode.
  * **it runs here.** Headless Chrome on this box, no VM to power on, no licence, no watermark.

The one thing headless does not give you is a cursor — screencast frames contain no pointer. So we
draw one: a real mouse event is dispatched (hover states, drags and focus all behave), and an
overlay cursor glides to the same point along a humanflow bezier path with a click ripple behind
it. That is not a workaround; a styled cursor with click feedback is what the demo videos people
actually watch look like.

Output is byte-for-byte the bundle ``plan.py`` already reads, so the whole downstream pipeline —
zooms, chapters, typing runs, and whatever hyperframes does with them — works unchanged.

Usage:
    python webrec.py check
    python webrec.py discover http://localhost:4173 [--out map.json] [--wait-for SELECTOR]
    python webrec.py validate demo.json
    python webrec.py rec demo.json [--out-dir DIR] [--headed] [--keep-frames]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
_MONOREPO_HUMANFLOW = REPO_ROOT / "apps/automation-platform/clicker-man/humanflow/src"
_PACKAGED_HUMANFLOW = Path(__file__).resolve().parents[2] / "humanflow"
HUMANFLOW_SRC = Path(os.environ.get("CAPTURE_LANE_HUMANFLOW_SRC", str(
    _MONOREPO_HUMANFLOW if _MONOREPO_HUMANFLOW.is_dir() else _PACKAGED_HUMANFLOW)))
DEFAULT_OUT = Path(os.environ.get("CAPTURE_LANE_RECORDINGS", str(
    REPO_ROOT / "dropbox/recordings" if _MONOREPO_HUMANFLOW.is_dir() else Path.cwd() / "recordings")))

# Real sessions live outside the repo, mode 0700, and are never printed, copied into a bundle, or
# published. A session cookie is the account; treating it as a build artifact is how it ends up in
# a git history or on a static host.
AUTH_HOME = Path(os.environ.get("CAPTURE_LANE_AUTH_HOME", Path.home() / ".capture-lane"))
AUTH_STATES = AUTH_HOME / "auth"
AUTH_PROFILES = AUTH_HOME / "profiles"

# A demo reads as deliberate at roughly this pace. Faster and the viewer cannot follow the cursor;
# slower and the take needs cutting down anyway.
GLIDE_MIN_S = 0.45
GLIDE_MAX_S = 1.10
GLIDE_PX_PER_S = 1400.0
SETTLE_S = 0.35          # after a click, before the next move — the app gets to respond on camera
TYPE_DELAY_S = 0.06      # per keystroke; fast enough to be real, slow enough to read

# Real mouse events only need enough samples for :hover and drag to behave; the *visible* cursor is
# animated by the overlay at display rate, so this is not the thing the viewer sees.
REAL_MOVE_SAMPLES = 14

SCREENCAST_QUALITY = 92
OUTPUT_FPS = 30
DOWNLOAD_CLEANUP_TIMEOUT_S = 2.0


def _humanflow():
    """humanflow owns motion + DOM scanning (capabilities.yaml). Import it, never re-derive it.

    ``path_generator`` is loaded from its file rather than as ``humanflow.motion.path_generator``
    because that package's ``__init__`` also pulls in ``mouse_mover``, which needs ``pynput`` and
    a real desktop. This lane never touches a physical mouse, and making it depend on one — on a
    headless box, in a container — would be the wrong dependency for the wrong reason. The curve
    maths is still humanflow's, byte for byte.
    """
    # humanflow's ``scan_elements()`` wraps this JS for the *sync* Playwright API; this lane is
    # async (frames have to keep arriving while a step runs), so the same scan is awaited instead
    # of copied. The JS — the part that decides what counts as a visible, pressable element — is
    # humanflow's, unchanged.
    # Loading these two owner files directly avoids agent.__init__ as well as
    # motion.__init__: both pull unrelated desktop/provider dependencies.
    modules = []
    for name, relative in (("humanflow_path_generator", "motion/path_generator.py"),
                           ("humanflow_dom_scan", "agent/dom_scan.py")):
        source = HUMANFLOW_SRC / "humanflow" / relative
        spec = importlib.util.spec_from_file_location(name, source)
        if spec is None or spec.loader is None:                 # pragma: no cover - packaging fault
            raise ImportError(f"humanflow owner missing at {source}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules[0].generate_human_path, modules[1]._SCAN_JS


def browser_executable() -> Path | None:
    """Explicit override, then system Chrome, then Playwright's platform cache."""
    if configured := os.environ.get("CAPTURE_LANE_BROWSER_PATH"):
        path = Path(configured).expanduser()
        if not path.is_file():
            raise ValueError("CAPTURE_LANE_BROWSER_PATH must name an existing browser executable")
        return path
    if Path("/usr/bin/google-chrome").is_file():
        return Path("/usr/bin/google-chrome")
    # Playwright resolves PLAYWRIGHT_BROWSERS_PATH and Windows/macOS cache paths.
    # At launch, omitting executable_path lets it use its matching browser build.
    return None


# ---------------------------------------------------------------------------------------------
# the drawn cursor
# ---------------------------------------------------------------------------------------------
# Injected before any page script and re-injected on every navigation, so an SPA route change or a
# full reload never loses the pointer mid-take. Everything is pointer-events:none and lives on
# documentElement, so it cannot intercept a click or be reflowed away by the app's own layout.
OVERLAY_JS = r"""
(() => {
  if (window.__hfcursor) { window.__hfcursor.reattach(); return; }
  const layer = document.createElement('div');
  // An init script runs in EVERY frame, and an app that loads its own favicon or an <img> of an
  // SVG gets a subframe holding an *XML* document. There, createElement() returns a namespace-less
  // Element with no .style at all, so the next line throws before anything is drawn. Measured on
  // uptime-kuma: 3 page errors per take from its /icon.svg frame, which read as the app's bug for
  // a whole evening. There is no cursor to draw in an SVG subframe, so leave.
  if (!layer.style) return;
  layer.setAttribute('data-hf-overlay', '1');
  layer.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;' +
    'pointer-events:none;z-index:2147483647;overflow:hidden;';

  const cur = document.createElement('div');
  cur.style.cssText = 'position:absolute;left:0;top:0;width:26px;height:26px;' +
    'transform:translate3d(-100px,-100px,0);will-change:transform;opacity:0;' +
    'transition:opacity .18s ease;';
  cur.innerHTML =
    '<svg width="26" height="26" viewBox="0 0 26 26" xmlns="http://www.w3.org/2000/svg">' +
    '<defs><filter id="hfsh" x="-50%" y="-50%" width="200%" height="200%">' +
    '<feDropShadow dx="0" dy="1.5" stdDeviation="1.6" flood-opacity="0.45"/></filter></defs>' +
    '<path filter="url(#hfsh)" d="M4 2 L4 20.5 L9.1 15.9 L12.1 22.6 L15.4 21.1 L12.4 14.6 L19.3 14.3 Z" ' +
    'fill="#ffffff" stroke="#111827" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  layer.appendChild(cur);

  const chip = document.createElement('div');
  chip.style.cssText = 'position:absolute;left:50%;bottom:6%;transform:translateX(-50%);' +
    'font:600 20px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace;color:#f8fafc;' +
    'background:rgba(15,23,42,.86);border:1px solid rgba(148,163,184,.35);border-radius:10px;' +
    'padding:10px 16px;opacity:0;transition:opacity .15s ease;letter-spacing:.04em;' +
    'box-shadow:0 8px 24px rgba(0,0,0,.35);max-width:70%;white-space:nowrap;overflow:hidden;' +
    'text-overflow:ellipsis;';
  layer.appendChild(chip);

  const attach = () => { (document.body || document.documentElement).appendChild(layer); };
  if (document.body) attach();
  else document.addEventListener('DOMContentLoaded', attach, { once: true });

  let px = -100, py = -100, anim = null, chipTimer = null;

  const put = (x, y) => {
    px = x; py = y;
    cur.style.transform = 'translate3d(' + (x - 3) + 'px,' + (y - 1) + 'px,0)';
  };

  const ripple = (kind) => {
    const r = document.createElement('div');
    const size = kind === 'down' ? 16 : 46;
    r.style.cssText = 'position:absolute;left:' + (px - size / 2) + 'px;top:' + (py - size / 2) +
      'px;width:' + size + 'px;height:' + size + 'px;border-radius:50%;' +
      'border:2.5px solid rgba(56,189,248,.95);background:rgba(56,189,248,.18);';
    layer.appendChild(r);
    const a = r.animate(
      [{ transform: 'scale(.35)', opacity: 1 }, { transform: 'scale(1)', opacity: 0 }],
      { duration: kind === 'down' ? 220 : 520, easing: 'cubic-bezier(.22,.61,.36,1)' });
    a.onfinish = () => r.remove();
  };

  window.__hfcursor = {
    // A Vue/React route change can replace document.body wholesale, taking the overlay with
    // it. Re-injection alone cannot fix that: the JS context survives a soft navigation, so
    // the guard above sees __hfcursor and returns. Put the existing layer back instead.
    reattach() { if (!layer.isConnected) (document.body || document.documentElement).appendChild(layer); },
    show() { cur.style.opacity = '1'; },
    hide() { cur.style.opacity = '0'; },
    at(x, y) { put(x, y); cur.style.opacity = '1'; },
    // Animate along a pre-computed path. The path comes from humanflow so the curve, the
    // overshoot and the jitter are the same motion model the desktop lane replays with.
    glide(points, ms) {
      if (anim) { cancelAnimationFrame(anim); anim = null; }
      if (!points || !points.length) return;
      cur.style.opacity = '1';
      const t0 = performance.now();
      const step = (now) => {
        const p = Math.max(0, Math.min((now - t0) / ms, 1));
        const i = Math.min(Math.floor(p * (points.length - 1)), points.length - 1);
        put(points[i][0], points[i][1]);
        if (p < 1) anim = requestAnimationFrame(step);
        else { anim = null; put(points[points.length - 1][0], points[points.length - 1][1]); }
      };
      anim = requestAnimationFrame(step);
    },
    press() { ripple('down'); },
    release() { ripple('up'); },
    key(label) {
      chip.textContent = label;
      chip.style.opacity = '1';
      if (chipTimer) clearTimeout(chipTimer);
      chipTimer = setTimeout(() => { chip.style.opacity = '0'; }, 1300);
    },
    caption(text, ms) {
      chip.textContent = text;
      chip.style.opacity = text ? '1' : '0';
      if (chipTimer) clearTimeout(chipTimer);
      if (text && ms) chipTimer = setTimeout(() => { chip.style.opacity = '0'; }, ms);
    },
  };
})();
//# sourceURL=webrec-overlay.js
"""


# ---------------------------------------------------------------------------------------------
# whatever is standing in front of the app
# ---------------------------------------------------------------------------------------------
# A demo does not fail on the app. It fails on a cookie banner, a "what's new" modal, a trial
# nag — the furniture a signed-in human clicks away without noticing and then forgets exists.
# These are matched by accessible name, so they survive a redesign the way a class name does not,
# and every hit is logged: a take that silently dismissed something is worse than one that did not.
BLOCKERS = [
    'role=button[name=/^(accept|accept all|allow all|i agree|agree|got it|ok, got it)$/i]',
    'role=button[name=/^(close|dismiss|no thanks|not now|maybe later|skip|skip for now)$/i]',
    'role=button[name=/^(continue|continue without|stay logged out)$/i]',
    '[aria-label="Close"]',
    '[data-testid*="close" i]',
    'button.close',
]


DIALOG_SELECTOR = "[role=dialog], [role=alertdialog]"


async def open_dialogs(page: Any) -> set[str]:
    """A signature per visible dialog, so two snapshots can be differenced.

    The text is the signature because it is the only thing stable across a render: a radix id
    changes every mount, and a dialog has no accessible name worth trusting.
    """
    try:
        texts = await page.eval_on_selector_all(
            DIALOG_SELECTOR,
            "els => els.filter(e => e.offsetParent !== null || e.getClientRects().length)"
            "        .map(e => (e.innerText || '').trim().slice(0, 160))")
    except Exception:                                           # noqa: BLE001
        return set()
    return {t for t in texts if t}


async def dismiss_blockers(page: Any, extra: list[str], verbose: bool = True,
                           rounds: int = 2, protect: set[str] | None = None) -> list[str]:
    """Click away the furniture, best effort, never fatal.

    Two rounds because banners queue: a cookie wall often reveals an onboarding modal underneath.
    Anything that is not visible within a heartbeat is not there, so the timeout is deliberately
    tiny — a demo must not spend four seconds waiting for a dialog that never existed.

    ``protect`` is what the *setup walk deliberately opened*, and it exists because this swept away
    the thing it was sent to find. FreeCut's Motion workspace opens on "No compositions yet"; the
    walk pressed **New composition**; the dialog that came up has a close button; the sweep read
    that close button as furniture and put the app straight back to the empty screen. Measured
    2026-08-30 — nothing failed, the map just came back describing a screen nobody asked for.

    A dialog is furniture when it appears *by itself* and load-bearing when the script's own last
    action produced it, so the caller differences the open dialogs across that final step and hands
    the new ones in here. Everything else is still swept, and every skip is logged: a guard that
    quietly stopped guarding is worse than one that never ran.
    """
    cleared: list[str] = []
    for _ in range(max(rounds, 1)):
        hit = False
        for selector in list(extra) + BLOCKERS:
            try:
                target = page.locator(selector).first
                if await target.count() == 0:
                    continue
                if protect and await _inside_protected(target, protect):
                    if verbose:
                        print(f"    kept    · {selector[:56]} — the setup walk opened this",
                              flush=True)
                    continue
                await target.click(timeout=900)
            except Exception:                                   # noqa: BLE001
                continue
            cleared.append(selector)
            hit = True
            if verbose:
                print(f"    cleared · {selector[:64]}", flush=True)
            await asyncio.sleep(0.35)
        if not hit:
            break
    return cleared


async def _inside_protected(target: Any, protect: set[str]) -> bool:
    """Does this candidate sit inside a dialog the script opened on purpose?"""
    try:
        text = await target.evaluate(
            "el => { const d = el.closest('[role=dialog], [role=alertdialog]');"
            "        return d ? (d.innerText || '').trim().slice(0, 160) : ''; }")
    except Exception:                                           # noqa: BLE001
        return False
    return bool(text) and text in protect


# ---------------------------------------------------------------------------------------------
# the bundle
# ---------------------------------------------------------------------------------------------
class Bundle:
    """Writes exactly the streams ``plan.py`` reads — humanflow's event schema, unchanged.

    ``t0`` is the timestamp of the first screencast frame, so ``video_t = ts - t0`` is the frame
    the event actually lands on rather than an estimate. The desktop lane has to negotiate this
    with OBS across a socket; here both numbers come off one clock.
    """

    def __init__(self, session_dir: Path, redact_keys: bool = True,
                 record_downloads: bool = False, record_uploads: bool = False):
        self.dir = session_dir
        owned_take = record_downloads or record_uploads
        if owned_take:
            for parent in self.dir.absolute().parents:
                try:
                    info = parent.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError("download take ancestors must be real directories")
        # Export evidence must belong to this take; never truncate a previous take's logs.
        self.dir.mkdir(parents=True, exist_ok=not owned_take)
        self.redact = redact_keys
        self.t0: float | None = None
        self._input = (self.dir / "input.jsonl").open("w", encoding="utf-8")
        self._windows = (self.dir / "windows.jsonl").open("w", encoding="utf-8")
        self._beats = (self.dir / "beats.jsonl").open("w", encoding="utf-8")
        self._last_event = time.time()
        self.counts = {"click": 0, "move": 0, "key": 0, "scroll": 0}
        self.chapters = 0
        self.beats = 0
        self.downloads: list[dict] = []
        self.uploads: list[dict] = []
        self.assertions: list[dict] = []
        self._uploads = None
        self._downloads = None
        self._take_fd: int | None = None
        self._download_fd: int | None = None
        self._download_ancestors: list[tuple[Path, tuple[int, int]]] = []
        if owned_take:
            self.dir = self.dir.absolute()
            for path in (self.dir, *self.dir.parents):
                info = path.stat(follow_symlinks=False)
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError("download take ancestors must be real directories")
                self._download_ancestors.append((path, (info.st_dev, info.st_ino)))
            if record_downloads:
                (self.dir / "downloads").mkdir(mode=0o700)
            self._take_fd = os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if record_downloads:
            self._download_fd = os.open("downloads", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                        dir_fd=self._take_fd)
            journal = os.open("downloads.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=self._take_fd)
            self._downloads = os.fdopen(journal, "w", encoding="utf-8")
        if record_uploads:
            try:
                journal = os.open("uploads.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                  0o600, dir_fd=self._take_fd)
                self._uploads = os.fdopen(journal, "w", encoding="utf-8")
            except Exception:
                self.close()
                raise

    def upload_receipt(self, receipt: dict) -> None:
        if self._uploads is None:
            raise ValueError("upload_recording_not_enabled")
        for path, identity in self._download_ancestors:
            info = path.stat(follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
                raise ValueError("upload_take_identity_changed")
        info = os.stat("uploads.jsonl", dir_fd=self._take_fd, follow_symlinks=False)
        held = os.fstat(self._uploads.fileno())
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (held.st_dev, held.st_ino):
            raise ValueError("upload_journal_identity_changed")
        self._uploads.write(json.dumps(receipt, ensure_ascii=False, allow_nan=False) + "\n")
        self._uploads.flush()
        os.fsync(self._uploads.fileno())
        self.uploads.append(receipt)

    def check_download_owner(self) -> None:
        """The receipt and its relative artifact paths must still name the allocated take."""
        if self._download_fd is None or self._take_fd is None:
            raise DownloadCaptureError("download_recording_not_enabled")
        for path, identity in self._download_ancestors:
            info = path.stat(follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
                raise DownloadCaptureError("download_take_identity_changed")
        info = os.stat("downloads", dir_fd=self._take_fd, follow_symlinks=False)
        held = os.fstat(self._download_fd)
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != (held.st_dev, held.st_ino):
            raise DownloadCaptureError("download_root_not_owned")

    def download_receipt(self, receipt: dict) -> None:
        if self._downloads is None:
            raise ValueError("download recording was not enabled for this take")
        self._downloads.write(json.dumps(receipt, ensure_ascii=False) + "\n")
        self._downloads.flush()
        os.fsync(self._downloads.fileno())
        self.downloads.append(receipt)

    def _dt(self) -> float:
        now = time.time()
        dt = now - self._last_event
        self._last_event = now
        return round(dt, 6)

    def _write(self, event: dict) -> None:
        self._input.write(json.dumps(event) + "\n")
        self._input.flush()

    def move(self, x: float, y: float) -> None:
        self.counts["move"] += 1
        self._write({"device": "mouse", "type": "move", "x": round(x, 1), "y": round(y, 1),
                     "dt": self._dt(), "ts": time.time()})

    def click(self, x: float, y: float, pressed: bool, button: str = "left") -> None:
        if pressed:
            self.counts["click"] += 1
        self._write({"device": "mouse", "type": "click", "x": round(x, 1), "y": round(y, 1),
                     "button": button, "pressed": pressed, "dt": self._dt(), "ts": time.time()})

    def scroll(self, x: float, y: float, dx: float, dy: float) -> None:
        self.counts["scroll"] += 1
        self._write({"device": "mouse", "type": "scroll", "x": round(x, 1), "y": round(y, 1),
                     "dx": float(dx), "dy": float(dy), "dt": self._dt(), "ts": time.time()})

    def key(self, key: str, kind: str = "press") -> None:
        # Same rule as the desktop lane: these takes get posted, so the default log carries the
        # shape of the typing and not its content. plan.py only counts key events anyway.
        if kind == "press":
            self.counts["key"] += 1
        self._write({"device": "keyboard", "type": kind,
                     "key": "char" if (self.redact and len(key) == 1) else key,
                     "dt": self._dt(), "ts": time.time()})

    def chapter(self, title: str) -> None:
        now = time.time()
        if not title:
            return
        self.chapters += 1
        self._windows.write(json.dumps({
            "type": "window", "title": title, "ts": now,
            "video_t": round(now - (self.t0 or now), 3)}) + "\n")
        self._windows.flush()

    def beat(self, beat_id: str, vo: str = "", explain: str = "", show: str = "",
             lang: str = "") -> None:
        """Mark what this stretch of the take is *saying*, at the instant it starts saying it.

        The clicks say where the demo went; a beat says why it went there. It is a separate
        stream from ``windows.jsonl`` because a chapter is a boundary in the *app* (the route
        changed) and a beat is a boundary in the *argument* — one point the video makes. Nothing
        is rendered here: the text lands in the composition, where it can still be re-timed,
        re-voiced and reframed for a vertical cut. Burn it into the frame and all three are gone.
        """
        now = time.time()
        self.beats += 1
        self._beats.write(json.dumps({
            "id": beat_id or f"beat-{self.beats}", "vo": vo, "explain": explain, "show": show,
            # The language rides with the line, not with the project: one take can carry an
            # English read and a Hebrew one, and the frame has to know which way the words run.
            "lang": lang or "en", "ts": now, "video_t": round(now - (self.t0 or now), 3)}) + "\n")
        self._beats.flush()

    def close(self) -> None:
        self._input.close()
        self._windows.close()
        self._beats.close()
        if self._downloads is not None:
            self._downloads.close()
        if self._uploads is not None:
            self._uploads.close()
        if self._download_fd is not None:
            os.close(self._download_fd)
        if self._take_fd is not None:
            os.close(self._take_fd)


# ---------------------------------------------------------------------------------------------
# screencast -> mp4
# ---------------------------------------------------------------------------------------------
MIN_FRAME_S = 1.0 / 120


def frame_listing(frames: list[tuple[float, Path]], end_ts: float) -> str:
    """The concat listing for a variable-rate capture, with the recording's own length kept.

    Every downstream cut trusts ``video_t = ts - t0``, so the encoded timeline must be exactly as
    long as the capture was. Frames closer together than ``MIN_FRAME_S`` are therefore *dropped*
    (the one already on screen stays up), never stretched to a floor — stretching is what made a
    69.8 s recording encode as 73.7 s and put every beat ~5% early.
    """
    kept: list[tuple[float, Path]] = []
    for ts, path in frames:
        if kept and ts - kept[-1][0] < MIN_FRAME_S:
            continue
        kept.append((ts, path))
    if end_ts - kept[-1][0] < MIN_FRAME_S and len(kept) > 1:
        kept.pop()
    lines = []
    for i, (ts, path) in enumerate(kept):
        nxt = kept[i + 1][0] if i + 1 < len(kept) else end_ts
        lines.append(f"file '{path.name}'")
        lines.append(f"duration {nxt - ts:.6f}")
    # concat's last entry carries no duration of its own, so the final frame is repeated.
    lines.append(f"file '{kept[-1][1].name}'")
    return "\n".join(lines) + "\n"


@dataclass
class Screencast:
    """CDP ``Page.startScreencast`` frames, kept with their capture times.

    Chrome emits a frame when the page changes, not on a fixed clock, so the frames are held with
    their own timestamps and handed to ffmpeg's concat demuxer with real per-frame durations. A
    fixed-rate encode of a variable-rate capture is what makes screen recordings drift.
    """

    frames_dir: Path
    frames: list[tuple[float, Path]] = field(default_factory=list)
    dropped: int = 0

    async def start(self, cdp: Any, width: int, height: int) -> None:
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        cdp.on("Page.screencastFrame", self._on_frame_sync)
        self._cdp = cdp
        await cdp.send("Page.startScreencast", {
            "format": "jpeg", "quality": SCREENCAST_QUALITY,
            "maxWidth": width, "maxHeight": height, "everyNthFrame": 1})

    def _on_frame_sync(self, params: dict) -> None:
        asyncio.create_task(self._on_frame(params))

    async def _on_frame(self, params: dict) -> None:
        now = time.time()
        meta = params.get("metadata") or {}
        stamp = meta.get("timestamp")
        # Chrome sends epoch seconds here, but a build that ever changes clock domain would make
        # every frame time nonsense. Trust it only when it agrees with our own clock.
        if not isinstance(stamp, (int, float)) or abs(stamp - now) > 60:
            stamp = now
        path = self.frames_dir / f"f{len(self.frames):06d}.jpg"
        try:
            path.write_bytes(base64.b64decode(params["data"]))
            self.frames.append((float(stamp), path))
        except Exception:                                       # noqa: BLE001
            self.dropped += 1
        try:
            await self._cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except Exception:                                       # noqa: BLE001
            self.dropped += 1                                   # page closed mid-flight

    async def stop(self) -> None:
        try:
            await self._cdp.send("Page.stopScreencast")
        except Exception:                                       # noqa: BLE001
            pass
        await asyncio.sleep(0.25)                               # let in-flight frames land

    def encode(self, out: Path, end_ts: float) -> tuple[bool, str]:
        if len(self.frames) < 2:
            return False, f"only {len(self.frames)} frame(s) captured — nothing to encode"
        listing = self.frames_dir / "frames.txt"
        listing.write_text(frame_listing(self.frames, end_ts), encoding="utf-8")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "concat", "-safe", "0", "-i", str(listing),
               "-fps_mode", "cfr", "-r", str(OUTPUT_FPS),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-pix_fmt", "yuv420p", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return False, (proc.stderr or "ffmpeg failed").strip().splitlines()[-1]
        return True, str(out)


# ---------------------------------------------------------------------------------------------
# the demo script
# ---------------------------------------------------------------------------------------------
async def wait_for_first_frame(screencast: Screencast, timeout_s: float = 15.0) -> bool:
    """Wait for retained pixels, rather than treating cold-browser latency as proof."""
    deadline = time.monotonic() + timeout_s
    while not screencast.frames:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(0.05, remaining))
    return True


STEP_KINDS = {"goto", "click", "dblclick", "hover", "type", "key", "scroll",
              "wait", "wait_for", "chapter", "caption", "drag", "beat", "download", "upload", "assert"}


SETUP_KINDS = (STEP_KINDS - {"download", "upload", "assert"}) | {"eval"}


def _upload_problems(step: dict) -> list[str]:
    required = {"do", "id", "selector", "seed", "expected_bytes", "expected_sha256", "max_bytes", "timeout"}
    problems = []
    if set(step) != required:
        problems.append("upload requires only its explicit seed/input/byte-proof/timeout fields")
    for key in ("id", "seed"):
        value = step.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) or ".." in value:
            problems.append(f"upload needs a safe '{key}' basename")
    if not isinstance(step.get("selector"), str) or not step["selector"].strip():
        problems.append("upload needs one explicit file-input selector")
    for key in ("expected_bytes", "max_bytes"):
        if type(step.get(key)) is not int or not 0 < step[key] <= 2**53 - 1:
            problems.append(f"upload needs positive integer '{key}'")
    if not problems and step["expected_bytes"] > step["max_bytes"]:
        problems.append("upload expected bytes exceed its limit")
    if not isinstance(step.get("expected_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", step["expected_sha256"]):
        problems.append("upload needs an explicit SHA256")
    timeout = step.get("timeout")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 600:
        problems.append("upload needs a finite timeout, 0 < timeout <= 600")
    return problems


def _seed_name(seed: dict) -> str:
    return seed.get("as") or Path(seed["path"]).name


# These are recorder-owned programs, never script-supplied page JS. A private immutable File
# is made from the verified bytes; rereading a mutable OPFS name would lose that binding.
PREPARE_UPLOAD_JS = """
async ({token, name, expected_bytes, expected_sha256, max_bytes, deadline_ms}) => {
  const entries = window.__hfRecordedUploads ||= new Map();
  const slot = {deadline_ms};
  entries.set(token, slot);
  const fail = code => ({error: code});
  try {
    const root = await navigator.storage.getDirectory();
    const file = await (await root.getFileHandle(name)).getFile();
    if (file.name !== name || file.size !== expected_bytes || file.size > max_bytes)
      return fail('upload_seed_size_mismatch');
    // WebCrypto needs a bounded ArrayBuffer. Keep an immutable File copy for dispatch:
    // an OPFS-backed File can become unreadable if another writer changes its handle.
    const data = await file.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', data);
    const sha256 = Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('');
    if (sha256 !== expected_sha256) return fail('upload_seed_hash_mismatch');
    if (entries.get(token) !== slot || Date.now() > deadline_ms)
      return fail('upload_verification_cancelled');
    Object.assign(slot, {file: new File([data], file.name, {type: file.type, lastModified: file.lastModified}), sha256});
    return {name: file.name, bytes: file.size, sha256};
  } catch (_) { return fail('upload_seed_unavailable'); }
}
"""

DISPATCH_UPLOAD_JS = """
(el, {token}) => {
  const slot = window.__hfRecordedUploads?.get(token);
  if (!slot?.file || slot.supplied || Date.now() > slot.deadline_ms)
    return {error: 'upload_verified_file_unavailable'};
  if (!(el instanceof HTMLInputElement) || el.type !== 'file' || !el.isConnected ||
      el.disabled || el.webkitdirectory || el.hasAttribute('directory'))
    return {error: 'upload_target_not_file_input'};
  const transfer = new DataTransfer();
  transfer.items.add(slot.file);
  el.files = transfer.files;
  slot.supplied = true;
  const event_ts = Date.now() / 1000;
  // This invokes the application's ordinary handlers. Their asynchronous result is unknown.
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return {name: slot.file.name, bytes: slot.file.size, sha256: slot.sha256, event_ts,
          events: ['input', 'change'], app_result: 'unknown'};
}
"""

CLEANUP_UPLOAD_JS = """
token => { window.__hfRecordedUploads?.delete(token); return true; }
"""


def _download_problems(step: dict) -> list[str]:
    problems = []
    for key in ("id", "filename"):
        value = step.get(key)
        if (not isinstance(value, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
                or ".." in value):
            problems.append(f"download needs a safe, explicit '{key}' basename")
    if not isinstance(step.get("selector"), str) or not step["selector"].strip() or "at" in step:
        problems.append("download needs an explicit selector, without an 'at' override")
    timeout = step.get("timeout")
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or not 0 < timeout <= 600):
        problems.append("download needs a finite 'timeout' in seconds, 0 < timeout <= 600")
    if type(step.get("max_bytes")) is not int or step["max_bytes"] <= 0:
        problems.append("download needs a positive integer 'max_bytes' retention limit")
    return problems


class DownloadCaptureError(Exception):
    """Stable non-secret error code; browser errors/URLs may contain signed credentials."""


def validate_script(script: dict) -> list[str]:
    """Fail on paper before failing on camera — a bad step costs a whole take."""
    problems: list[str] = []
    for i, step in enumerate(script.get("setup") or []):
        if step.get("do") not in SETUP_KINDS:
            problems.append(f"setup step {i}: unknown 'do': {step.get('do')!r}")
        elif step["do"] == "eval" and not step.get("js"):
            problems.append(f"setup step {i}: 'eval' needs 'js'")
    stage = script.get("stage") or {}
    if not isinstance(stage, dict):
        problems.append("'stage' must be an object")
    elif not isinstance(stage.get("init_scripts", []), list):
        problems.append("'stage.init_scripts' must be a list of JS strings")
    elif stage.get("auth") and stage.get("profile"):
        problems.append("'stage' names both 'auth' and 'profile' — a profile already carries its "
                        "own cookies, so the saved session would be silently ignored")
    elif stage.get("auth") and not auth_state_path(stage["auth"]).exists():
        problems.append(f"'stage.auth' names {stage['auth']!r}, which is not saved yet "
                        f"(python webrec.py auth grab {stage['auth']} --cdp <port>)")
    elif stage.get("profile") and not (AUTH_PROFILES / _slug(stage["profile"])).exists():
        problems.append(f"'stage.profile' names {stage['profile']!r}, which does not exist yet "
                        f"(python webrec.py auth login {stage['profile']} --url <the app>)")
    if not script.get("url"):
        problems.append("missing 'url'")
    if not isinstance(script.get("steps"), list) or not script["steps"]:
        problems.append("missing or empty 'steps'")
        return problems
    download_ids: set[str] = set()
    upload_ids: set[str] = set()
    upload_proofs: dict[str, tuple] = {}
    for i, step in enumerate(script["steps"]):
        where = f"step {i}"
        kind = step.get("do")
        if kind not in STEP_KINDS:
            problems.append(f"{where}: unknown 'do': {kind!r} (known: {sorted(STEP_KINDS)})")
            continue
        if kind == "download":
            problems.extend(f"{where}: {problem}" for problem in _download_problems(step))
            step_id = step.get("id")
            if isinstance(step_id, str):
                if step_id in download_ids:
                    problems.append(f"{where}: duplicate download id {step_id!r}")
                download_ids.add(step_id)
        if kind == "upload":
            errors = _upload_problems(step)
            problems.extend(f"{where}: {error}" for error in errors)
            if not errors:
                if step["id"] in upload_ids:
                    problems.append(f"{where}: duplicate upload id")
                upload_ids.add(step["id"])
                seeds = stage.get("seed_files", []) if isinstance(stage, dict) else []
                if not isinstance(seeds, list) or sum(isinstance(seed, dict) and bool(seed.get("path"))
                        and _seed_name(seed) == step["seed"] for seed in seeds) != 1:
                    problems.append(f"{where}: upload must name exactly one stage.seed_files item")
                proof = (step["expected_bytes"], step["expected_sha256"], step["max_bytes"])
                if step["seed"] in upload_proofs and upload_proofs[step["seed"]] != proof:
                    problems.append(f"{where}: upload seed has conflicting byte proofs")
                upload_proofs[step["seed"]] = proof
        if (kind in {"click", "dblclick", "hover", "wait_for"} and not step.get("selector")
                and not step.get("at")):
            problems.append(f"{where}: '{kind}' needs a 'selector' (or an 'at' point)")
        if kind == "type" and "text" not in step:
            problems.append(f"{where}: 'type' needs 'text'")
        if kind == "assert":
            if not isinstance(step.get("selector"), str) or not step["selector"].strip():
                problems.append(f"{where}: 'assert' needs a selector")
            if not isinstance(step.get("text"), str) or not 0 < len(step["text"]) <= 2000:
                problems.append(f"{where}: 'assert' needs 1–2000 characters of exact expected text")
            shot = step.get("screenshot")
            if not isinstance(shot, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.png", shot) or ".." in shot:
                problems.append(f"{where}: 'assert' needs a safe .png screenshot basename")
            timeout = step.get("timeout", 15)
            if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
                problems.append(f"{where}: 'assert' timeout must be finite, 0 < timeout <= 60")
        if kind == "key" and not step.get("key"):
            problems.append(f"{where}: 'key' needs 'key'")
        if kind == "drag" and not (step.get("selector")
                                   and (step.get("to") or step.get("to_at"))):
            problems.append(f"{where}: 'drag' needs 'selector' and a 'to' (or a 'to_at' point)")
        if kind == "chapter" and not step.get("title"):
            problems.append(f"{where}: 'chapter' needs 'title'")
        if kind == "beat" and not (step.get("vo") or step.get("explain")):
            problems.append(f"{where}: 'beat' needs a 'vo' line or an 'explain' — a beat that "
                            f"says nothing is a chapter")
    return problems


# ---------------------------------------------------------------------------------------------
# the director
# ---------------------------------------------------------------------------------------------
class Director:
    """Runs the script: resolve → glide → dispatch → log.

    The order matters. The overlay cursor is *ahead* of the real event by the glide duration, which
    is what makes the click look intentional: the viewer sees the pointer arrive, settle, and then
    the app react — the same beat ``plan.py``'s 0.6 s zoom lead is built around.
    """

    def __init__(self, page: Any, bundle: Bundle, width: int, height: int, verbose: bool = True,
                 cdp: Any = None, burn_captions: bool = True, lang: str = "en", upload_seeds=()):
        self.page = page
        self.cdp = cdp
        self.burn_captions = burn_captions
        self.lang = lang or "en"
        self.bundle = bundle
        self.width = width
        self.height = height
        self.verbose = verbose
        self.x = width / 2
        self.y = height * 0.62                    # start low, so the first move travels upward
        self.failures: list[str] = []
        self._download_click_active = False
        self._download_mouse_held = False
        self._download_press_receipt: dict | None = None
        self.upload_seeds = tuple(_seed_name(seed) for seed in upload_seeds)
        self._gen_path, _ = _humanflow()

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"    {msg}", flush=True)

    async def _overlay(self, expr: str) -> None:
        try:
            await self.page.evaluate(expr)
        except Exception:                                       # noqa: BLE001
            pass                                                # a navigation mid-call is not fatal

    async def glide_to(self, tx: float, ty: float) -> None:
        dist = math.hypot(tx - self.x, ty - self.y)
        if dist < 2:
            return
        seconds = min(max(dist / GLIDE_PX_PER_S, GLIDE_MIN_S), GLIDE_MAX_S)
        steps = max(int(seconds * 60), 12)
        path = self._gen_path((self.x, self.y), (tx, ty), steps=steps,
                              curve_strength=0.16, jitter=1.2)
        await self._overlay(
            "window.__hfcursor && window.__hfcursor.glide("
            + json.dumps([[round(p[0], 1), round(p[1], 1)] for p in path])
            + f", {int(seconds * 1000)})")
        # The real pointer follows the same curve, coarsely — enough for :hover, drag thresholds
        # and pointermove listeners to see a human trajectory rather than a teleport.
        stride = max(len(path) // REAL_MOVE_SAMPLES, 1)
        samples = path[::stride] + [path[-1]]
        for point in samples:
            await self.page.mouse.move(point[0], point[1])
            self.bundle.move(point[0], point[1])
            await asyncio.sleep(seconds / len(samples))
        self.x, self.y = tx, ty

    async def _locate(self, selector: str, timeout_s: float) -> tuple[float, float] | None:
        try:
            locator = self.page.locator(selector).first
            await locator.wait_for(state="visible", timeout=timeout_s * 1000)
            await locator.scroll_into_view_if_needed(timeout=timeout_s * 1000)
            box = await locator.bounding_box()
        except Exception as exc:                                # noqa: BLE001
            self.failures.append(f"{selector!r}: {type(exc).__name__}")
            return None
        if not box or box["width"] < 1 or box["height"] < 1:
            self.failures.append(f"{selector!r}: resolved to a zero-size box")
            return None
        # Not dead centre: a real hand lands slightly off, and dead centre is also where a tooltip
        # or a centred icon most often sits on top of the thing you meant to hit.
        return (box["x"] + box["width"] * random.uniform(0.38, 0.62),
                box["y"] + box["height"] * random.uniform(0.38, 0.62))

    async def press_release(self, double: bool = False) -> None:
        await self._overlay("window.__hfcursor && window.__hfcursor.press()")
        if self._download_click_active:
            # The browser may press before its RPC acknowledges. Cancellation must release this
            # action's possibly-held button without inventing a confirmed input press event.
            self._download_mouse_held = True
            if self._download_press_receipt is not None:
                self._download_press_receipt["requested_ts"] = time.time()
        await self.page.mouse.down()
        if self._download_click_active and self._download_press_receipt is not None:
            self._download_press_receipt["acknowledged"] = True
        self.bundle.click(self.x, self.y, pressed=True)
        await asyncio.sleep(0.055)
        await self.page.mouse.up()
        if self._download_click_active:
            self._download_mouse_held = False
        self.bundle.click(self.x, self.y, pressed=False)
        await self._overlay("window.__hfcursor && window.__hfcursor.release()")
        if double:
            await asyncio.sleep(0.07)
            await self.page.mouse.down()
            await self.page.mouse.up()
            self.bundle.click(self.x, self.y, pressed=True)
            self.bundle.click(self.x, self.y, pressed=False)

    async def _drag(self, start: tuple[float, float], end: tuple[float, float]) -> bool:
        """Drag for real, including the HTML5 kind.

        A ``draggable`` element does not move for synthetic mouse events: Chrome swallows the
        gesture and turns it into a drag it expects the *client* to carry, so a plain
        down-move-up records as a cursor sliding over a timeline that never accepts the clip.
        ``Input.setInterceptDrags`` hands us that drag's payload, and we then dispatch dragOver
        along the same path and drop it at the end — at demo pace, so the take shows the clip
        landing under the cursor rather than teleporting.

        Apps that implement dragging with pointer events instead never intercept, and those fall
        back to the plain mouse path, which is exactly right for them.
        """
        intercepted: dict[str, Any] = {}
        if self.cdp is not None:
            def capture(params: dict) -> None:
                intercepted.setdefault("data", params.get("data"))
            try:
                self.cdp.on("Input.dragIntercepted", capture)
                await self.cdp.send("Input.setInterceptDrags", {"enabled": True})
            except Exception:                                   # noqa: BLE001
                pass

        await self.page.mouse.down()
        self.bundle.click(self.x, self.y, pressed=True)
        # A drag only starts once the pointer passes the browser's threshold, so nudge first.
        await self.page.mouse.move(start[0] + 12, start[1] + 12)
        for _ in range(20):
            if intercepted.get("data"):
                break
            await asyncio.sleep(0.02)

        data = intercepted.get("data")
        if not data:                                            # pointer-event app: plain drag
            await self.glide_to(*end)
            await self.page.mouse.up()
            self.bundle.click(self.x, self.y, pressed=False)
            return False

        # Chrome now owns the gesture; the visible cursor and the drag events are driven together.
        dist = math.hypot(end[0] - self.x, end[1] - self.y)
        seconds = min(max(dist / GLIDE_PX_PER_S, GLIDE_MIN_S), GLIDE_MAX_S) * 1.4
        path = self._gen_path((self.x, self.y), end, steps=max(int(seconds * 40), 16),
                              curve_strength=0.10, jitter=0.8)
        await self._overlay(
            "window.__hfcursor && window.__hfcursor.glide("
            + json.dumps([[round(p[0], 1), round(p[1], 1)] for p in path])
            + f", {int(seconds * 1000)})")
        stride = max(len(path) // REAL_MOVE_SAMPLES, 1)
        first = True
        for point in path[::stride] + [path[-1]]:
            await self.cdp.send("Input.dispatchDragEvent", {
                "type": "dragEnter" if first else "dragOver",
                "x": point[0], "y": point[1], "data": data})
            first = False
            self.bundle.move(point[0], point[1])
            await asyncio.sleep(seconds / max(len(path[::stride]), 1))
        await self.cdp.send("Input.dispatchDragEvent",
                            {"type": "drop", "x": end[0], "y": end[1], "data": data})
        self.x, self.y = end
        self.bundle.click(end[0], end[1], pressed=False)
        try:
            await self.cdp.send("Input.setInterceptDrags", {"enabled": False})
        except Exception:                                       # noqa: BLE001
            pass
        return True

    async def _download(self, step: dict) -> bool:
        """Retain the first download emitted by one recorded click, never an existing export.

        Reuses this page and the ordinary glide/mouse/input log. Extra automatic sidecars are
        counted while the action is active, but are not retained or claimed by this receipt.
        """
        problems = _download_problems(step)
        if problems:
            self.failures.extend(problems)
            return False
        if self.bundle._downloads is None:
            self.failures.append("download recording was not enabled for this take")
            return False
        step_hash = hashlib.sha256(json.dumps(
            step, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        receipt = {"schema_version": "webrec-download/v1", "step_id": step["id"],
                   "step_sha256": step_hash, "status": "failed", "started_ts": time.time(),
                   "event_ts": None, "video_t": None, "artifact": None,
                   "selection": "first_download_event_after_click",
                   "product_verified": False, "qa_status": "not_run"}
        artifact_path = f"downloads/{step['id']}/{step['filename']}"
        directory_fd: int | None = None
        temporary: str | None = None
        file_identity: tuple[int, int] | None = None
        download = None
        committed = False
        observed: list[tuple[Any, float]] = []
        listening = False
        cancelled = False
        phase = "prepare"

        def observe(item: Any) -> None:
            observed.append((item, time.time()))

        def check_owner() -> None:
            self.bundle.check_download_owner()
            if directory_fd is not None:
                info = os.stat(step["id"], dir_fd=self.bundle._download_fd, follow_symlinks=False)
                held = os.fstat(directory_fd)
                if (not stat.S_ISDIR(info.st_mode)
                        or (info.st_dev, info.st_ino) != (held.st_dev, held.st_ino)):
                    raise DownloadCaptureError("download_step_identity_changed")

        def unlink_owned(name: str) -> None:
            # Held directory FDs never traverse a replaced take/ancestor pathname.
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            if (info.st_dev, info.st_ino) != file_identity:
                raise DownloadCaptureError("cleanup_file_identity_changed")
            os.unlink(name, dir_fd=directory_fd)

        async def perform() -> None:
            nonlocal temporary, download, committed, listening, phase, directory_fd, file_identity
            if self.bundle.t0 is None:
                raise DownloadCaptureError("recording_clock_missing")
            if self._download_mouse_held:
                raise DownloadCaptureError("previous_download_button_still_held")
            check_owner()
            os.mkdir(step["id"], mode=0o700, dir_fd=self.bundle._download_fd)
            directory_fd = os.open(step["id"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                   dir_fd=self.bundle._download_fd)
            phase = "locate"
            locator = self.page.locator(step["selector"])
            await locator.wait_for(state="visible", timeout=step["timeout"] * 1000)
            if await locator.count() != 1:
                raise DownloadCaptureError("selector_not_unique")
            point = await self._locate(step["selector"], step["timeout"])
            if point is None:
                raise DownloadCaptureError("selector_not_visible")
            await self.glide_to(*point)
            check_owner()
            self.page.on("download", observe)
            listening = True
            phase = "click_and_event"
            async with self.page.expect_download(timeout=step["timeout"] * 1000) as pending:
                receipt["click_started_ts"] = time.time()
                receipt["input_click_index"] = self.bundle.counts["click"] + 1
                self._download_press_receipt = {"requested_ts": None, "acknowledged": False}
                receipt["mouse_press"] = self._download_press_receipt
                self._download_click_active = True
                await self.press_release()
            download = await pending.value
            event_ts = next((ts for item, ts in observed if item is download), None)
            if event_ts is None or event_ts < max(self.bundle.t0, receipt["click_started_ts"]):
                raise DownloadCaptureError("download_event_clock_missing_or_invalid")
            receipt.update(event_ts=event_ts, video_t=round(event_ts - self.bundle.t0, 6))
            phase = "download_completion"
            if await download.failure():
                raise DownloadCaptureError("browser_download_failed")
            phase = "save"
            # Local Playwright owns this newly emitted download's temporary file. Copy via an
            # already-open output-directory FD instead of handing a mutable take path to save_as.
            # Playwright connections that cannot expose download.path() fail explicitly here.
            downloaded_path = await download.path()
            check_owner()
            source_fd = os.open(downloaded_path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(source_fd, "rb") as source:
                source_info = os.fstat(source.fileno())
                if not stat.S_ISREG(source_info.st_mode) or not 0 < source_info.st_size <= step["max_bytes"]:
                    raise DownloadCaptureError("download_empty_or_exceeds_max_bytes")
                temporary = ".partial-" + uuid.uuid4().hex
                fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory_fd)
                info = os.fstat(fd)
                file_identity = (info.st_dev, info.st_ino)
                size = 0
                with os.fdopen(fd, "w+b") as saved:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        check_owner()
                        size += len(chunk)
                        if size > step["max_bytes"]:
                            raise DownloadCaptureError("download_empty_or_exceeds_max_bytes")
                        saved.write(chunk)
                        await asyncio.sleep(0)  # Deadline/cancellation applies during large copies too.
                    if size != source_info.st_size:
                        raise DownloadCaptureError("download_size_changed")
                    saved.flush()
                    os.fsync(saved.fileno())
                    saved.seek(0)
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: saved.read(1024 * 1024), b""):
                        digest.update(chunk)
            phase = "retain"
            # Hard-linking within the owned directory atomically refuses an existing target.
            check_owner()
            os.link(temporary, step["filename"], src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                    follow_symlinks=False)
            committed = True
            receipt["artifact"] = {"path": artifact_path,
                                   "bytes": size, "sha256": digest.hexdigest()}

        cleanup = {"temporary_removed": True, "cancel_requested": False,
                   "owned_mouse_release": "not_needed", "path_binding_valid": True}

        async def cleanup_resources() -> None:
            nonlocal listening
            deadline = asyncio.get_running_loop().time() + DOWNLOAD_CLEANUP_TIMEOUT_S
            cleanup["budget_seconds"] = DOWNLOAD_CLEANUP_TIMEOUT_S

            async def bounded_call(call):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    cleanup["deadline_exhausted"] = True
                    raise TimeoutError("download cleanup budget exhausted")
                try:
                    return await asyncio.wait_for(call(), timeout=remaining)
                except TimeoutError:
                    cleanup["deadline_exhausted"] = True
                    raise

            if self._download_click_active and self._download_mouse_held:
                try:
                    await bounded_call(self.page.mouse.up)
                    self._download_mouse_held = False
                    self.bundle.click(self.x, self.y, pressed=False)
                    cleanup["owned_mouse_release"] = "released"
                    cleanup["mouse_release_ts"] = time.time()
                    try:
                        await bounded_call(lambda: self._overlay(
                            "window.__hfcursor && window.__hfcursor.release()"))
                        cleanup["overlay_release"] = "attempted"
                    except (Exception, asyncio.CancelledError) as exc:                    # noqa: BLE001
                        cleanup.update(overlay_release="failed", overlay_error_type=type(exc).__name__)
                        receipt["status"] = "failed"
                        self.failures.append(f"download {step['id']}: overlay_release_failed")
                except (Exception, asyncio.CancelledError) as exc:                        # noqa: BLE001
                    cleanup.update(owned_mouse_release="failed", mouse_error_type=type(exc).__name__)
                    receipt["status"] = "failed"
                    self.failures.append(f"download {step['id']}: owned_mouse_release_failed")
            self._download_click_active = False
            if self._download_press_receipt is not None and not self._download_press_receipt["acknowledged"]:
                receipt["input_click_index"] = None
            self._download_press_receipt = None
            if listening:
                self.page.remove_listener("download", observe)
                listening = False
            try:
                check_owner()
            except (OSError, DownloadCaptureError) as exc:
                cleanup["path_binding_valid"] = False
                receipt["status"] = "failed"
                receipt.setdefault("error", {"phase": "cleanup", "type": type(exc).__name__,
                                             "code": "download_path_identity_changed"})
                self.failures.append(f"download {step['id']}: download_path_identity_changed")
            if temporary is not None:
                try:
                    unlink_owned(temporary)
                except (OSError, DownloadCaptureError) as exc:
                    cleanup.update(temporary_removed=False, error_type=type(exc).__name__)
                    receipt["status"] = "failed"
                    receipt["error"] = {"phase": "cleanup", "type": type(exc).__name__,
                                        "code": "temporary_cleanup_failed"}
                    self.failures.append(f"download {step['id']}: temporary_cleanup_failed")
            if receipt["status"] != "retained":
                if committed:
                    try:
                        unlink_owned(step["filename"])
                        cleanup["committed_file_removed"] = True
                    except (OSError, DownloadCaptureError) as exc:
                        cleanup.update(committed_file_removed=False,
                                       committed_file_error_type=type(exc).__name__)
                receipt["artifact"] = None
                for index, (item, _) in enumerate(observed):
                    if asyncio.get_running_loop().time() >= deadline:
                        cleanup.update(deadline_exhausted=True,
                                       downloads_cancel_skipped=len(observed) - index)
                        break
                    cleanup["cancel_requested"] = True
                    try:
                        await bounded_call(item.cancel)
                    except (Exception, asyncio.CancelledError) as exc:                    # noqa: BLE001
                        cleanup["cancel_error_type"] = type(exc).__name__
            receipt.update(completed_ts=time.time(), observed_downloads=len(observed),
                           observed_event_ts=[ts for _, ts in observed],
                           additional_downloads_retained=False, cleanup=cleanup)

        try:
            try:
                await asyncio.wait_for(perform(), timeout=step["timeout"])
                receipt["status"] = "retained"
            except asyncio.CancelledError:
                cancelled = True
                receipt["error"] = {"phase": phase, "type": "CancelledError",
                                    "code": "download_action_cancelled"}
                self.failures.append(f"download {step['id']}: download_action_cancelled")
            except Exception as exc:                                # noqa: BLE001
                receipt["error"] = {"phase": phase, "type": type(exc).__name__,
                                    "code": str(exc) if isinstance(exc, DownloadCaptureError)
                                    else "download_action_failed"}
                self.failures.append(f"download {step['id']}: {receipt['error']['code']}")
            # Outer cancellation must not detach cleanup or interrupt its bounded owner calls.
            cleanup_task = asyncio.create_task(cleanup_resources())
            while True:
                try:
                    await asyncio.shield(cleanup_task)
                    break
                except asyncio.CancelledError:
                    cancelled = True
                    receipt["status"] = "failed"
                    receipt["cancellation_requested"] = True
                    receipt.setdefault("error", {"phase": "cleanup", "type": "CancelledError",
                                                 "code": "download_action_cancelled"})
                    if cleanup_task.done() and cleanup_task.cancelled():
                        cleanup["error_type"] = "CancelledError"
                        break
                except Exception as exc:
                    receipt["status"] = "failed"
                    cleanup["error_type"] = type(exc).__name__
                    receipt.setdefault("error", {"phase": "cleanup", "type": type(exc).__name__,
                                                 "code": "download_cleanup_failed"})
                    break
            # Cancellation may arrive just as cleanup finishes. Reconcile only owned inodes before
            # retaining the final failure, even when the earlier cleanup saw a successful action.
            if receipt["status"] != "retained":
                for name in ([temporary] if temporary else []) + ([step["filename"]] if committed else []):
                    try:
                        unlink_owned(name)
                    except (OSError, DownloadCaptureError) as exc:
                        cleanup["final_unlink_error_type"] = type(exc).__name__
                receipt["artifact"] = None
            receipt.update(completed_ts=time.time(), cleanup=cleanup)
            try:
                self.bundle.download_receipt(receipt)
            except Exception as exc:
                if committed:
                    unlink_owned(step["filename"])
                if cancelled:
                    raise asyncio.CancelledError from exc
                raise
            if cancelled:
                raise asyncio.CancelledError
            return receipt["status"] == "retained"
        finally:
            self._download_click_active = False
            self._download_press_receipt = None
            try:
                if listening:
                    self.page.remove_listener("download", observe)
            finally:
                if directory_fd is not None:
                    os.close(directory_fd)

    async def _upload(self, step: dict) -> bool:
        problems = _upload_problems(step)
        if problems:
            self.failures.extend(problems)
            return False
        token = uuid.uuid4().hex
        receipt = {"schema_version": "webrec-upload/v1", "step_id": step["id"],
                   "step_sha256": hashlib.sha256(json.dumps(step, sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(),
                   "seed": step["seed"], "status": "failed", "started_ts": time.time(),
                   "selection": "verified_opfs_file_to_input_change", "seed_phase": "off_camera",
                   "supply_phase": "recorded", "product_verified": False, "app_result": "unknown",
                   "cleanup": "not_started", "error": None}
        cancelled = None
        prepared = False

        async def perform():
            nonlocal prepared
            if self.bundle._uploads is None:
                raise ValueError("upload_recording_not_enabled")
            if (type(self.bundle.t0) not in (int, float) or not math.isfinite(self.bundle.t0)
                    or not 0 < self.bundle.t0 <= receipt["started_ts"]):
                raise ValueError("upload_recording_clock_missing")
            if self.upload_seeds.count(step["seed"]) != 1:
                raise ValueError("upload_seed_not_admitted")
            locator = self.page.locator(step["selector"])
            await locator.wait_for(state="attached", timeout=step["timeout"] * 1000)
            if await locator.count() != 1:
                raise ValueError("upload_target_not_unique")
            prepared = True
            facts = await self.page.evaluate(PREPARE_UPLOAD_JS, {
                "token": token, "name": step["seed"], "expected_bytes": step["expected_bytes"],
                "expected_sha256": step["expected_sha256"], "max_bytes": step["max_bytes"],
                "deadline_ms": (receipt["started_ts"] + step["timeout"]) * 1000})
            expected = dict(name=step["seed"], bytes=step["expected_bytes"], sha256=step["expected_sha256"])
            if facts != expected:
                raise ValueError("upload_seed_verification_failed")
            receipt["verified"] = facts
            receipt["dispatch_requested_ts"] = time.time()
            # Locator.evaluate is strict; a changed/ambiguous selector is not silently .first.
            supplied = await locator.evaluate(DISPATCH_UPLOAD_JS, {"token": token},
                                               timeout=step["timeout"] * 1000)
            acknowledged = time.time()
            if (not isinstance(supplied, dict) or any(supplied.get(k) != v for k, v in expected.items())
                    or supplied.get("events") != ["input", "change"] or supplied.get("app_result") != "unknown"
                    or type(supplied.get("event_ts")) not in (int, float)
                    or not math.isfinite(supplied["event_ts"])
                    or not receipt["dispatch_requested_ts"] - .001 <= supplied["event_ts"] <= acknowledged):
                raise ValueError("upload_supply_not_acknowledged")
            receipt.update(status="supplied", supplied=supplied, acknowledged_ts=acknowledged,
                           video_t=acknowledged - self.bundle.t0,
                           video_time_rule="video_t = acknowledged_ts - t0_wallclock")
        try:
            await asyncio.wait_for(perform(), timeout=step["timeout"])
        except asyncio.CancelledError as exc:
            cancelled = exc
            receipt["error"] = "upload_action_cancelled"
        except Exception as exc:
            # Never retain signed URLs/browser error text in an upload journal.
            code = str(exc) if type(exc) is ValueError and re.fullmatch(r"upload_[a-z_]+", str(exc)) else "upload_action_failed"
            receipt["error"] = "upload_action_timeout" if isinstance(exc, asyncio.TimeoutError) else code
        finally:
            if prepared:
                try:
                    cleared = await asyncio.wait_for(self.page.evaluate(CLEANUP_UPLOAD_JS, token), timeout=2.0)
                    if cleared is not True:
                        raise ValueError("upload_cleanup_unacknowledged")
                    receipt["cleanup"] = "released"
                except (Exception, asyncio.CancelledError) as exc:
                    receipt["cleanup"] = "failed"
                    receipt["error"] = receipt["error"] or "upload_cleanup_failed"
                    if isinstance(exc, asyncio.CancelledError):
                        cancelled = exc
            else:
                receipt["cleanup"] = "not_needed"
            receipt["completed_ts"] = time.time()
            if receipt["error"]:
                receipt["status"] = "failed"
                self.failures.append(f"upload {step['id']}: {receipt['error']}")
            try:
                self.bundle.upload_receipt(receipt)
            except Exception:
                self.failures.append(f"upload {step['id']}: upload_receipt_persist_failed")
                receipt["status"] = "failed"
            if cancelled is not None:
                raise cancelled
        return receipt["status"] == "supplied"

    async def run_step(self, step: dict) -> bool:
        kind = step["do"]
        timeout_s = float(step.get("timeout", 15))
        # ``say`` is narration, so it is *recorded* whether or not it is also drawn. Burning it
        # into the frame is now opt-in: burned text cannot be re-timed against a real voice, and
        # it survives a 9:16 reframe as a crop of itself.
        if line := step.get("say"):
            self.bundle.beat(step.get("beat") or "", vo=line, explain=step.get("explain") or "",
                             lang=step.get("lang") or self.lang)
            if self.burn_captions:
                await self._overlay(
                    f"window.__hfcursor && window.__hfcursor.caption({json.dumps(line)}, 2400)")

        if kind == "download":
            return await self._download(step)
        if kind == "upload":
            return await self._upload(step)

        if kind == "assert":
            from playwright.async_api import expect
            receipt = {"selector": step["selector"], "expected_text": step["text"],
                       "dt": round(time.time() - (self.bundle.t0 or time.time()), 3),
                       "status": "failed", "visual_verification": "not_performed"}
            try:
                locator = self.page.locator(step["selector"])
                await expect(locator).to_have_count(1, timeout=timeout_s * 1000)
                await expect(locator).to_be_visible(timeout=timeout_s * 1000)
                await expect(locator).to_have_text(step["text"], timeout=timeout_s * 1000)
                await locator.scroll_into_view_if_needed(timeout=timeout_s * 1000)
                data = await self.page.screenshot(full_page=False)
                # Keep proof with this take; never overwrite another assertion or
                # follow a symlink planted at the requested screenshot name.
                with (self.bundle.dir / step["screenshot"]).open("xb") as output:
                    output.write(data)
                receipt.update(status="passed", screenshot=step["screenshot"],
                               sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
                self.bundle.assertions.append(receipt)
                self.log("assert · exact DOM text passed; screenshot retained")
                return True
            except (AssertionError, OSError):
                self.bundle.assertions.append(receipt)
                self.failures.append("assertion_failed")
                self.log("assert · failed")
                return False

        if kind == "beat":
            self.bundle.beat(step.get("id") or "", vo=step.get("vo") or "",
                             explain=step.get("explain") or "", show=step.get("show") or "",
                             lang=step.get("lang") or self.lang)
            self.log(f"beat · {(step.get('vo') or step.get('explain') or '')[:60]}")
            return True

        if kind == "goto":
            await self.page.goto(step["url"], wait_until=step.get("until", "load"),
                                 timeout=timeout_s * 1000)
            self.bundle.chapter(step.get("title") or step["url"])
            return True

        if kind == "wait":
            await asyncio.sleep(float(step.get("s", 1.0)))
            return True

        if kind == "chapter":
            self.bundle.chapter(step["title"])
            self.log(f"chapter · {step['title']}")
            return True

        if kind == "caption":
            await self._overlay(
                f"window.__hfcursor && window.__hfcursor.caption({json.dumps(step.get('text', ''))},"
                f" {int(float(step.get('s', 2.5)) * 1000)})")
            return True

        if kind == "wait_for":
            try:
                await self.page.locator(step["selector"]).first.wait_for(
                    state="visible", timeout=timeout_s * 1000)
                return True
            except Exception as exc:                            # noqa: BLE001
                self.failures.append(f"wait_for {step['selector']!r}: {type(exc).__name__}")
                return False

        if kind in {"click", "dblclick", "hover"}:
            # A timeline, a canvas and a waveform have no element to name. `at` is the escape
            # hatch for those surfaces, in viewport pixels, and it is deliberately clumsier than
            # a selector so it stays the exception rather than the habit.
            if at := step.get("at"):
                point = (float(at["x"]), float(at["y"]))
            else:
                point = await self._locate(step["selector"], timeout_s)
            if point is None:
                return False
            await self.glide_to(*point)
            if kind != "hover":
                await self.press_release(double=(kind == "dblclick"))
            await asyncio.sleep(float(step.get("settle", SETTLE_S)))
            self.log(f"{kind} · {step.get('selector') or step.get('at')}")
            return True

        if kind == "drag":
            start = await self._locate(step["selector"], timeout_s)
            if start is not None and step.get("from_at"):
                start = (float(step["from_at"]["x"]), float(step["from_at"]["y"]))
            # A timeline track has no element to name — same hole "at" fills for click.
            end = ((float(step["to_at"]["x"]), float(step["to_at"]["y"])) if step.get("to_at")
                   else await self._locate(step["to"], timeout_s))
            if start is None or end is None:
                return False
            await self.glide_to(*start)
            await self._overlay("window.__hfcursor && window.__hfcursor.press()")
            ok = await self._drag(start, end)
            await self._overlay("window.__hfcursor && window.__hfcursor.release()")
            await asyncio.sleep(float(step.get("settle", 0.8)))
            self.log(f"drag · {step['selector']} -> {step.get('to') or step['to_at']}"
                     f"{'' if ok else '  (no drag interception — plain mouse used; confirm the drop landed)'}")
            return True

        if kind == "type":
            if step.get("selector"):
                point = await self._locate(step["selector"], timeout_s)
                if point is None:
                    return False
                await self.glide_to(*point)
                await self.press_release()
                await asyncio.sleep(0.15)
            text = str(step["text"])
            show = step.get("show", True)
            if step.get("paste"):
                # A field the app re-reads on every keystroke sees a *prefix* of the value on all
                # but the last one. Measured on FreeCut's block source field: typing
                # "/icons/icon-512.png" made it try to decode "/icons/icon-512.pn", fail, and keep
                # showing that failure — the finished value never got a second look. `fill` sets
                # the whole string and fires one input event, which is also what a URL wants:
                # nobody needs to watch a path being typed.
                if not step.get("selector"):
                    self.failures.append("type --paste needs a selector")
                    return False
                await self.page.locator(step["selector"]).first.fill(text)
                self.bundle.key(text[:48], "press")
                self.bundle.key(text[:48], "release")
                await asyncio.sleep(float(step.get("settle", 0.4)))
            else:
                for char in text:
                    await self.page.keyboard.type(char)
                    self.bundle.key(char, "press")
                    self.bundle.key(char, "release")
                    await asyncio.sleep(float(step.get("delay", TYPE_DELAY_S)))
            if show:
                await self._overlay(
                    f"window.__hfcursor && window.__hfcursor.key({json.dumps(text[:48])})")
            self.log(f"type · {len(text)} chars{' (pasted)' if step.get('paste') else ''}")
            return True

        if kind == "key":
            await self.page.keyboard.press(step["key"])
            self.bundle.key(step["key"], "press")
            self.bundle.key(step["key"], "release")
            await self._overlay(
                f"window.__hfcursor && window.__hfcursor.key({json.dumps(step['key'])})")
            await asyncio.sleep(float(step.get("settle", 0.3)))
            self.log(f"key · {step['key']}")
            return True

        if kind == "scroll":
            dy = float(step.get("dy", 400))
            if step.get("selector"):
                point = await self._locate(step["selector"], timeout_s)
                if point:
                    await self.glide_to(*point)
            # Several small wheel events, not one jump: a page that lazy-loads on scroll needs the
            # intermediate positions, and a single 1200px jump is unwatchable anyway.
            chunks = max(int(abs(dy) / 120), 1)
            for _ in range(chunks):
                await self.page.mouse.wheel(0, dy / chunks)
                self.bundle.scroll(self.x, self.y, 0, dy / chunks)
                await asyncio.sleep(0.045)
            await asyncio.sleep(float(step.get("settle", 0.4)))
            self.log(f"scroll · {dy:+.0f}px")
            return True

        self.failures.append(f"unknown step kind {kind!r}")
        return False


# ---------------------------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------------------------
def auth_state_path(name: str) -> Path:
    return AUTH_STATES / f"{_slug(name)}.json"


def _secure_dir(path: Path) -> Path:
    """0700, always. These directories hold live sessions for the operator's real accounts."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:                                             # pragma: no cover - odd filesystem
        pass
    return path


def cmd_auth_list(_: argparse.Namespace) -> int:
    _secure_dir(AUTH_STATES)
    _secure_dir(AUTH_PROFILES)
    states = sorted(AUTH_STATES.glob("*.json"))
    profiles = sorted(d for d in AUTH_PROFILES.iterdir() if d.is_dir())
    print(f"sessions ({AUTH_STATES}):")
    now = time.time()
    for state in states:
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
        except Exception:                                       # noqa: BLE001
            print(f"  {state.stem:<24} unreadable")
            continue
        cookies = data.get("cookies") or []
        # The number that matters is not "does the file exist" but "will it still log in
        # tomorrow". A session that expires mid-shoot looks exactly like a broken selector.
        expiries = [c["expires"] for c in cookies
                    if isinstance(c.get("expires"), (int, float)) and c["expires"] > 0]
        soonest = min(expiries) if expiries else None
        when = ("session-only" if soonest is None else
                f"expires in {max(soonest - now, 0) / 86400:.1f}d")
        hosts = sorted({c.get("domain", "").lstrip(".") for c in cookies})[:3]
        print(f"  {state.stem:<24} {len(cookies):>3} cookies · {when} · {', '.join(hosts)}")
    if not states:
        print("  (none)")
    print(f"profiles ({AUTH_PROFILES}):")
    for profile in profiles:
        print(f"  {profile.name:<24} {sum(f.stat().st_size for f in profile.rglob('*') if f.is_file()) / 1e6:.0f} MB")
    if not profiles:
        print("  (none)")
    return 0


async def cmd_auth_grab(args: argparse.Namespace) -> int:
    """Copy a signed-in session out of a browser that is already logged in.

    The fleet already keeps signed-in Chrome seats on CDP ports — that is where the operator's
    real accounts live. This reads their cookies and writes a session webrec can wear. It reads;
    it does not navigate, click, open or close anything in that seat: those windows are the
    operator's, and a recorder that reaches into them to "just check something" is the reason
    nobody trusts automation near a real account.
    """
    from playwright.async_api import async_playwright

    _secure_dir(AUTH_STATES)
    out = auth_state_path(args.name)
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{args.cdp}", timeout=15_000)
        except Exception as exc:                                # noqa: BLE001
            print(f"could not attach to a browser on port {args.cdp}: {type(exc).__name__}")
            print("  is the seat up?  curl -s http://localhost:%s/json/version" % args.cdp)
            return 3
        contexts = browser.contexts
        if not contexts:
            print(f"port {args.cdp} has a browser but no open context to read a session from")
            await browser.close()
            return 3
        cookies: list[dict] = []
        for context in contexts:
            cookies.extend(await context.cookies())
        origins: list[dict] = []
        if args.include_local_storage:
            # Only from tabs that are ALREADY open — no navigation, so the seat is left as found.
            for context in contexts:
                for page in context.pages:
                    try:
                        origin = await page.evaluate("location.origin")
                        items = await page.evaluate(
                            "Object.entries(localStorage).map(([name, value]) => ({name, value}))")
                    except Exception:                           # noqa: BLE001
                        continue
                    if origin and items and not any(o["origin"] == origin for o in origins):
                        origins.append({"origin": origin, "localStorage": items})
        await browser.close()

    if args.domain:
        keep = [d.lower().lstrip(".") for d in args.domain]
        cookies = [c for c in cookies
                   if any(c.get("domain", "").lstrip(".").endswith(d) for d in keep)]
    if args.dry:
        # Look before you copy. A seat can hold sessions for a dozen accounts, and a session file
        # should carry the one this demo needs — not the operator's whole browsing life.
        by_host: dict[str, int] = {}
        for cookie in cookies:
            host = cookie.get("domain", "").lstrip(".")
            by_host[host] = by_host.get(host, 0) + 1
        print(f"port {args.cdp} holds {len(cookies)} cookie(s) across {len(by_host)} host(s). "
              f"Nothing written.")
        for host, count in sorted(by_host.items(), key=lambda kv: -kv[1])[:25]:
            print(f"  {count:>4}  {host}")
        print("  narrow it:  --domain <host>  (repeatable), then drop --dry")
        return 0

    if not cookies:
        print("no cookies matched — nothing saved (a session file with no cookies is a trap: "
              "it makes a signed-out run look configured)")
        return 1

    seen: set[tuple] = set()
    unique = []
    for cookie in cookies:
        key = (cookie.get("name"), cookie.get("domain"), cookie.get("path"))
        if key not in seen:
            seen.add(key)
            unique.append(cookie)

    out.write_text(json.dumps({"cookies": unique, "origins": origins}, indent=2), encoding="utf-8")
    out.chmod(0o600)
    hosts = sorted({c.get("domain", "").lstrip(".") for c in unique})
    print(f"saved · {len(unique)} cookies"
          f"{f' + localStorage for {len(origins)} origin(s)' if origins else ''} → {out}")
    print(f"  hosts : {', '.join(hosts[:8])}{' …' if len(hosts) > 8 else ''}")
    print(f'  use it: "stage": {{ "auth": "{_slug(args.name)}" }}')
    return 0


async def cmd_auth_login(args: argparse.Namespace) -> int:
    """Open a real browser on a named profile and hold it while a human signs in.

    A profile beats a copied cookie jar: it survives token refreshes, device checks and the
    "is this you?" mail, because from the site's side it *is* one browser used repeatedly. This
    box has no display, so the browser is opened with a debug port and the operator drives it
    from wherever they already drive the rest of the estate.
    """
    from playwright.async_api import async_playwright

    directory = _secure_dir(AUTH_PROFILES / _slug(args.name))
    print(f"profile   : {directory}")
    print(f"debug port: {args.port}  →  attach with your own CDP tooling, or tunnel it:")
    print(f"            ssh -N -L {args.port}:127.0.0.1:{args.port} user@your-host")
    print(f"            then open  http://localhost:{args.port}  in a local Chrome")
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(directory),
            headless=args.headless,
            executable_path="/usr/bin/google-chrome" if Path("/usr/bin/google-chrome").exists() else None,
            # Same software-GL flags a take uses. Without them an app with a WebGL background
            # fails to boot here, and a sign-in that never reached the app looks like a sign-in
            # that failed.
            args=[f"--remote-debugging-port={args.port}", "--remote-allow-origins=*",
                  "--no-first-run", "--no-default-browser-check",
                  "--use-gl=angle", "--use-angle=swiftshader", "--ignore-gpu-blocklist",
                  "--enable-unsafe-swiftshader"],
            viewport={"width": args.width, "height": args.height},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        if args.url:
            await page.goto(args.url, wait_until="load", timeout=60_000)
        if args.setup_from:
            # A scripted sign-in, for an app whose credentials the operator is willing to put in a
            # file or an env var. It runs ONCE, here, into the profile — never inside a take, so a
            # password is never on camera and never in a recorded input log.
            script = json.loads(Path(args.setup_from).read_text(encoding="utf-8"))
            if not args.url and script.get("url"):
                await page.goto(script["url"], wait_until="load", timeout=60_000)
            await dismiss_blockers(page, list((script.get("stage") or {}).get("dismiss") or []))
            problems = await run_setup(page, script.get("setup") or [], verbose=True)
            for problem in problems:
                print(f"  ! {problem}")
            await asyncio.sleep(2)
        else:
            print(f"holding the browser open for {args.minutes} minute(s). Sign in, then Ctrl-C.")
            try:
                await asyncio.sleep(args.minutes * 60)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
        cookies = await context.cookies()
        await context.close()
    print(f"closed · profile now holds {len(cookies)} cookie(s)")
    print(f'  use it: "stage": {{ "profile": "{_slug(args.name)}" }}')
    return 0


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "take"


async def _shutdown(browser: Any, context: Any) -> None:
    """A persistent profile has no browser object — closing its context is what closes Chrome."""
    try:
        if browser is not None:
            await browser.close()
        else:
            await context.close()
    except Exception:                                           # noqa: BLE001
        pass


async def _browser(playwright: Any, script: dict, headed: bool):
    """Launch Chrome already wearing whatever the target app needs to be usable.

    This is the ``stage`` half of a demo script, and it is the half that decides whether there is
    anything to film. freecut is the worked example: headless Chrome has no folder dialog, so the
    workspace gate is a dead end until ``showDirectoryPicker`` hands back OPFS — which is a *real*
    ``FileSystemDirectoryHandle``, so the workspace and media library still run their true code
    paths. That recipe is the repo's own (``freecut/src/features/particles/proof.mjs``), not a
    stub invented here.
    """
    width = int(script.get("viewport", {}).get("width", 1920))
    height = int(script.get("viewport", {}).get("height", 1080))
    stage = script.get("stage") or {}
    args = ["--hide-scrollbars", "--force-color-profile=srgb", "--font-render-hinting=none",
            "--disable-gpu-vsync", f"--window-size={width},{height}"]
    # Software GL by default: this box has no GPU, and an app whose canvas silently fails to
    # composite records as a black rectangle nobody notices until they watch the take.
    args += list(stage.get("chrome_args") or ["--use-gl=angle", "--use-angle=swiftshader",
                                              "--ignore-gpu-blocklist",
                                              "--enable-unsafe-swiftshader"])
    # Same trap one layer up. Software GL covers WebGL; WebGPU is a separate stack, and without
    # this flag ``requestAdapter()`` resolves to null on a GPU-less box — so a WebGPU compositor
    # (freecut's preview is one) comes up black while every element and assert still passes.
    if not any(a.startswith("--enable-unsafe-webgpu") for a in args):
        args.append("--enable-unsafe-webgpu")
    launch: dict[str, Any] = {"headless": not headed, "args": args}
    if executable := browser_executable():
        launch["executable_path"] = str(executable)
    common = {
        "viewport": {"width": width, "height": height},
        "device_scale_factor": 1,              # frames must match the coordinates plan.py normalises
        "locale": script.get("locale", "en-US"),
        "reduced_motion": "no-preference",
    }

    # Three ways to arrive already signed in, strongest first. A profile is a whole browser the
    # operator logged into once and never thinks about again; a saved state is a snapshot of
    # cookies that will eventually expire; neither is the signed-out demo that hits a wall.
    if profile := stage.get("profile"):
        directory = AUTH_PROFILES / profile
        if not directory.exists():
            raise SystemExit(
                f"no browser profile named {profile!r} at {directory}.\n"
                f"  create it once:  python webrec.py auth login {profile} --url <the app>")
        context = await playwright.chromium.launch_persistent_context(
            str(directory), **launch, **common)
        browser = None
    else:
        browser = await playwright.chromium.launch(**launch)
        state: str | None = None
        if name := stage.get("auth"):
            state = str(auth_state_path(name))
            if not Path(state).exists():
                raise SystemExit(
                    f"no saved session named {name!r} at {state}.\n"
                    f"  capture one:  python webrec.py auth grab {name} --cdp <port>")
        elif stage.get("storage_state"):
            state = stage["storage_state"]
        context = await browser.new_context(storage_state=state, **common)
    if stage.get("permissions"):
        await context.grant_permissions(list(stage["permissions"]))
    if seeds := stage.get("seed_files"):
        names = [seed.get("as") or Path(seed["path"]).name for seed in seeds]
        await context.add_init_script(SEED_PICKER_JS.replace("__NAMES__", json.dumps(names)))
    for snippet in stage.get("init_scripts") or []:
        await context.add_init_script(snippet)
    await context.add_init_script(OVERLAY_JS)
    return browser, context, width, height


async def run_setup(page: Any, steps: list[dict], verbose: bool = True,
                    opened: set[str] | None = None) -> list[str]:
    """Walk the app to the state worth filming — off camera, at machine speed.

    Every app has a foyer: a workspace gate, a login, an empty-project screen. Filming it is how
    you get a demo whose first eight seconds are a folder dialog. So the setup steps run before the
    screencast starts, with no cursor and no glide, and the recording opens on the part that
    actually shows the product.

    ``opened``, when given, is filled with the dialogs the **last** step produced. The walk usually
    ends by putting the app somewhere on purpose — "New composition", "Add layer", "Export" — and
    the blocker sweep that runs next has a close button to press on every one of them. Differencing
    the open dialogs across that final step is what tells the sweep which one it must not touch.
    """
    problems: list[str] = []
    before_last: set[str] = set()
    # A trailing `wait` is punctuation, not an action: the step that *did* something is the last one
    # that is not a wait. Snapshotting after the wait would compare the dialog with itself and
    # protect nothing, which is exactly how this was wrong the first time.
    acted = max((i for i, st in enumerate(steps) if st.get("do") != "wait"), default=-1)
    for i, step in enumerate(steps):
        if opened is not None and i == acted:
            before_last = await open_dialogs(page)
        kind = step.get("do")
        timeout = float(step.get("timeout", 30)) * 1000
        try:
            if kind == "goto":
                await page.goto(step["url"], wait_until=step.get("until", "load"), timeout=timeout)
            elif kind == "wait":
                await asyncio.sleep(float(step.get("s", 1.0)))
            elif kind == "wait_for":
                await page.locator(step["selector"]).first.wait_for(state="visible", timeout=timeout)
            elif kind in {"click", "dblclick"}:
                # A timeline, a canvas and a waveform have no element to name. The filmed steps
                # already carry `at` as the escape hatch for those surfaces; setup needs the same
                # one, or a state you can film is a state you cannot stage.
                if at := step.get("at"):
                    await page.mouse.click(float(at["x"]), float(at["y"]),
                                           click_count=2 if kind == "dblclick" else 1)
                else:
                    target = page.locator(step["selector"]).first
                    await target.wait_for(state="visible", timeout=timeout)
                    await (target.dblclick() if kind == "dblclick" else target.click())
            elif kind == "drag":
                # Setup is off camera, so this is the plain-mouse drag with no cursor overlay —
                # enough to stage a timeline before the take opens on it.
                start = page.locator(step["selector"]).first
                await start.wait_for(state="visible", timeout=timeout)
                box_a = await start.bounding_box()
                if step.get("to_at"):
                    box_b = None
                    bx, by = float(step["to_at"]["x"]), float(step["to_at"]["y"])
                else:
                    end = page.locator(step["to"]).first
                    await end.wait_for(state="visible", timeout=timeout)
                    box_b = await end.bounding_box()
                    if box_b:
                        bx = box_b["x"] + box_b["width"] / 2
                        by = box_b["y"] + box_b["height"] / 2
                if not box_a or (box_b is None and not step.get("to_at")):
                    problems.append(f"setup step {i} (drag): no box for source or target")
                    continue
                ax, ay = box_a["x"] + box_a["width"] / 2, box_a["y"] + box_a["height"] / 2
                await page.mouse.move(ax, ay)
                await page.mouse.down()
                for stepno in range(1, 26):                    # HTML5 dnd needs real intermediate moves
                    await page.mouse.move(ax + (bx - ax) * stepno / 25,
                                          ay + (by - ay) * stepno / 25)
                    await asyncio.sleep(0.02)
                await page.mouse.up()
                await asyncio.sleep(float(step.get("settle", 1.5)))
            elif kind == "type":
                await page.locator(step["selector"]).first.fill(str(step["text"]), timeout=timeout)
            elif kind == "key":
                await page.keyboard.press(step["key"])
            elif kind == "eval":
                await page.evaluate(step["js"])
            else:
                problems.append(f"setup step {i}: unknown kind {kind!r}")
                continue
            if verbose:
                print(f"    setup · {kind} {step.get('selector') or step.get('at') or step.get('url') or ''}"[:110],
                      flush=True)
        except Exception as exc:                                # noqa: BLE001
            problems.append(f"setup step {i} ({kind} {step.get('selector', '')}): "
                            f"{type(exc).__name__}")
            if not step.get("optional"):
                break
    if opened is not None:
        opened |= await open_dialogs(page) - before_last

    return problems


def session_label(stage: dict, cdp_port: int = 0) -> str | None:
    """Name the session a take used — never the session itself.

    The manifest travels inside the bundle, and bundles get published. So this returns a pointer:
    which window, or which 0600 file outside the repo. Cookie values never come near it.
    """
    if cdp_port:
        return f"attached:cdp-{cdp_port}"
    if profile := (stage or {}).get("profile"):
        return f"profile:{profile}"
    if name := (stage or {}).get("auth"):
        return f"session:{name}"
    return None


async def cmd_rec(args: argparse.Namespace) -> int:
    script_bytes = Path(args.script).read_bytes()
    script = json.loads(script_bytes)
    problems = validate_script(script)
    if problems:
        print("script will not record — fix these first:")
        for problem in problems:
            print(f"  ! {problem}")
        return 2

    from playwright.async_api import async_playwright

    name = script.get("name") or Path(args.script).stem
    out_root = Path(args.out_dir) if args.out_dir else DEFAULT_OUT
    session_dir = out_root / f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(name)}"
    record_downloads = any(step.get("do") == "download" for step in script["steps"])
    upload_steps = [step for step in script["steps"] if step.get("do") == "upload"]
    bundle = Bundle(session_dir, redact_keys=not args.raw_keys, record_downloads=record_downloads,
                    record_uploads=bool(upload_steps))
    frames_dir = session_dir / "_frames"

    print(f"webrec · {name}")
    print(f"  target  : {script['url']}")
    print(f"  bundle  : {session_dir}")

    async with async_playwright() as playwright:
        attached = bool(args.cdp)
        if attached:
            # The strongest answer to a login wall is not to copy a session but to record the
            # browser that already has one. Nothing is copied, nothing expires, and no provider
            # sees a new device. The cost is that this window belongs to whoever opened it: the
            # port is never guessed, the browser is never closed, and the viewport is whatever
            # size that window already is.
            browser = await playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{args.cdp}", timeout=20_000)
            if not browser.contexts:
                print(f"port {args.cdp} has a browser but no context to record")
                if upload_steps:
                    bundle.close()
                return 3
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
            await context.add_init_script(OVERLAY_JS)           # for anything it navigates to
            size = await page.evaluate("({w: window.innerWidth, h: window.innerHeight})")
            width, height = int(size["w"]), int(size["h"])
            print(f"  attached: port {args.cdp} · {width}x{height} · this window will NOT be closed")
        else:
            browser, context, width, height = await _browser(playwright, script, args.headed)
            page = await context.new_page()
        cdp = await context.new_cdp_session(page)

        # A route change is this lane's "foreground app changed" — the same signal, and the same
        # chapter boundary plan.py builds title cards from.
        page.on("framenavigated", lambda frame: (
            bundle.chapter(frame.url) if frame is page.main_frame and bundle.t0 else None))

        console_errors: list[str] = []
        def _page_error(exc) -> str:
            """Record the error *and* where it came from.

            `webrec-overlay.js` in the stack means the recorder broke, not the app — a distinction
            the gate has to make without a human re-running the take to find out.
            """
            stack = (getattr(exc, "stack", "") or "").splitlines()
            frame = next((ln.strip() for ln in stack[1:] if ln.strip().startswith("at ")), "")
            mine = next((ln.strip() for ln in stack if "webrec-overlay.js" in ln), "")
            source = mine.removeprefix("at ")[:70] if mine else frame[:70]
            return f"pageerror: {str(exc)[:160]}" + (f" [{source}]" if source else "")

        page.on("pageerror", lambda exc: console_errors.append(_page_error(exc)))
        page.on("console", lambda msg: console_errors.append(f"console: {msg.text[:160]}")
                if msg.type == "error" else None)

        await page.goto(script["url"], wait_until=script.get("until", "load"),
                        timeout=float(script.get("timeout", 45)) * 1000)

        if attached:
            # add_init_script only fires on the NEXT document; this one is already open.
            await page.evaluate(OVERLAY_JS)

        blockers = list((script.get("stage") or {}).get("dismiss") or [])
        await dismiss_blockers(page, blockers, verbose=not args.quiet)

        seeds = (script.get("stage") or {}).get("seed_files") or []
        if attached and seeds:
            print("  ! ignoring stage.seed_files — this browser was not launched by webrec, so "
                  "its storage is the operator's, not ours to write into")
            seeds = []
        setup_problems = await seed_files(page, seeds, verbose=not args.quiet, upload_steps=upload_steps)
        if attached and upload_steps:
            setup_problems.append("recorded upload requires this recorder's seeded browser")
        script_opened: set[str] = set()
        setup_problems += await run_setup(page, script.get("setup") or [], verbose=not args.quiet,
                                          opened=script_opened)
        # Again after the walk: a sign-in wall is usually the *second* thing in the way, and an
        # onboarding tour only appears once you are inside. Whatever the walk's final step opened
        # is not furniture, though — see dismiss_blockers.
        await dismiss_blockers(page, blockers, verbose=not args.quiet, protect=script_opened)
        if setup_problems and not args.keep_going:
            print("  ! the app never reached a state worth filming:")
            for problem in setup_problems:
                print(f"    {problem}")
            print("  ! nothing recorded. Fix the setup walk, or pass --keep-going to film anyway.")
            await _shutdown(browser, context)
            if upload_steps:
                bundle.close()
            return 3

        if ready := script.get("ready_selector") or script.get("wait_for"):
            try:
                await page.locator(ready).first.wait_for(state="visible", timeout=60_000)
            except Exception as exc:                            # noqa: BLE001
                print(f"  ! app never reached its ready state ({ready!r}: {type(exc).__name__})")
                await _shutdown(browser, context)
                if upload_steps:
                    bundle.close()
                return 3
        await asyncio.sleep(float(script.get("settle_s", 1.2)))  # let fonts and first paint land

        screencast = Screencast(frames_dir)
        await screencast.start(cdp, width, height)
        if upload_steps:
            first_frame_ready = await wait_for_first_frame(screencast)
        else:
            await asyncio.sleep(0.4)
            first_frame_ready = bool(screencast.frames)
        if upload_steps and not first_frame_ready:
            # A fallback wall clock does not prove an upload was on camera.
            await screencast.stop()
            await _shutdown(browser, context)
            bundle.close()
            print("  ! no screencast frame before recorded upload; nothing supplied")
            return 3
        bundle.t0 = screencast.frames[0][0] if screencast.frames else time.time()
        bundle.chapter(script.get("opening_title") or name)

        director = Director(page, bundle, width, height, verbose=not args.quiet, cdp=cdp,
                            burn_captions=not args.no_burn_captions,
                            lang=script.get("lang") or "en", upload_seeds=seeds)
        await director._overlay(f"window.__hfcursor && window.__hfcursor.at({width / 2}, {height * 0.62})")

        ok_steps = 0
        for i, step in enumerate(script["steps"]):
            try:
                ok = await director.run_step(step)
            except Exception as exc:                            # noqa: BLE001
                director.failures.append(f"step {i} ({step.get('do')}): {type(exc).__name__}: {exc}")
                ok = False
            if ok:
                ok_steps += 1
            elif not args.keep_going:
                print(f"  ! step {i} ({step.get('do')}) failed — stopping. "
                      f"Pass --keep-going to record the rest anyway.")
                break

        await asyncio.sleep(float(script.get("tail_s", 1.0)))    # do not cut on the last click
        await screencast.stop()
        end_ts = time.time()
        if attached:
            await browser.close()          # detaches the CDP client; the window stays open
        else:
            await _shutdown(browser, context)

    encoded, detail = screencast.encode(session_dir / "screen.mp4", end_ts)
    duration = round(end_ts - (bundle.t0 or end_ts), 3)
    bundle.close()

    manifest = {
        "name": name,
        "session_id": session_dir.name,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "t0_wallclock": bundle.t0,
        # Frames and events are stamped by one process off one clock, so this is not the desktop
        # lane's negotiated estimate. plan.py reads the field; it should say what it means.
        "clock_source": "cdp-screencast (single-process, exact)",
        "duration_s": duration,
        "lang": script.get("lang") or "en",
        "source": {"kind": "web", "url": script["url"], "script": str(Path(args.script).resolve()),
                   "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
                   # WHICH session, never the session. The name is a pointer to a 0600 file
                   # outside the repo; the cookies never touch a bundle that gets published.
                   "signed_in_as": session_label(script.get("stage") or {}, args.cdp)},
        "screen": {"width": width, "height": height},
        "streams": {
            "screen": {"tool": "cdp+ffmpeg", "path": "screen.mp4" if encoded else None,
                       "status": "ok" if encoded else "failed",
                       "error": None if encoded else detail,
                       "frames": len(screencast.frames), "dropped": screencast.dropped},
            "input": {"tool": "webrec (humanflow schema)", "path": "input.jsonl", "status": "ok",
                      "keys": "raw" if args.raw_keys else "redacted", "counts": bundle.counts,
                      # Synthetic input is already a script: re-run the .json, do not replay a log.
                      "replayable": False, "replay_via": "the demo script itself"},
            "windows": {"tool": "webrec (route changes)", "path": "windows.jsonl", "status": "ok",
                        "changes": bundle.chapters},
            # What the take SAYS, kept out of the pixels so the cut can still re-time it, dub it
            # in another voice, or reframe it 9:16. ``burned`` tells the compositor whether the
            # frames already carry these words — putting them on twice is the obvious own goal.
            "beats": {"tool": "webrec (script beat marks)", "path": "beats.jsonl",
                      "status": "ok" if bundle.beats else "none", "count": bundle.beats,
                      "burned": not args.no_burn_captions},
            "webcam": {"tool": None, "path": None, "status": "off"},
        },
        "steps": {"total": len(script["steps"]), "ok": ok_steps,
                  "failures": director.failures, "setup_problems": setup_problems},
        # A take can be 8/8 green and still be a video of a broken app. The page's own errors are
        # the cheapest signal that what got filmed is not what should ship.
        "page_errors": console_errors[:25],
        "video_time_rule": "video_t = event.ts - t0_wallclock",
    }
    if bundle.assertions:
        manifest["assertions"] = bundle.assertions
    if record_downloads:
        manifest["streams"]["downloads"] = {
            "tool": "webrec (Playwright download events)", "path": "downloads.jsonl",
            "status": "ok" if len(bundle.downloads) == sum(
                step.get("do") == "download" for step in script["steps"])
                and all(item["status"] == "retained" for item in bundle.downloads) else "failed",
            "receipts": len(bundle.downloads), "product_verified": False, "qa_status": "not_run"}
    if upload_steps:
        manifest["streams"]["uploads"] = {
            "tool": "webrec (verified OPFS File to native input/change)", "path": "uploads.jsonl",
            "status": "ok" if len(bundle.uploads) == len(upload_steps)
                and all(row["status"] == "supplied" for row in bundle.uploads) else "failed",
            "receipts": len(bundle.uploads), "product_verified": False, "app_result": "unknown"}
    (session_dir / "session.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if not args.keep_frames and encoded:
        shutil.rmtree(frames_dir, ignore_errors=True)

    print(f"  done    : {duration:.1f}s · {ok_steps}/{len(script['steps'])} steps · "
          f"{bundle.counts['click']} clicks · {len(screencast.frames)} frames")
    print(f"  video   : {detail if encoded else 'NOT ENCODED — ' + detail}")
    for failure in director.failures + setup_problems:
        print(f"  ! {failure}")
    if console_errors:
        print(f"  ! the app logged {len(console_errors)} error(s) during the take — "
              f"first: {console_errors[0]}")
    print(f"  next    : python {Path(__file__).parent / 'plan.py'} {session_dir}")
    return 0 if (encoded and not director.failures) else 1


SEED_PICKER_JS = """
(() => {
  window.__hfSeedNames = __NAMES__;
  // The app asks the browser for files; headless Chrome has no dialog, so the picker is answered
  // from OPFS instead. These are real FileSystemFileHandles over real bytes, so import, probing,
  // thumbnailing and decode all run their true paths — the dialog is the only thing missing.
  const fromOpfs = async () => {
    const root = await navigator.storage.getDirectory();
    const out = [];
    for (const name of window.__hfSeedNames) {
      try { out.push(await root.getFileHandle(name)); } catch (e) { /* not seeded yet */ }
    }
    return out;
  };
  window.showOpenFilePicker = fromOpfs;
  window.__hfSeedPicker = fromOpfs;
})();
"""

WRITE_SEED_JS = """
async ({ name, data }) => {
  const binary = atob(data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const root = await navigator.storage.getDirectory();
  const handle = await root.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  await writable.write(bytes);
  await writable.close();
  return (await handle.getFile()).size;
}
"""


UPLOAD_SEED_CHUNK_BYTES = 1024 * 1024
UPLOAD_SEED_CLEANUP_S = 2.0

# Only opted-in recorded uploads use this transaction protocol. Each call moves
# at most one bounded chunk; Director still verifies the complete immutable File.
UPLOAD_SEED_STREAM_JS = """
async ({op, token, name, expected_bytes, expected_sha256, max_bytes, deadline_ms, offset, data, sha256}) => {
  const slots = window.__hfSeedStreams ||= new Map();
  const fail = code => ({error: code});
  const live = s => slots.get(token) === s && !s.cancelled && Date.now() < s.deadline;
  const abortWriter = async s => {
    if (!s.writer || s.closed) return false;
    if (!s.abortPromise) s.abortPromise = s.writer.abort().then(() => true, () => false);
    return await s.abortPromise;
  };
  const tombstone = s => {
    clearTimeout(s.timer);
    s.timer = setTimeout(() => {if (slots.get(token) === s) slots.delete(token);},
                        Math.max(0, s.deadline - Date.now()) + 1000);
  };
  let slot = slots.get(token);
  if (op === 'abort') {
    // Remember cancellation even if the timed-out begin evaluation has not run.
    slot ||= {deadline: deadline_ms}; slots.set(token, slot); slot.cancelled = true;
    const pending = slot.pending;
    try { await abortWriter(slot); if (pending) await pending.catch(() => {}); }
    finally { tombstone(slot); }
    return {status: slot.closed ? 'committed' : 'aborted'};
  }
  if (op === 'release') {
    if (!slot || !slot.closed || !slot.verified || slot.cancelled) return fail('upload_seed_release_failed');
    clearTimeout(slot.timer); slots.delete(token); return {status: 'released'};
  }
  if (op === 'begin') {
    if (slot || !Number.isSafeInteger(expected_bytes) || expected_bytes <= 0 || expected_bytes > max_bytes ||
        !Number.isSafeInteger(max_bytes) || !/^[a-f0-9]{64}$/.test(expected_sha256) ||
        typeof name !== 'string' || !name || /[\\/]/.test(name) || name === '.' || name === '..' ||
        !Number.isFinite(deadline_ms) || Date.now() >= deadline_ms)
      return fail('upload_seed_begin_refused');
    slot = {name, expected: expected_bytes, digest: expected_sha256, deadline: deadline_ms, offset: 0};
    slots.set(token, slot);
    slot.timer = setTimeout(() => {slot.cancelled = true; tombstone(slot); void abortWriter(slot).catch(() => {});},
                            Math.max(0, deadline_ms - Date.now()));
  } else if (!slot || !live(slot) || slot.pending || slot.closed) {
    return fail('upload_seed_transaction_unavailable');
  }
  const run = async () => {
    try {
      if (op === 'begin') {
        const root = await navigator.storage.getDirectory();
        if (!live(slot)) return fail('upload_seed_cancelled');
        slot.handle = await root.getFileHandle(name, {create: true});
        if (!live(slot)) return fail('upload_seed_cancelled');
        slot.writer = await slot.handle.createWritable();
        if (!live(slot)) {await abortWriter(slot); return fail('upload_seed_cancelled');}
        return {status: 'ready', offset: 0};
      }
      if (op === 'write') {
        if (!Number.isSafeInteger(offset) || offset !== slot.offset || typeof data !== 'string' ||
            data.length > 4 * Math.ceil(1048576 / 3) || !/^[a-f0-9]{64}$/.test(sha256))
          throw new Error('invalid chunk');
        const binary = atob(data), bytes = new Uint8Array(binary.length);
        if (!bytes.length || bytes.length > 1048576 || offset + bytes.length > slot.expected)
          throw new Error('invalid chunk size');
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        const hash = await crypto.subtle.digest('SHA-256', bytes);
        if (Array.from(new Uint8Array(hash), x => x.toString(16).padStart(2, '0')).join('') !== sha256 || !live(slot))
          throw new Error('changed or late chunk');
        await slot.writer.write({type: 'write', position: offset, data: bytes});
        if (!live(slot)) throw new Error('cancelled write');
        slot.offset += bytes.length;
        return {status: 'written', offset: slot.offset};
      }
      if (op === 'finalize') {
        if (offset !== slot.offset || offset !== slot.expected || sha256 !== slot.digest || !live(slot))
          throw new Error('incomplete seed');
        slot.committing = true;
        await slot.writer.close(); slot.closed = true;
        if (!live(slot)) return fail('upload_seed_commit_uncertain');
        const file = await slot.handle.getFile();
        if (!live(slot) || file.size !== slot.expected) return fail('upload_seed_commit_uncertain');
        slot.verified = true;
        return {status: 'seeded', name: slot.name, bytes: slot.expected, sha256: slot.digest};
      }
      throw new Error('unknown operation');
    } catch (_) {
      slot.cancelled = true; await abortWriter(slot); return fail('upload_seed_transaction_failed');
    }
  };
  const pending = run(); slot.pending = pending;
  try { return await pending; }
  finally { if (slot.pending === pending) slot.pending = null; }
}
"""


def _upload_seed_facts(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_upload_seed(source: Path, step: dict, *, buffering=0):
    """One held no-follow descriptor, shared by legacy proof and streamed seeding."""
    path = source.absolute()
    if ".." in path.parts:
        raise ValueError("upload_seed_path_invalid")
    parent = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    stream = os.fdopen(fd, "rb", buffering=buffering)
    try:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_size != step["expected_bytes"]
                or not 0 < before.st_size <= step["max_bytes"]):
            raise ValueError("upload_seed_size_mismatch")
        return stream, before
    except BaseException:
        stream.close()
        raise


def _upload_seed_bytes(source: Path, step: dict) -> bytes:
    """Compatibility helper; recorded seeding uses bounded reads below."""
    stream, before = _open_upload_seed(source, step, buffering=-1)
    with stream:
        data = stream.read(step["expected_bytes"] + 1)
        after = os.fstat(stream.fileno())
        if (_upload_seed_facts(before) != _upload_seed_facts(after) or len(data) != step["expected_bytes"]
                or hashlib.sha256(data).hexdigest() != step["expected_sha256"]):
            raise ValueError("upload_seed_bytes_changed")
        return data


async def _stream_upload_seed(page: Any, source: Path, name: str, proof: dict, *, started=None) -> int:
    """Bound every transfer and include preparation in one observed deadline.

    The small synchronous filesystem calls cannot preempt a stalled kernel, but
    no unbounded read/encode precedes the deadline. Cancellation fences browser
    writes; a close already committing may be uncertain and never permits supply.
    """
    started = time.monotonic() if started is None else started
    if _upload_problems(proof) or name != proof["seed"]:
        raise ValueError("upload_seed_proof_invalid")
    deadline = started + proof["timeout"]
    wall_deadline = (time.time() + max(0, deadline - time.monotonic())) * 1000
    token, stream, begun, completed = uuid.uuid4().hex, None, False, False
    cancelled = None
    def remaining():
        left = deadline - time.monotonic()
        if left <= 0:
            raise asyncio.TimeoutError()
        return left
    async def command(op, **values):
        timeout = remaining()
        value = await asyncio.wait_for(page.evaluate(UPLOAD_SEED_STREAM_JS,
            dict(op=op, token=token, deadline_ms=wall_deadline, **values)), timeout=timeout)
        remaining()  # a late acknowledgment is not successful admission
        return value
    try:
        remaining()
        stream, before = _open_upload_seed(source, proof)
        remaining()
        begun = True  # a cancelled evaluate may still have reached the browser
        ready = await command("begin", name=name, expected_bytes=proof["expected_bytes"],
                              expected_sha256=proof["expected_sha256"], max_bytes=proof["max_bytes"])
        if ready != {"status": "ready", "offset": 0}:
            raise ValueError("upload_seed_begin_failed")
        count, digest = 0, hashlib.sha256()
        while count < proof["expected_bytes"]:
            remaining()
            chunk = stream.read(min(UPLOAD_SEED_CHUNK_BYTES, proof["expected_bytes"] - count))
            remaining()
            if not chunk:
                raise ValueError("upload_seed_truncated")
            digest.update(chunk)
            written = await command("write", offset=count,
                data=base64.b64encode(chunk).decode("ascii"), sha256=hashlib.sha256(chunk).hexdigest())
            count += len(chunk)
            if written != {"status": "written", "offset": count}:
                raise ValueError("upload_seed_chunk_failed")
            del chunk
        remaining()
        extra = stream.read(1)
        after = os.fstat(stream.fileno())
        remaining()
        if (extra or _upload_seed_facts(before) != _upload_seed_facts(after)
                or digest.hexdigest() != proof["expected_sha256"]):
            raise ValueError("upload_seed_bytes_changed")
        result = await command("finalize", offset=count, sha256=digest.hexdigest())
        if result != dict(status="seeded", name=name, bytes=count, sha256=proof["expected_sha256"]):
            raise ValueError("upload_seed_commit_unacknowledged")
        completed = True
        return count
    except asyncio.CancelledError as exc:
        cancelled = exc
        raise
    finally:
        if stream is not None:
            stream.close()
        if begun:
            try:
                cleaned = await asyncio.wait_for(page.evaluate(UPLOAD_SEED_STREAM_JS,
                    dict(op="release" if completed else "abort", token=token, deadline_ms=wall_deadline)),
                    timeout=UPLOAD_SEED_CLEANUP_S)
                if completed and cleaned != {"status": "released"}:
                    raise ValueError("upload_seed_cleanup_failed")
            except (Exception, asyncio.CancelledError):
                if cancelled is not None:
                    raise cancelled
                raise


async def seed_files(page: Any, seeds: list[dict], verbose: bool = True, *, upload_steps=()) -> list[str]:
    """Put real media in the app's reach before the camera rolls.

    An editor with an empty media library records as a tour of an empty room. Seeding writes the
    bytes into OPFS — the same storage the app itself uses — so what gets filmed is the product
    doing its actual job on actual footage, not a mocked-out shell.
    """
    problems: list[str] = []
    for seed in seeds:
        seed_started = time.monotonic()
        source = Path(seed["path"]).expanduser()
        if not source.is_absolute():
            # Scripts are checked in and run from several directories; a seed path is resolved
            # against the repo so the same file works from the app folder, the root or a cron.
            source = REPO_ROOT / source if upload_steps else (REPO_ROOT / source).resolve()
        name = seed.get("as") or source.name
        proof = next((step for step in upload_steps if step["seed"] == name), None)
        if proof is None:
            if not source.exists():
                problems.append(f"seed missing: {source}")
                continue
            payload = base64.b64encode(source.read_bytes()).decode("ascii")
        try:
            if proof is not None:
                size = await _stream_upload_seed(page, source, name, proof, started=seed_started)
            else:
                size = await page.evaluate(WRITE_SEED_JS, {"name": name, "data": payload})
            if verbose:
                print(f"    seed  · {name} ({size / 1_000_000:.1f} MB) → workspace", flush=True)
        except Exception as exc:                                # noqa: BLE001
            problems.append(f"seed {name}: upload_seed_failed" if proof is not None
                            else f"seed {name}: {type(exc).__name__}: {exc}")
    return problems


def _best_selector(element: dict, label: str) -> str | None:
    """Pick the selector most likely to still resolve next week.

    Order is deliberate: a test id survives a redesign, an id survives a re-style, an accessible
    role+name survives a DOM reshuffle, and visible text survives nothing but is what a human
    writing a script actually types. A first-class-name selector is last because a Tailwind class
    is a coincidence, not an identity.
    """
    if testid := element.get("data_testid"):
        return f'[data-testid="{testid}"]'
    identifier = element.get("id")
    if identifier and not re.search(r"\d{4,}|:r[a-z0-9]+:", identifier):
        return f"#{identifier}"                        # generated ids change on every render
    role = element.get("role") or ({"a": "link", "button": "button"}.get(element.get("tag") or ""))
    if role and label:
        return f'role={role}[name="{label[:60]}"]'
    # A truncated *exact* attribute selector matches nothing, which is worse than a long one —
    # it fails at record time on a step that looked fine in the map. Truncation switches to
    # starts-with so the selector still resolves.
    for attribute, key in (("aria-label", "aria_label"), ("placeholder", "placeholder")):
        if value := element.get(key):
            operator = "^=" if len(value) > 60 else "="
            return f'[{attribute}{operator}"{value[:60]}"]'
    if label and len(label) <= 60:
        return f"text={label}"
    return None


async def cmd_discover(args: argparse.Namespace) -> int:
    """Dump what is on the page and how to press it — the input a model turns into a script.

    This is the answer to "how does the agent know where to click": it does not guess at pixels,
    it reads the same accessibility-shaped element map humanflow's own agent decides from, and
    every row carries a selector that can be pasted straight into a step.
    """
    from playwright.async_api import async_playwright

    _, scan_js = _humanflow()
    # Pointed at a script, discover walks that script's own stage + setup first. The map you want
    # is of the screen the demo will actually open on, not of the workspace gate in front of it.
    if args.script:
        script = json.loads(Path(args.script).read_text(encoding="utf-8"))
        url = args.url or script["url"]
    else:
        script = {"url": args.url, "viewport": {"width": args.width, "height": args.height}}
        url = args.url
    if not url:
        print("give a URL, or --script pointing at a demo script that has one")
        return 2
    async with async_playwright() as playwright:
        browser, context, width, height = await _browser(playwright, script, args.headed)
        page = await context.new_page()
        await page.goto(url, wait_until="load", timeout=args.timeout * 1000)
        stage = script.get("stage") or {}
        await dismiss_blockers(page, list(stage.get("dismiss") or []))
        problems = await seed_files(page, stage.get("seed_files") or [])
        script_opened: set[str] = set()
        problems += await run_setup(page, script.get("setup") or [], verbose=True,
                                    opened=script_opened)
        await dismiss_blockers(page, list(stage.get("dismiss") or []), protect=script_opened)
        for problem in problems:
            print(f"  ! {problem}")
        if args.wait_for:
            await page.locator(args.wait_for).first.wait_for(state="visible",
                                                             timeout=args.timeout * 1000)
        await asyncio.sleep(args.settle)
        try:
            elements = await page.evaluate(scan_js)
        except Exception as exc:                                # noqa: BLE001
            print(f"  ! element scan failed: {type(exc).__name__}: {exc}")
            elements = []
        shot = None
        if args.screenshot:
            shot = str(Path(args.screenshot).resolve())
            await page.screenshot(path=shot, full_page=False)
        title = await page.title()
        await _shutdown(browser, context)

    rows = []
    for element in elements or []:
        if not element.get("clickable"):
            continue                                   # a map of every visible div helps nobody
        label = (element.get("text") or element.get("aria_label") or
                 element.get("placeholder") or "").strip()
        selector = _best_selector(element, label)
        if not selector:
            continue
        rows.append({
            "role": element.get("role") or element.get("tag"),
            "label": label[:80],
            "selector": selector,
            "enabled": element.get("enabled", True),
            "in_viewport": element.get("in_viewport", True),
            "box": {"x": round(element.get("x", 0)), "y": round(element.get("y", 0)),
                    "w": round(element.get("width", 0)), "h": round(element.get("height", 0))},
        })
    # Same element reached two ways is one row; a map with duplicates reads as a bigger app.
    seen: set[str] = set()
    rows = [row for row in rows if not (row["selector"] in seen or seen.add(row["selector"]))]
    payload = {"url": url, "title": title, "viewport": {"width": width, "height": height},
               "screenshot": shot, "count": len(rows), "elements": rows}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"{len(rows)} pressable elements → {args.out}")
    else:
        print(json.dumps(payload, indent=2))
    return 0


def cmd_check(_: argparse.Namespace) -> int:
    ok = True
    try:
        import playwright                                       # noqa: F401
        from importlib.metadata import version
        print(f"playwright  : ok ({version('playwright')})")
    except Exception as exc:                                    # noqa: BLE001
        print(f"playwright  : MISSING ({exc}) — pip install playwright")
        ok = False
    try:
        chrome = browser_executable()
        if chrome is None:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as driver:
                chrome = Path(driver.chromium.executable_path)
        if not chrome.is_file():
            raise ValueError("run `python -m playwright install chromium`")
        print(f"chrome      : ok ({chrome})")
    except (ImportError, ValueError) as exc:
        print(f"chrome      : MISSING — {exc}")
        ok = False
    if shutil.which("ffmpeg"):
        print(f"ffmpeg      : ok ({shutil.which('ffmpeg')})")
    else:
        print("ffmpeg      : MISSING — apt install ffmpeg")
        ok = False
    if (HUMANFLOW_SRC / "humanflow").is_dir():
        try:
            _humanflow()
            print(f"humanflow   : ok ({HUMANFLOW_SRC})")
        except Exception as exc:                                # noqa: BLE001
            print(f"humanflow   : present but not importable ({exc})")
            ok = False
    else:
        print(f"humanflow   : MISSING {HUMANFLOW_SRC}")
        ok = False
    print(f"recordings  : {DEFAULT_OUT}")
    return 0 if ok else 1


def cmd_validate(args: argparse.Namespace) -> int:
    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    problems = validate_script(script)
    for problem in problems:
        print(f"  ! {problem}")
    if problems:
        return 2
    kinds: dict[str, int] = {}
    for step in script["steps"]:
        kinds[step["do"]] = kinds.get(step["do"], 0) + 1
    print(f"ok · {len(script['steps'])} steps · " + " · ".join(f"{k}×{v}" for k, v in kinds.items()))
    if script.get("setup"):
        print(f"     setup {len(script['setup'])} off-camera step(s) before the camera rolls")
    print(f"     target {script['url']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record an agent-driven demo of a web app as a capture-lane bundle.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="verify playwright, chrome, ffmpeg and humanflow are reachable")

    p_val = sub.add_parser("validate", help="check a demo script without opening a browser")
    p_val.add_argument("script")

    p_dis = sub.add_parser("discover", help="dump every pressable element + its selector")
    p_dis.add_argument("url", nargs="?", default="")
    p_dis.add_argument("--script", default="",
                       help="run this demo script's stage + setup first, then map that screen")
    p_dis.add_argument("--out", default="", help="write JSON here instead of stdout")
    p_dis.add_argument("--wait-for", default="", help="selector that means the app is ready")
    p_dis.add_argument("--screenshot", default="", help="also save a PNG of the ready state")
    p_dis.add_argument("--settle", type=float, default=1.5)
    p_dis.add_argument("--timeout", type=float, default=45)
    p_dis.add_argument("--width", type=int, default=1920)
    p_dis.add_argument("--height", type=int, default=1080)
    p_dis.add_argument("--headed", action="store_true")

    p_auth = sub.add_parser("auth", help="signed-in sessions, so a take never meets a login wall")
    auth_sub = p_auth.add_subparsers(dest="auth_cmd", required=True)
    auth_sub.add_parser("list", help="what sessions and profiles exist, and when they expire")

    a_grab = auth_sub.add_parser("grab", help="copy a session out of an already signed-in CDP seat")
    a_grab.add_argument("name")
    a_grab.add_argument("--cdp", type=int, required=True, help="debug port of the signed-in browser")
    a_grab.add_argument("--domain", action="append", default=[],
                        help="keep only cookies for this domain (repeatable). Narrow it: a session "
                             "file should carry the one account it is for, not the whole browser")
    a_grab.add_argument("--dry", action="store_true",
                        help="show which hosts the seat holds sessions for; write nothing")
    a_grab.add_argument("--include-local-storage", action="store_true",
                        help="also read localStorage from tabs that are ALREADY open (many SPAs "
                             "keep the token there). Never navigates the operator's seat")

    a_login = auth_sub.add_parser("login", help="open a real browser on a named profile and sign in")
    a_login.add_argument("name")
    a_login.add_argument("--url", default="", help="page to open for signing in")
    a_login.add_argument("--port", type=int, default=9777, help="remote debugging port to attach to")
    a_login.add_argument("--minutes", type=float, default=20)
    a_login.add_argument("--setup-from", default="",
                         help="run this demo script's setup steps to sign in, then close — for "
                              "apps whose credentials can live in a file rather than a human")
    a_login.add_argument("--headless", action="store_true",
                         help="headless — only useful when your CDP client drives the sign-in")
    a_login.add_argument("--width", type=int, default=1440)
    a_login.add_argument("--height", type=int, default=900)

    p_rec = sub.add_parser("rec", help="record a take from a demo script")
    p_rec.add_argument("script")
    p_rec.add_argument("--out-dir", default="", help=f"default {DEFAULT_OUT}")
    p_rec.add_argument("--headed", action="store_true", help="show the browser (needs a display)")
    p_rec.add_argument("--keep-frames", action="store_true", help="keep the raw jpg frames")
    p_rec.add_argument("--no-burn-captions", action="store_true",
                       help="record 'say' lines as narration only — do not draw them in the frame "
                            "(the cut adds them back as typography that can be re-timed)")
    p_rec.add_argument("--keep-going", action="store_true", help="do not stop on a failed step")
    p_rec.add_argument("--raw-keys", action="store_true",
                       help="log typed characters (default redacts — these takes get posted)")
    p_rec.add_argument("--cdp", type=int, default=0,
                       help="record INSIDE an already-signed-in browser on this debug port "
                            "instead of launching one. Name the port explicitly — webrec never "
                            "picks a window for you, and never closes the one you name")
    p_rec.add_argument("--quiet", action="store_true")

    args = parser.parse_args()
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "validate":
        return cmd_validate(args)
    if args.cmd == "auth":
        if args.auth_cmd == "list":
            return cmd_auth_list(args)
        if args.auth_cmd == "grab":
            return asyncio.run(cmd_auth_grab(args))
        return asyncio.run(cmd_auth_login(args))
    if args.cmd == "discover":
        return asyncio.run(cmd_discover(args))
    return asyncio.run(cmd_rec(args))


if __name__ == "__main__":
    raise SystemExit(main())
