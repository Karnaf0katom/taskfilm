"""
Click jitter: small random offset within a circle for human-like variation.
Uniform distribution inside the circle (not square); deterministic when seed is set.
"""
from __future__ import annotations

import math
import random


def jitter_point(
    point: tuple[int, int],
    radius_px: float = 2.0,
) -> tuple[int, int]:
    """
    Return a new point randomly offset within a circle. Does not modify the input.

    Uniform in disk: use sqrt(random()) for radius so that area density is constant.
    (If we used uniform r, points would cluster near the center.)
    """
    if radius_px <= 0:
        return (point[0], point[1])

    theta = 2.0 * math.pi * random.random()
    r = radius_px * math.sqrt(random.random())
    dx = r * math.cos(theta)
    dy = r * math.sin(theta)

    return (
        point[0] + int(round(dx)),
        point[1] + int(round(dy)),
    )


def adaptive_jitter(
    target: tuple[int, int],
    current_pos: tuple[int, int],
    radius_hint: float | None = None,
) -> tuple[int, int]:
    """
    Jitter a click target based on distance from current position.
    radius_hint=None: auto (1px short moves, 2px long).
    radius_hint=0: exact coords, no jitter.
    radius_hint>0: use that radius.
    """
    if radius_hint is not None and radius_hint <= 0:
        return target
    dist = ((target[0] - current_pos[0]) ** 2 + (target[1] - current_pos[1]) ** 2) ** 0.5
    radius = (1.0 if dist < 50 else 2.0) if radius_hint is None else radius_hint
    return jitter_point(target, radius_px=radius)
