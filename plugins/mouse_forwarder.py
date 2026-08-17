"""Forward Talon mouse actions through the native Wayland runtime."""

import os

from talon import Context, Module, actions, app, settings, ui

from .shared.pure_utils import (
    accumulate_scroll_steps,
    desktop_bounds_from_rects,
    normalize_point,
)

mod = Module()
mod.tag(
    "wayland_mouse_forwarder",
    desc="Enable Wayland mouse forwarder command overrides.",
)

ctx = Context()
ctx.matches = r"""
os: linux
"""


@mod.action_class
class Actions:
    def mouse_forwarder_touch():
        """Click normally, or release an active drag."""

    def mouse_forwarder_scroll_up(amount: float = 1):
        """Scroll up via the native Wayland pointer."""

    def mouse_forwarder_scroll_down(amount: float = 1):
        """Scroll down via the native Wayland pointer."""

    def mouse_forwarder_scroll_left(amount: float = 1):
        """Scroll left via the native Wayland pointer."""

    def mouse_forwarder_scroll_right(amount: float = 1):
        """Scroll right via the native Wayland pointer."""

    def mouse_forwarder_modified_click(modifiers: str, button: int = 0):
        """Click while holding modifiers via native Wayland input."""


_vertical_scroll_remainder = 0.0
_horizontal_scroll_remainder = 0.0


def _is_wayland() -> bool:
    return bool(
        os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("SWAYSOCK")
        or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def _scaled_scroll_delta(delta: float, setting_name: str) -> float:
    unit = settings.get(setting_name)
    if unit == 0:
        return delta
    return delta / unit


def _forward_vertical_scroll(delta: float) -> None:
    global _vertical_scroll_remainder
    if delta == 0:
        return
    scaled = _scaled_scroll_delta(delta, "user.mouse_wheel_down_amount")
    steps, _vertical_scroll_remainder = accumulate_scroll_steps(
        scaled,
        _vertical_scroll_remainder,
    )
    if steps:
        actions.user.wayland_pointer_scroll(vertical_steps=steps)


def _forward_horizontal_scroll(delta: float) -> None:
    global _horizontal_scroll_remainder
    if delta == 0:
        return
    scaled = _scaled_scroll_delta(delta, "user.mouse_wheel_horizontal_amount")
    steps, _horizontal_scroll_remainder = accumulate_scroll_steps(
        scaled,
        _horizontal_scroll_remainder,
    )
    if steps:
        actions.user.wayland_pointer_scroll(horizontal_steps=steps)


@ctx.action_class("main")
class MainActions:
    def mouse_click(button: int = 0):
        if not _is_wayland():
            actions.next(button)
            return
        try:
            actions.user.wayland_pointer_click(button)
        except ValueError:
            actions.next(button)

    def mouse_drag(button: int = 0):
        if not _is_wayland():
            actions.next(button)
            return
        try:
            actions.user.wayland_pointer_button_down(button)
        except ValueError:
            actions.next(button)

    def mouse_release(button: int = 0):
        if not _is_wayland():
            actions.next(button)
            return
        try:
            actions.user.wayland_pointer_button_up(button)
        except ValueError:
            actions.next(button)

    def mouse_move(x: float, y: float):
        if not _is_wayland():
            actions.next(x, y)
            return
        rects = [
            (screen.rect.x, screen.rect.y, screen.rect.width, screen.rect.height)
            for screen in ui.screens()
        ]
        bounds = desktop_bounds_from_rects(rects)
        normalized_x, normalized_y = normalize_point(bounds, x, y)
        actions.user.wayland_pointer_move_absolute(normalized_x, normalized_y)

    def mouse_scroll(y: float = 0.0, x: float = 0.0, by_lines: bool = False):
        if not _is_wayland():
            actions.next(y, x, by_lines)
            return
        _forward_vertical_scroll(y)
        _forward_horizontal_scroll(x)


@ctx.action_class("user")
class UserActions:
    def mouse_forwarder_touch():
        if actions.user.mouse_drag_end():
            return
        actions.mouse_click(0)

    def mouse_forwarder_scroll_up(amount: float = 1):
        if not _is_wayland():
            actions.user.mouse_scroll_up(amount)
            return
        delta = amount * settings.get("user.mouse_wheel_down_amount")
        _forward_vertical_scroll(-delta)

    def mouse_forwarder_scroll_down(amount: float = 1):
        if not _is_wayland():
            actions.user.mouse_scroll_down(amount)
            return
        delta = amount * settings.get("user.mouse_wheel_down_amount")
        _forward_vertical_scroll(delta)

    def mouse_forwarder_scroll_left(amount: float = 1):
        if not _is_wayland():
            actions.user.mouse_scroll_left(amount)
            return
        delta = amount * settings.get("user.mouse_wheel_horizontal_amount")
        _forward_horizontal_scroll(-delta)

    def mouse_forwarder_scroll_right(amount: float = 1):
        if not _is_wayland():
            actions.user.mouse_scroll_right(amount)
            return
        delta = amount * settings.get("user.mouse_wheel_horizontal_amount")
        _forward_horizontal_scroll(delta)

    def mouse_forwarder_modified_click(modifiers: str, button: int = 0):
        if not _is_wayland():
            actions.key(f"{modifiers}:down")
            try:
                actions.mouse_click(button)
            finally:
                actions.key(f"{modifiers}:up")
            return
        actions.user.wayland_pointer_modified_click(modifiers, button)

    def mouse_scroll_up(amount: float = 1):
        if not _is_wayland():
            actions.next(amount)
            return
        delta = amount * settings.get("user.mouse_wheel_down_amount")
        _forward_vertical_scroll(-delta)

    def mouse_scroll_down(amount: float = 1):
        if not _is_wayland():
            actions.next(amount)
            return
        delta = amount * settings.get("user.mouse_wheel_down_amount")
        _forward_vertical_scroll(delta)

    def mouse_scroll_left(amount: float = 1):
        if not _is_wayland():
            actions.next(amount)
            return
        delta = amount * settings.get("user.mouse_wheel_horizontal_amount")
        _forward_horizontal_scroll(-delta)

    def mouse_scroll_right(amount: float = 1):
        if not _is_wayland():
            actions.next(amount)
            return
        delta = amount * settings.get("user.mouse_wheel_horizontal_amount")
        _forward_horizontal_scroll(delta)

    def mouse_drag_end() -> bool:
        if not _is_wayland():
            return actions.next()
        return actions.user.wayland_pointer_release_all()

    def mouse_drag_toggle(button: int):
        if not _is_wayland():
            actions.next(button)
            return
        try:
            actions.user.wayland_pointer_button_toggle(button)
        except ValueError:
            actions.next(button)


def _on_ready() -> None:
    if not _is_wayland():
        ctx.tags = []
        return
    ctx.tags = ["user.wayland_mouse_forwarder"]


app.register("ready", _on_ready)
_on_ready()
