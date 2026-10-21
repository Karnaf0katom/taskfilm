"""Original frame styles and seekable screencast overlays for hfcomp.

Only presentation is authored here. The existing compositor and HyperFrames
continue to own media timing, preview and rendering.
"""
from __future__ import annotations

import html
import math
import re


PRESETS = {
    "studio": {"background": ["#10283f", "#071018"], "angle": 135,
               "padding": 72, "radius": 24, "shadow": True, "accent": "#38bdf8", "cursor_size": 32},
    "paper": {"background": ["#f0e9df", "#d5dfe4"], "angle": 120,
              "padding": 80, "radius": 16, "shadow": True, "accent": "#2563eb", "cursor_size": 32},
    "midnight": {"background": ["#17152f", "#070916"], "angle": 145,
                 "padding": 64, "radius": 28, "shadow": True, "accent": "#a78bfa", "cursor_size": 32},
}
EASINGS = {"gentle": ("power2.out", "power2.inOut"),
           "smooth": ("sine.inOut", "sine.inOut"), "linear": ("none", "none")}


def number(value, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if not low <= value <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return float(value)


def fields(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"unknown {label} field(s): {', '.join(sorted(unknown))}")


def style_config(preset: str, overrides: dict, width: int, height: int) -> dict:
    if not isinstance(preset, str) or preset not in PRESETS:
        raise ValueError(f"preset must be one of {', '.join(PRESETS)}")
    fields(overrides, PRESETS[preset], "style")
    style = {**PRESETS[preset], **overrides}
    colors = style["background"]
    if isinstance(colors, str):
        colors = [colors]
    if not isinstance(colors, list) or not 1 <= len(colors) <= 2:
        raise ValueError("background must be one hex color or a pair of hex colors")
    for color in [*colors, style["accent"]]:
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("style colors must use #RRGGBB")
    style["background"] = colors
    for key, low, high in (("padding", 0, min(width, height) / 3), ("radius", 0, 100),
                           ("angle", 0, 360), ("cursor_size", 12, 96)):
        style[key] = number(style[key], key, low, high)
    if not isinstance(style["shadow"], bool):
        raise ValueError("shadow must be true or false")
    return style


def layers(presentation: dict, width: int, height: int) -> tuple[str, str, str]:
    style = presentation["style"]
    padding = style["padding"]
    ratio = presentation["source_width"] / presentation["source_height"]
    fw = min(width - 2 * padding, (height - 2 * padding) * ratio)
    fh = fw / ratio
    colors = style["background"]
    background = colors[0] if len(colors) == 1 else f'linear-gradient({style["angle"]}deg, {colors[0]}, {colors[1]})'
    shadow = "0 24px 70px rgba(0,0,0,.4)" if style["shadow"] else "none"
    accent, size = style["accent"], style["cursor_size"]
    css = f"""
      html, body, #root {{ background: {background}; }}
      .stage {{ inset: auto; left: {(width-fw)/2:.3f}px; top: {(height-fh)/2:.3f}px;
        width: {fw:.3f}px; height: {fh:.3f}px; border-radius: {style['radius']}px;
        box-shadow: {shadow}; }}
      .camera video {{ object-fit: contain; }}
      .vignette {{ display: none; }}
      .screen-layer {{ position: absolute; inset: 0; pointer-events: none; }}
      #polish-cursor {{ position: absolute; left: 0; top: 0; width: {size}px;
        height: {size}px; opacity: 0; filter: drop-shadow(0 2px 3px rgba(0,0,0,.6)); }}
      .click-ring {{ position: absolute; width: {size*1.5}px; height: {size*1.5}px;
        border: 3px solid {accent}; border-radius: 50%; opacity: 0; }}
      .screen-label {{ position: absolute; max-width: 80%; transform: translate(-50%, -50%);
        padding: .5em .8em; border-radius: 10px; color: #fff; background: #080d16;
        border: 1px solid {accent}; font-size: {max(16, fw*.022):.3f}px;
        line-height: 1.3; text-align: center; overflow-wrap: anywhere; visibility: hidden; }}
"""
    nodes, tweens = [], []
    if presentation.get("cursor_overlay"):
        nodes.append('<svg id="polish-cursor" viewBox="0 0 32 32" aria-hidden="true">'
                     '<path d="M3 2 L3 26 L10 20 L15 30 L20 27 L15 18 L25 17 Z" '
                     'fill="white" stroke="#101820" stroke-width="1.5"/></svg>')
        for segment in presentation.get("cursor_segments", []):
            samples = segment["samples"]
            if not samples:
                continue
            first = samples[0]
            tweens.append(f'tl.set("#polish-cursor", {{x:{first["x"]*fw:.4f}, y:{first["y"]*fh:.4f}, opacity:1}}, {first["t"]:.6f});')
            for prev, sample in zip(samples, samples[1:]):
                gap = sample["t"] - prev["t"]
                position = f'x:{sample["x"]*fw:.4f}, y:{sample["y"]*fh:.4f}'
                if gap > 1.5:
                    tweens.append(f'tl.set("#polish-cursor", {{opacity:0}}, {prev["t"]+1.5:.6f});')
                    tweens.append(f'tl.set("#polish-cursor", {{{position}, opacity:1}}, {sample["t"]:.6f});')
                else:
                    tweens.append(f'tl.to("#polish-cursor", {{{position}, duration:{gap:.6f}, ease:"none"}}, {prev["t"]:.6f});')
            end = min(segment["end"], samples[-1]["t"] + 1.5)
            tweens.append(f'tl.set("#polish-cursor", {{opacity:0}}, {end:.6f});')
    for i, click in enumerate(presentation.get("clicks", [])):
        nodes.append(f'<div class="click-ring" id="click-{i}" style="left:{click["x"]*100:.4f}%;top:{click["y"]*100:.4f}%"></div>')
        tweens.append(f'tl.fromTo("#click-{i}", {{xPercent:-50,yPercent:-50,scale:.3,opacity:.9}}, '
                      f'{{scale:1.8,opacity:0,duration:{click["duration"]:.6f},ease:"power2.out",immediateRender:false}}, {click["t"]:.6f});')
    for i, label in enumerate(presentation.get("annotations", [])):
        nodes.append(f'<div class="screen-label" id="label-{i}" style="left:{label["x"]*100:.4f}%;top:{label["y"]*100:.4f}%">{html.escape(label["text"])}</div>')
        # Fading text and its plate together makes contrast collapse against
        # the recording during the fade. Keep timed labels fully readable.
        tweens.append(f'tl.set("#label-{i}", {{visibility:"visible"}}, {label["start"]:.6f});')
        tweens.append(f'tl.set("#label-{i}", {{visibility:"hidden"}}, {label["end"]:.6f});')
    return css, '<div class="screen-layer">' + "\n".join(nodes) + '</div>', "\n".join(tweens)
