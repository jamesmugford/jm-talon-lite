"""Route Talon's Linux mouse actions through uinput."""

import sys

from talon import Context, Module, actions, app, settings, ui
from talon.lib.keys import parse_keys

from .input_backend.backend import InputError
from .input_backend.talon_input import get_input
from .shared.pure_utils import (
    accumulate_scroll_steps,
    desktop_bounds_from_rects,
    normalize_point,
)


mod = Module()
ctx = Context()
ctx.matches = "os: linux"


@mod.action_class
class Actions:
    @staticmethod
    def native_scroll(vertical: float = 0, horizontal: float = 0):
        """Scroll through the native Linux input device."""

    @staticmethod
    def native_modified_click(modifiers: str, button: int = 0):
        """Click while holding modifiers through native Linux input."""


_last_error: str | None = None
_vertical_scroll_remainder = 0.0
_horizontal_scroll_remainder = 0.0


def _run(operation) -> bool:
    global _last_error
    try:
        operation()
    except (InputError, RuntimeError, ValueError) as exc:
        message = str(exc)
        if message != _last_error:
            _last_error = message
            print(f"native mouse error: {message}", file=sys.stderr, flush=True)
            app.notify(message)
        return False
    _last_error = None
    return True


def _scroll_steps(delta: float, setting_name: str, remainder: float):
    unit = settings.get(setting_name)
    scaled = delta if unit == 0 else delta / unit
    return accumulate_scroll_steps(scaled, remainder)


def _scroll(vertical: float = 0, horizontal: float = 0) -> None:
    global _horizontal_scroll_remainder, _vertical_scroll_remainder
    vertical_steps, _vertical_scroll_remainder = _scroll_steps(
        vertical,
        "user.mouse_wheel_down_amount",
        _vertical_scroll_remainder,
    )
    horizontal_steps, _horizontal_scroll_remainder = _scroll_steps(
        horizontal,
        "user.mouse_wheel_horizontal_amount",
        _horizontal_scroll_remainder,
    )
    if not vertical_steps and not horizontal_steps:
        return
    _run(
        lambda: get_input().scroll(
            vertical=-vertical_steps,
            horizontal=horizontal_steps,
        )
    )


def _scroll_lines(vertical: float = 0, horizontal: float = 0) -> None:
    global _horizontal_scroll_remainder, _vertical_scroll_remainder
    vertical_steps, _vertical_scroll_remainder = accumulate_scroll_steps(
        vertical,
        _vertical_scroll_remainder,
    )
    horizontal_steps, _horizontal_scroll_remainder = accumulate_scroll_steps(
        horizontal,
        _horizontal_scroll_remainder,
    )
    if vertical_steps or horizontal_steps:
        _run(
            lambda: get_input().scroll(
                vertical=-vertical_steps,
                horizontal=horizontal_steps,
            )
        )


@ctx.action_class("main")
class MainActions:
    @staticmethod
    def mouse_click(button: int = 0):
        native_input = get_input()
        if native_input.button_pressed(button):
            return
        _run(lambda: native_input.click(button))

    @staticmethod
    def mouse_drag(button: int = 0):
        native_input = get_input()
        if native_input.button_pressed(button):
            return
        _run(lambda: native_input.button(button, True))

    @staticmethod
    def mouse_release(button: int = 0):
        _run(lambda: get_input().button(button, False))

    @staticmethod
    def mouse_move(x: float, y: float):
        rects = [
            (screen.rect.x, screen.rect.y, screen.rect.width, screen.rect.height)
            for screen in ui.screens()
        ]
        nx, ny = normalize_point(desktop_bounds_from_rects(rects), x, y)
        _run(lambda: get_input().move(nx, ny))

    @staticmethod
    def mouse_scroll(y: float = 0.0, x: float = 0.0, by_lines: bool = False):
        if by_lines:
            _scroll_lines(y, x)
        else:
            _scroll(y, x)


@ctx.action_class("user")
class UserActions:
    @staticmethod
    def native_scroll(vertical: float = 0, horizontal: float = 0):
        vertical *= settings.get("user.mouse_wheel_down_amount")
        horizontal *= settings.get("user.mouse_wheel_horizontal_amount")
        _scroll(vertical, horizontal)

    @staticmethod
    def native_modified_click(modifiers: str, button: int = 0):
        _run(
            lambda: get_input().modified_click(
                parse_keys(f"{modifiers}:down"),
                parse_keys(f"{modifiers}:up"),
                button,
            )
        )

    @staticmethod
    def mouse_scroll_up(amount: float = 1):
        actions.user.native_scroll(-amount)

    @staticmethod
    def mouse_scroll_down(amount: float = 1):
        actions.user.native_scroll(amount)

    @staticmethod
    def mouse_scroll_left(amount: float = 1):
        actions.user.native_scroll(0, -amount)

    @staticmethod
    def mouse_scroll_right(amount: float = 1):
        actions.user.native_scroll(0, amount)

    @staticmethod
    def mouse_drag_end() -> bool:
        released = False

        def release() -> None:
            nonlocal released
            released = get_input().release_buttons()

        _run(release)
        return released

    @staticmethod
    def mouse_drag_toggle(button: int):
        if get_input().button_pressed(button):
            actions.mouse_release(button)
        else:
            actions.mouse_drag(button)
