"""Talon integration for the in-process Wayland input runtime."""

import os
import sys
import threading

from talon import Context, Module, actions, app, cron, registry, scope

from .wayland_backend.runtime import ToplevelSnapshot, WaylandRuntime

mod = Module()
ctx = Context()
ctx.matches = "os: linux"
_RUNTIME_KEY = "_jm_talon_lite_wayland_runtime"
_CONTEXT_JOB_KEY = "_jm_talon_lite_wayland_context_job"
_SCOPE_ORIGINALS_KEY = "_jm_talon_lite_wayland_scope_originals"


def _is_wayland() -> bool:
    return bool(
        os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("SWAYSOCK")
        or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


# The sys slot survives Talon reloads, so stop its previous owner thread first.
_previous_runtime = getattr(sys, _RUNTIME_KEY, None)
if _previous_runtime is not None:
    _previous_runtime.stop()

_previous_context_job = getattr(sys, _CONTEXT_JOB_KEY, None)
if _previous_context_job is not None:
    cron.cancel(_previous_context_job)
    delattr(sys, _CONTEXT_JOB_KEY)

_app_scope_decl = None
_win_scope_decl = None
_scope_originals = getattr(sys, _SCOPE_ORIGINALS_KEY, None)


def _initialize_scope_declarations() -> None:
    global _app_scope_decl, _scope_originals, _win_scope_decl
    _app_scope_decl = scope.scopes["app"]
    _win_scope_decl = scope.scopes["win"]
    if _scope_originals is None:
        _scope_originals = (_app_scope_decl.func, _win_scope_decl.func)
        setattr(sys, _SCOPE_ORIGINALS_KEY, _scope_originals)
        return
    _app_scope_decl.func, _win_scope_decl.func = _scope_originals
    _app_scope_decl.update()
    _win_scope_decl.update()

_context_lock = threading.Lock()
_context_job = None
_context_job_clears = False
_latest_toplevel: ToplevelSnapshot | None = None
_active_toplevel: ToplevelSnapshot | None = None
_active_apps: set[str] = set()
_context_available = False


def _active_app_name() -> str:
    if _active_toplevel is None or not _active_toplevel.app_id:
        return ""
    app_id = _active_toplevel.app_id
    return app_id[0].upper() + app_id[1:]


def _app_scope() -> dict:
    name = _active_app_name()
    return {
        "app": set(_active_apps),
        "name": name,
        "bundle": "",
        "path": "",
        "exe": "",
        "exe_path": "",
    }


def _win_scope() -> dict:
    title = "" if _active_toplevel is None else _active_toplevel.title
    return {
        "title": title,
        "doc": "",
        "filename": "",
        "file_ext": "",
    }


def _has_toplevel_manager() -> bool:
    return any(
        name == "zwlr_foreign_toplevel_manager_v1"
        for name, _version in _runtime.status().globals
    )


def _install_scope_providers() -> None:
    global _context_available
    if _context_available:
        return
    _app_scope_decl.func = _app_scope
    _win_scope_decl.func = _win_scope
    _context_available = True
    _app_scope_decl.update()
    _win_scope_decl.update()


def _restore_scope_providers() -> None:
    global _context_available
    if not _context_available:
        return
    _app_scope_decl.func, _win_scope_decl.func = _scope_originals
    _context_available = False
    _app_scope_decl.update()
    _win_scope_decl.update()


def _refresh_app_scope() -> None:
    global _active_apps
    app_id = "" if _active_toplevel is None else _active_toplevel.app_id
    _active_apps = {app_id, app_id.casefold()} if app_id else set()
    _app_scope_decl.update()
    matched_apps = {
        name
        for name, declarations in registry.decls.apps.items()
        if any(declaration.is_active() for declaration in declarations)
    }
    if not matched_apps.issubset(_active_apps):
        _active_apps |= matched_apps
        _app_scope_decl.update()


def _apply_active_toplevel() -> None:
    global _active_toplevel, _context_job, _context_job_clears
    with _context_lock:
        snapshot = _latest_toplevel
        job = _context_job
        _context_job = None
        _context_job_clears = False
        if job is not None and getattr(sys, _CONTEXT_JOB_KEY, None) == job:
            delattr(sys, _CONTEXT_JOB_KEY)

    previous = _active_toplevel
    _active_toplevel = snapshot
    if not _has_toplevel_manager():
        _restore_scope_providers()
        return
    _install_scope_providers()
    _win_scope_decl.update()
    _refresh_app_scope()
    previous_key = (
        None if previous is None else (previous.app_id, previous.title)
    )
    snapshot_key = (
        None if snapshot is None else (snapshot.app_id, snapshot.title)
    )
    if snapshot_key != previous_key:
        app_id, title = ("", "") if snapshot is None else snapshot_key
        print(
            f"Wayland context: app={app_id!r} title={title!r}",
            flush=True,
        )


def _queue_active_toplevel(snapshot: ToplevelSnapshot | None) -> None:
    global _context_job, _context_job_clears, _latest_toplevel
    with _context_lock:
        _latest_toplevel = snapshot
        if _context_job is not None:
            if snapshot is not None and not _context_job_clears:
                return
            cron.cancel(_context_job)
        _context_job_clears = snapshot is None
        delay = "20ms" if _context_job_clears else "0ms"
        _context_job = cron.after(delay, _apply_active_toplevel)
        setattr(sys, _CONTEXT_JOB_KEY, _context_job)


_runtime = WaylandRuntime(
    on_active_toplevel=_queue_active_toplevel if _is_wayland() else None
)
setattr(sys, _RUNTIME_KEY, _runtime)


@mod.action_class
class Actions:
    def wayland_pointer_move_absolute(
        x: float, y: float, refresh_hover: bool = False
    ) -> None:
        """Move the pointer to normalized 0..1 desktop coordinates."""
        _runtime.pointer_move_absolute(x, y, refresh_hover=refresh_hover)

    def wayland_pointer_move_relative(dx: float, dy: float) -> None:
        """Move the pointer by a relative compositor-space delta."""
        _runtime.pointer_move_relative(dx, dy)

    def wayland_pointer_button_down(button: int = 0) -> None:
        """Press a button with the virtual pointer."""
        _runtime.pointer_button_down(button)

    def wayland_pointer_button_up(button: int = 0) -> None:
        """Release a button with the virtual pointer."""
        _runtime.pointer_button_up(button)

    def wayland_pointer_click(button: int = 0) -> None:
        """Click a button with the virtual pointer."""
        _runtime.pointer_click(button)

    def wayland_pointer_button_toggle(button: int = 0) -> bool:
        """Toggle a button with the virtual pointer."""
        return _runtime.pointer_button_toggle(button)

    def wayland_pointer_release_all() -> bool:
        """Release every button held by the virtual pointer."""
        return _runtime.pointer_release_all()

    def wayland_pointer_scroll(
        vertical_steps: int = 0, horizontal_steps: int = 0
    ) -> None:
        """Scroll discrete steps with the virtual pointer."""
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


@ctx.action_class("app")
class AppActions:
    def name() -> str:
        if not _is_wayland() or not _context_available:
            return actions.next()
        return _active_app_name()

    def executable() -> str:
        if not _is_wayland() or not _context_available:
            return actions.next()
        return ""

    def bundle() -> str:
        if not _is_wayland() or not _context_available:
            return actions.next()
        return ""


@ctx.action_class("win")
class WinActions:
    def title() -> str:
        if not _is_wayland() or not _context_available:
            return actions.next()
        return "" if _active_toplevel is None else _active_toplevel.title


def _on_ready() -> None:
    if not _is_wayland():
        return
    try:
        _initialize_scope_declarations()
        _runtime.start()
        if _has_toplevel_manager():
            _install_scope_providers()
        registry.register("update_decls", _on_declarations_updated)
    except Exception as exc:
        _restore_scope_providers()
        print(f"Wayland runtime startup failed: {exc}", file=sys.stderr, flush=True)


def _on_declarations_updated(_declarations) -> None:
    if _context_available:
        _refresh_app_scope()


def _on_quit() -> None:
    _restore_scope_providers()


app.register("ready", _on_ready)
app.register("quit", _on_quit)
