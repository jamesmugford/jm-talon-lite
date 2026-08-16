"""Talon actions for the staged in-process Wayland runtime."""

import sys

from talon import Module

from .wayland_backend.runtime import WaylandRuntime

mod = Module()
_RUNTIME_KEY = "_jm_talon_lite_wayland_runtime"
_previous_runtime = getattr(sys, _RUNTIME_KEY, None)
if _previous_runtime is not None:
    _previous_runtime.stop()
_runtime = WaylandRuntime()
setattr(sys, _RUNTIME_KEY, _runtime)


@mod.action_class
class Actions:
    def wayland_runtime_start() -> None:
        """Start the staged Wayland registry and toplevel runtime."""
        _runtime.start()
        print(f"Wayland runtime started: {_runtime.status()}")

    def wayland_runtime_stop() -> None:
        """Stop the staged Wayland runtime."""
        _runtime.stop()
        print("Wayland runtime stopped")

    def wayland_runtime_status() -> str:
        """Return the staged Wayland runtime status."""
        return str(_runtime.status())
