"""Pure virtual-pointer value conversions."""

from __future__ import annotations

import math

POINTER_EXTENT = 65535
WAYLAND_FIXED_MIN = -(1 << 23)
WAYLAND_FIXED_MAX = ((1 << 31) - 1) / 256
INT32_MIN = -(1 << 31)
INT32_MAX = (1 << 31) - 1
BUTTON_CODES = {
    0: 0x110,  # BTN_LEFT
    1: 0x111,  # BTN_RIGHT
    2: 0x112,  # BTN_MIDDLE
}


def validate_wayland_fixed(value: float, field: str) -> float:
    """Return a finite value representable as Wayland signed 24.8 fixed."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    if not WAYLAND_FIXED_MIN <= value <= WAYLAND_FIXED_MAX:
        raise ValueError(f"{field} is outside the Wayland fixed-point range")
    return float(value)


def validate_int32(value: int, field: str) -> int:
    """Return a value representable as a signed Wayland protocol int."""
    if type(value) is not int:
        raise TypeError(f"{field} must be an integer")
    if not INT32_MIN <= value <= INT32_MAX:
        raise ValueError(f"{field} is outside the signed 32-bit range")
    return value


def normalized_to_extent(
    x: float, y: float, extent: int = POINTER_EXTENT
) -> tuple[int, int]:
    """Convert normalized coordinates to an inclusive integer extent."""
    if type(extent) is not int:
        raise TypeError("Pointer extent must be an integer")
    if not 0 < extent < (1 << 32):
        raise ValueError("Pointer extent must fit an unsigned 32-bit integer")
    if (
        isinstance(x, bool)
        or not isinstance(x, (int, float))
        or isinstance(y, bool)
        or not isinstance(y, (int, float))
    ):
        raise TypeError("Pointer coordinates must be numbers")
    if (
        (isinstance(x, float) and not math.isfinite(x))
        or (isinstance(y, float) and not math.isfinite(y))
    ):
        raise ValueError("Pointer coordinates must be finite")
    x = min(1.0, max(0.0, x))
    y = min(1.0, max(0.0, y))
    return (round(x * extent), round(y * extent))


def linux_button_code(button: int) -> int:
    """Return the Linux input code for a supported Talon mouse button."""
    if type(button) is not int:
        raise TypeError("Mouse button must be an integer")
    try:
        return BUTTON_CODES[button]
    except KeyError as exc:
        raise ValueError(f"Unsupported mouse button: {button}") from exc
