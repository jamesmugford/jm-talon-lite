"""Pure desktop geometry transformations."""

from __future__ import annotations

from collections.abc import Iterable

Rect = tuple[float, float, float, float]
Point = tuple[float, float]


def desktop_bounds(rects: Iterable[Rect]) -> Rect:
    """Return the union of desktop rectangles as left, top, width, height."""
    values = tuple(rects)
    if not values:
        return (0.0, 0.0, 1.0, 1.0)
    left = min(x for x, _, _, _ in values)
    top = min(y for _, y, _, _ in values)
    right = max(x + width for x, _, width, _ in values)
    bottom = max(y + height for _, y, _, height in values)
    return (left, top, max(1.0, right - left), max(1.0, bottom - top))


def clamp_unit(value: float) -> float:
    """Clamp a number to the inclusive zero-to-one range."""
    return min(1.0, max(0.0, value))


def normalize_point(bounds: Rect, x: float, y: float) -> Point:
    """Convert a desktop pixel point to normalized coordinates."""
    left, top, width, height = bounds
    return (
        clamp_unit((x - left) / width),
        clamp_unit((y - top) / height),
    )


def contains(rect: Rect, x: float, y: float) -> bool:
    """Return whether a point lies inside an inclusive rectangle."""
    left, top, width, height = rect
    return left <= x <= left + width and top <= y <= top + height


def local_point(rect: Rect, x: float, y: float) -> Point | None:
    """Return rectangle-local coordinates, or None when outside."""
    if not contains(rect, x, y):
        return None
    left, top, _, _ = rect
    return (x - left, y - top)
