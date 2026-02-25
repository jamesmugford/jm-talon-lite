"""Pure helpers for tracking forwarders."""

from __future__ import annotations


RectTuple = tuple[float, float, float, float]
Bounds = tuple[float, float, float, float]
PointTuple = tuple[float, float]


def should_emit_state_change(before: bool, after: bool) -> bool:
    """Return whether a state transition should emit an event."""
    return before != after


def desktop_bounds_from_rects(rects: list[RectTuple]) -> Bounds:
    """Return union desktop bounds as left, top, width, height."""
    if not rects:
        return (0.0, 0.0, 1.0, 1.0)

    left = min(x for x, _, _, _ in rects)
    top = min(y for _, y, _, _ in rects)
    right = max(x + width for x, _, width, _ in rects)
    bottom = max(y + height for _, y, _, height in rects)

    width = max(1.0, right - left)
    height = max(1.0, bottom - top)
    return (left, top, width, height)


def clamp01(value: float) -> float:
    """Clamp a value into the inclusive 0..1 range."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def normalize_point(bounds: Bounds, x_px: float, y_px: float) -> PointTuple:
    """Convert desktop pixels to normalized 0..1 coordinates."""
    left, top, width, height = bounds
    x = (x_px - left) / width
    y = (y_px - top) / height
    return (clamp01(x), clamp01(y))


def rect_contains_point(rect: RectTuple, x: float, y: float) -> bool:
    """Return whether a point is inside a rectangle."""
    rect_x, rect_y, rect_width, rect_height = rect
    return rect_x <= x <= rect_x + rect_width and rect_y <= y <= rect_y + rect_height


def rect_local_point(rect: RectTuple, x: float, y: float) -> PointTuple | None:
    """Return point in rect-local coordinates, or None if outside."""
    if not rect_contains_point(rect, x, y):
        return None

    rect_x, rect_y, _, _ = rect
    return (x - rect_x, y - rect_y)


def format_control1_sample(
    timestamp: float,
    xy_px: PointTuple,
    gaze_norm: PointTuple,
    delta: PointTuple | None,
) -> str:
    """Format one control1 tracking sample log line."""
    if delta is None:
        return (
            f"control1 ts={timestamp:.3f} "
            f"xy_px=({xy_px[0]:.1f},{xy_px[1]:.1f}) "
            f"gaze_norm=({gaze_norm[0]:.3f},{gaze_norm[1]:.3f})"
        )

    return (
        f"control1 ts={timestamp:.3f} "
        f"xy_px=({xy_px[0]:.1f},{xy_px[1]:.1f}) "
        f"delta=({delta[0]:.2f},{delta[1]:.2f}) "
        f"gaze_norm=({gaze_norm[0]:.3f},{gaze_norm[1]:.3f})"
    )
