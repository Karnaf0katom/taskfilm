import math
import random
from typing import List, Tuple

Point = Tuple[int, int]


def _ease_in_out(t: float) -> float:
    # Smoothstep
    return t * t * (3 - 2 * t)


def _bezier(p0, p1, p2, p3, t: float) -> Tuple[float, float]:
    # Cubic Bezier
    u = 1 - t
    x = (u**3)*p0[0] + 3*(u**2)*t*p1[0] + 3*u*(t**2)*p2[0] + (t**3)*p3[0]
    y = (u**3)*p0[1] + 3*(u**2)*t*p1[1] + 3*u*(t**2)*p2[1] + (t**3)*p3[1]
    return x, y


def generate_human_path(
    start: Point,
    end: Point,
    steps: int = 60,
    curve_strength: float = 0.25,
    jitter: float = 1.5,
) -> List[Point]:
    """
    Generate a smooth, slightly-random path from start->end.
    steps: number of points in the path
    curve_strength: how "curvy" the path is (0..1)
    jitter: random pixel noise applied to each sampled point
    """
    x0, y0 = start
    x1, y1 = end
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy)

    # Perpendicular vector for curve control
    if dist == 0:
        return [start]

    px, py = -dy / dist, dx / dist  # unit perpendicular

    # Curve magnitude scales with distance
    mag = dist * curve_strength * random.uniform(0.6, 1.2)

    # Control points along the line + perpendicular offset
    p0 = (x0, y0)
    p3 = (x1, y1)

    c1 = (
        x0 + dx * random.uniform(0.2, 0.4) + px * mag * random.uniform(-1, 1),
        y0 + dy * random.uniform(0.2, 0.4) + py * mag * random.uniform(-1, 1),
    )
    c2 = (
        x0 + dx * random.uniform(0.6, 0.8) + px * mag * random.uniform(-1, 1),
        y0 + dy * random.uniform(0.6, 0.8) + py * mag * random.uniform(-1, 1),
    )

    path: List[Point] = []
    last = None

    for i in range(steps):
        t = i / (steps - 1)
        t2 = _ease_in_out(t)
        x, y = _bezier(p0, c1, c2, p3, t2)

        # Small jitter (more at middle, less at ends)
        j = jitter * (1 - abs(2*t - 1))  # peak in middle
        x += random.uniform(-j, j)
        y += random.uniform(-j, j)

        pt = (int(round(x)), int(round(y)))
        if pt != last:
            path.append(pt)
            last = pt

    # Ensure exact end
    if not path or path[-1] != end:
        path.append(end)

    return path
