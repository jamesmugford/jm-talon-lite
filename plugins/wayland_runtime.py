"""Talon actions for the staged in-process Wayland runtime."""

import sys

from talon import Module

from .wayland_backend.runtime import WaylandRuntime

mod = Module()
_RUNTIME_KEY = "_jm_talon_lite_wayland_runtime"
# Talon reloads modules in-process, so stop the previous owner thread first.
_previous_runtime = getattr(sys, _RUNTIME_KEY, None)
if _previous_runtime is not None:
    _previous_runtime.stop()
_runtime = WaylandRuntime()
setattr(sys, _RUNTIME_KEY, _runtime)


@mod.action_class
class Actions:
    def wayland_runtime_start() -> None:
        """Start staged Wayland discovery and pointer diagnostics."""
        _runtime.start()
        print(f"Wayland runtime started: {_runtime.status()}")

    def wayland_runtime_stop() -> None:
        """Stop the staged Wayland runtime."""
        _runtime.stop()
        print("Wayland runtime stopped")

    def wayland_runtime_status() -> str:
        """Return the staged Wayland runtime status."""
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
