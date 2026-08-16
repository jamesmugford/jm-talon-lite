"""Talon integration for the in-process Wayland input runtime."""

import os
import sys

from talon import Context, Module, actions, app

from .wayland_backend.runtime import WaylandRuntime

mod = Module()
ctx = Context()
ctx.matches = "os: linux"
_RUNTIME_KEY = "_jm_talon_lite_wayland_runtime"
# The sys slot survives Talon reloads, so stop its previous owner thread first.
_previous_runtime = getattr(sys, _RUNTIME_KEY, None)
if _previous_runtime is not None:
    _previous_runtime.stop()
_runtime = WaylandRuntime()
setattr(sys, _RUNTIME_KEY, _runtime)


@mod.action_class
class Actions:
    def wayland_runtime_start() -> None:
        """Start Wayland discovery and virtual input."""
        _runtime.start()
        print(f"Wayland runtime started: {_runtime.status()}")

    def wayland_runtime_stop() -> None:
        """Stop the Wayland runtime."""
        _runtime.stop()
        print("Wayland runtime stopped")

    def wayland_runtime_status() -> str:
        """Return the Wayland runtime status."""
        return str(_runtime.status())

    def wayland_pointer_move_absolute(x: float, y: float) -> None:
        """Move the staged pointer to normalized 0..1 desktop coordinates."""
        _runtime.pointer_move_absolute(x, y)

    def wayland_pointer_move_relative(dx: float, dy: float) -> None:
        """Move the staged pointer by a relative compositor-space delta."""
        _runtime.pointer_move_relative(dx, dy)

    def wayland_pointer_button_down(button: int = 0) -> None:
        """Press a button with the staged virtual pointer."""
        _runtime.pointer_button_down(button)

    def wayland_pointer_button_up(button: int = 0) -> None:
        """Release a button with the staged virtual pointer."""
        _runtime.pointer_button_up(button)

    def wayland_pointer_click(button: int = 0) -> None:
        """Click a button with the staged virtual pointer."""
        _runtime.pointer_click(button)

    def wayland_pointer_scroll(
        vertical_steps: int = 0, horizontal_steps: int = 0
    ) -> None:
        """Scroll discrete steps with the staged virtual pointer."""
        _runtime.pointer_scroll(vertical_steps, horizontal_steps)

    def wayland_pointer_modified_click(
        modifiers: str, button: int = 0
    ) -> None:
        """Click the native pointer while holding Talon modifiers."""
        _runtime.pointer_modified_click(modifiers, button)


@ctx.action_class("main")
class MainActions:
    def key(key: str):
        """Send Talon key syntax through the native Wayland keyboard."""
        if not _is_wayland():
            actions.next(key)
            return
        _runtime.key(key)


def _is_wayland() -> bool:
    return bool(
        os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("SWAYSOCK")
        or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def _on_ready() -> None:
    if not _is_wayland():
        return
    try:
        _runtime.start()
    except Exception as exc:
        print(f"Wayland runtime startup failed: {exc}", file=sys.stderr, flush=True)


app.register("ready", _on_ready)
