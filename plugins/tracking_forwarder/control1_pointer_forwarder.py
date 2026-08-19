"""Forward control1 gaze samples through the native Wayland pointer."""

import os
import sys

from talon import Module, actions, app, settings, tracking_system, ui

_CALLBACK_KEY = "_jm_talon_lite_control1_pointer_callback"
_STATE_KEY = "_jm_talon_lite_control1_pointer_enabled"
_legacy_state_present = "_registered" in globals()
_legacy_registered = bool(globals().get("_registered", False))
_legacy_callback = globals().get("_on_gaze")
# Talon does not automatically remove tracking callbacks on script reload.
_retained_callback = getattr(sys, _CALLBACK_KEY, None)
_had_retained_state = (
    hasattr(sys, _STATE_KEY) or _legacy_state_present or _retained_callback is not None
)
_resume_registered = bool(
    getattr(
        sys,
        _STATE_KEY,
        _legacy_registered or _retained_callback is not None,
    )
)
_previous_callbacks = {
    _legacy_callback,
    _retained_callback,
}
for _previous_callback in _previous_callbacks - {None}:
    for _ in range(16):
        tracking_system.unregister("gaze", _previous_callback)
_resume_callback = _retained_callback or _legacy_callback
if _resume_registered and _resume_callback is not None:
    setattr(sys, _CALLBACK_KEY, _resume_callback)
elif hasattr(sys, _CALLBACK_KEY):
    delattr(sys, _CALLBACK_KEY)
if _had_retained_state:
    setattr(sys, _STATE_KEY, _resume_registered)

from talon.plugins import eye_mouse  # noqa: E402

from ..wayland_backend.errors import CapabilityUnavailable  # noqa: E402
from ..wayland_backend.geometry import desktop_bounds, normalize_point  # noqa: E402
from ..wayland_backend.session import is_wayland_session  # noqa: E402

mod = Module()
mod.setting(
    "control1_pointer_forwarder_autostart",
    type=bool,
    default=False,
    desc="Auto-start native control1 pointer forwarding at Talon startup.",
)

_desktop_bounds = (0.0, 0.0, 1.0, 1.0)
_registered = False


def _is_wayland() -> bool:
    """Return whether Talon is running in a Wayland session."""
    return is_wayland_session(os.environ)


def _native_pointer_available() -> bool:
    """Return whether this session currently has native pointer output."""
    if not _is_wayland():
        return False
    try:
        return actions.user.mouse_forwarder_native_pointer_selected()
    except Exception:
        return False


def _refresh_desktop_bounds() -> None:
    """Cache the bounding rectangle covering every Talon screen."""
    global _desktop_bounds
    rects = [
        (screen.rect.x, screen.rect.y, screen.rect.width, screen.rect.height)
        for screen in ui.screens()
    ]
    _desktop_bounds = desktop_bounds(rects)


def _clear_gaze_subscriptions(callback) -> None:
    """Remove every retained registration for one gaze callback."""
    for _ in range(16):
        tracking_system.unregister("gaze", callback)


def _register_gaze() -> None:
    """Register exactly one process-retained gaze callback."""
    global _registered
    _clear_gaze_subscriptions(_on_gaze)
    tracking_system.register("gaze", _on_gaze)
    setattr(sys, _CALLBACK_KEY, _on_gaze)
    setattr(sys, _STATE_KEY, True)
    _registered = True


def _unregister_gaze() -> None:
    """Remove this module generation's gaze callback idempotently."""
    global _registered
    _clear_gaze_subscriptions(_on_gaze)
    if getattr(sys, _CALLBACK_KEY, None) is _on_gaze:
        delattr(sys, _CALLBACK_KEY)
    setattr(sys, _STATE_KEY, False)
    _registered = False


def _on_gaze(*_args) -> None:
    """Forward the latest enabled Control Mouse point to the pointer."""
    if not actions.tracking.control1_enabled():
        return
    hist = eye_mouse.mouse.xy_hist
    if not hist:
        return
    point = hist[-1]
    if not _native_pointer_available():
        actions.mouse_move(point.x, point.y)
        return
    normalized_x, normalized_y = normalize_point(
        _desktop_bounds,
        point.x,
        point.y,
    )
    try:
        actions.user.wayland_pointer_move_absolute(
            normalized_x,
            normalized_y,
            refresh_hover=True,
        )
    except CapabilityUnavailable:
        actions.mouse_move(point.x, point.y)


def _on_screen_change(_screens) -> None:
    """Refresh pointer normalization after Talon's screen layout changes."""
    _refresh_desktop_bounds()


@mod.action_class
class Actions:
    def control1_pointer_forwarder_start() -> None:
        """Start control1 forwarding through the native Wayland pointer."""
        _refresh_desktop_bounds()
        _register_gaze()

    def control1_pointer_forwarder_stop() -> None:
        """Stop control1 pointer forwarding."""
        _unregister_gaze()

    def control1_pointer_forwarder_toggle(state: bool | None = None) -> None:
        """Enable, disable, or toggle control1 pointer forwarding."""
        target = not _registered if state is None else bool(state)
        if target:
            actions.user.control1_pointer_forwarder_start()
        else:
            actions.user.control1_pointer_forwarder_stop()


def _on_ready() -> None:
    """Initialize geometry and honor the forwarding autostart setting."""
    ui.register("screen_change", _on_screen_change)
    _refresh_desktop_bounds()
    if not _had_retained_state and settings.get(
        "user.control1_pointer_forwarder_autostart"
    ):
        actions.user.control1_pointer_forwarder_start()


def _on_quit() -> None:
    """Release gaze subscriptions before Talon exits."""
    _unregister_gaze()


setattr(sys, _STATE_KEY, _resume_registered)
if _resume_registered:
    _refresh_desktop_bounds()
    _register_gaze()

app.register("ready", _on_ready)
app.register("quit", _on_quit)
