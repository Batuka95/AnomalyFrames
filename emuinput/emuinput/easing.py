"""Gesture interpolation and easing utilities."""

from __future__ import annotations


def ease_in_out(t: float) -> float:
    """Smoothstep easing in [0, 1]."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


def interpolate_steps(x0: int, y0: int, x1: int, y1: int, steps: int) -> list[tuple[int, int]]:
    """Return `steps` eased points including start and end."""
    steps = max(2, int(steps))
    points: list[tuple[int, int]] = []

    for i in range(steps):
        t = i / float(steps - 1)
        p = ease_in_out(t)
        x = int(round(x0 + (x1 - x0) * p))
        y = int(round(y0 + (y1 - y0) * p))
        points.append((x, y))

    points[0] = (int(x0), int(y0))
    points[-1] = (int(x1), int(y1))
    return points
