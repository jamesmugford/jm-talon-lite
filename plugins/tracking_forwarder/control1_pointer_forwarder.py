"""Forward control1 gaze samples through the native Wayland pointer."""

import os
import sys

from talon import Module, actions, app, settings, tracking_system, ui
from talon.plugins import eye_mouse

from ..shared.pure_utils import desktop_bounds_from_rects, normalize_point

mod = Module()

mod.setting(
    "control1_pointer_forwarder_autostart",
    type=bool,
    default=False,
    desc="Auto-start native control1 pointer forwarding at Talon startup.",
)

_registered = False
_desktop_bounds = (0.0, 0.0, 1.0, 1.0)
_CALLBACK_KEY = "_jm_talon_lite_control1_pointer_callback"
# Talon does not automatically remove tracking callbacks on script reload.
_previous_callbacks = {
    globals().get("_on_gaze"),
    getattr(sys, _CALLBACK_KEY, None),
}
for _previous_callback in _previous_callbacks - {None}:
    for _ in range(16):
        tracking_system.unregister("gaze", _previous_callback)


def _is_wayland() -> bool:
    return bool(
        os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("SWAYSOCK")
        or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def _refresh_desktop_bounds() -> None:
    global _desktop_bounds
    rects = [
        (screen.rect.x, screen.rect.y, screen.rect.width, screen.rect.height)
        for screen in ui.screens()
    ]
    _desktop_bounds = desktop_bounds_from_rects(rects)


def _clear_gaze_subscriptions(callback) -> None:
    for _ in range(16):
        tracking_system.unregister("gaze", callback)


def _register_gaze() -> None:
    global _registered
    _clear_gaze_subscriptions(_on_gaze)
    tracking_system.register("gaze", _on_gaze)
    setattr(sys, _CALLBACK_KEY, _on_gaze)
    _registered = True


def _unregister_gaze() -> None:
    global _registered
    _clear_gaze_subscriptions(_on_gaze)
    if getattr(sys, _CALLBACK_KEY, None) is _on_gaze:
        delattr(sys, _CALLBACK_KEY)
    _registered = False


def _on_gaze(*_args) -> None:
    if not actions.tracking.control1_enabled():
        return
    hist = eye_mouse.mouse.xy_hist
    if not hist:
        return
    point = hist[-1]
    if not _is_wayland():
        actions.mouse_move(point.x, point.y)
        return
    normalized_x, normalized_y = normalize_point(
        _desktop_bounds,
        point.x,
        point.y,
    )
    actions.user.wayland_pointer_move_absolute(
        normalized_x,
        normalized_y,
        refresh_hover=True,
    )


def _on_screen_change(_screens) -> None:
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
    ui.register("screen_change", _on_screen_change)
    _refresh_desktop_bounds()
    if settings.get("user.control1_pointer_forwarder_autostart"):
        actions.user.control1_pointer_forwarder_start()


app.register("ready", _on_ready)
