"""Single-owner-thread Wayland registry and toplevel runtime."""

from __future__ import annotations

import errno
import selectors
import socket
import struct
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass(frozen=True)
class ToplevelSnapshot:
    id: int
    title: str
    app_id: str
    states: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeStatus:
    running: bool
    globals: tuple[tuple[str, int], ...]
    toplevels: tuple[ToplevelSnapshot, ...]
    error: str | None


@dataclass
class _PendingToplevel:
    id: int
    title: str = ""
    app_id: str = ""
    states: tuple[str, ...] = field(default_factory=tuple)


_STATE_NAMES = {
    0: "maximized",
    1: "minimized",
    2: "activated",
    3: "fullscreen",
}


def decode_toplevel_states(payload: bytes) -> tuple[str, ...]:
    """Decode the native-endian uint32 array used by the wlr protocol."""
    if len(payload) % 4:
        raise ValueError("Toplevel state payload is not uint32-aligned")
    values = struct.unpack(f"={len(payload) // 4}I", payload)
    return tuple(_STATE_NAMES.get(value, f"unknown:{value}") for value in values)


def _load_bindings() -> SimpleNamespace:
    from .vendor import activate

    activate()
    from pywayland import ffi, lib
    from pywayland.client import Display
    from pywayland.protocol.virtual_keyboard_unstable_v1 import (
        ZwpVirtualKeyboardManagerV1,
    )
    from pywayland.protocol.wlr_foreign_toplevel_management_unstable_v1 import (
        ZwlrForeignToplevelManagerV1,
    )
    from pywayland.protocol.wlr_virtual_pointer_unstable_v1 import (
        ZwlrVirtualPointerManagerV1,
    )

    if not hasattr(lib, "wl_display_cancel_read"):
        raise RuntimeError("Bundled PyWayland is missing wl_display_cancel_read")

    return SimpleNamespace(
        Display=Display,
        ffi=ffi,
        lib=lib,
        interfaces={
            ZwlrForeignToplevelManagerV1.name: ZwlrForeignToplevelManagerV1,
            ZwlrVirtualPointerManagerV1.name: ZwlrVirtualPointerManagerV1,
            ZwpVirtualKeyboardManagerV1.name: ZwpVirtualKeyboardManagerV1,
        },
    )


class WaylandRuntime:
    """Own a Wayland display and all its proxies on one worker thread."""

    def __init__(self) -> None:
        self._lifecycle_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._ready = threading.Event()
        self._running = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._wake_read: socket.socket | None = None
        self._wake_write: socket.socket | None = None
        self._error: str | None = None
        self._globals: dict[str, int] = {}
        self._snapshots: dict[int, ToplevelSnapshot] = {}
        self._handles: dict[Any, _PendingToplevel] = {}
        self._proxies: dict[str, tuple[int, Any]] = {}
        self._announced_globals: dict[int, tuple[str, int]] = {}
        self._next_toplevel_id = 1
        self._bindings: SimpleNamespace | None = None
        self._display: Any = None
        self._registry: Any = None
        self._sync_callback: Any = None

    def start(self, timeout: float = 5.0) -> None:
        """Start the owner thread and wait for registry initialization."""
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                ready = self._ready
            else:
                self._close_wakeup()
                self._ready.clear()
                self._running.clear()
                self._stopping.clear()
                with self._state_lock:
                    self._error = None
                    self._globals.clear()
                    self._snapshots.clear()
                self._handles.clear()
                self._proxies.clear()
                self._announced_globals.clear()
                self._next_toplevel_id = 1
                self._wake_read, self._wake_write = socket.socketpair()
                self._wake_read.setblocking(False)
                self._wake_write.setblocking(False)
                self._thread = threading.Thread(
                    target=self._run,
                    name="talon-wayland-owner",
                    daemon=True,
                )
                self._thread.start()
                ready = self._ready

        if not ready.wait(timeout):
            self.stop(timeout=timeout)
            raise TimeoutError("Timed out starting the Wayland runtime")

        with self._state_lock:
            error = self._error
        if error is not None:
            self.stop(timeout=timeout)
            raise RuntimeError(error)

    def stop(self, timeout: float = 5.0) -> None:
        """Wake and join the owner thread. Safe to call more than once."""
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                self._close_wakeup()
                return
            self._stopping.set()
            self._wake()
            if thread is not threading.current_thread():
                thread.join(timeout)
                if thread.is_alive():
                    raise TimeoutError("Timed out stopping the Wayland runtime")
            if self._thread is thread:
                self._thread = None
            self._close_wakeup()

    def status(self) -> RuntimeStatus:
        with self._state_lock:
            return RuntimeStatus(
                running=self._running.is_set(),
                globals=tuple(sorted(self._globals.items())),
                toplevels=tuple(
                    self._snapshots[key] for key in sorted(self._snapshots)
                ),
                error=self._error,
            )

    def _close_wakeup(self) -> None:
        for sock in (self._wake_read, self._wake_write):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._wake_read = None
        self._wake_write = None

    def _wake(self) -> None:
        writer = self._wake_write
        if writer is not None:
            try:
                writer.send(b"\0")
            except (BlockingIOError, OSError):
                pass

    def _record_failure(self, exc: Exception) -> None:
        with self._state_lock:
            if self._error is None:
                self._error = f"{type(exc).__name__}: {exc}"
        self._stopping.set()
        self._ready.set()
        self._wake()

    def _guard_callback(self, callback: Callable[..., None]) -> Callable[..., None]:
        def guarded(*args: Any) -> None:
            try:
                callback(*args)
            except Exception as exc:
                self._record_failure(exc)
                traceback.print_exc()

        return guarded

    def _run(self) -> None:
        try:
            self._bindings = _load_bindings()
            self._connect()
            self._running.set()
            self._event_loop()
        except Exception as exc:
            self._record_failure(exc)
            traceback.print_exc()
        finally:
            self._running.clear()
            self._ready.set()
            try:
                self._disconnect()
            except Exception as exc:
                self._record_failure(exc)
                traceback.print_exc()
            finally:
                self._close_wakeup()

    def _connect(self) -> None:
        assert self._bindings is not None
        display = self._bindings.Display()
        display.connect()
        self._display = display
        registry = display.get_registry()
        registry.dispatcher["global"] = self._guard_callback(self._on_global)
        registry.dispatcher["global_remove"] = self._guard_callback(
            self._on_global_remove
        )
        # PyWayland keeps display children weakly; retain the registry so new_id
        # events can continue resolving their owning display after cyclic GC.
        self._registry = registry
        self._request_initial_sync()

    def _request_initial_sync(self) -> None:
        callback = self._display.sync()
        callback.dispatcher["done"] = self._guard_callback(self._on_registry_sync)
        self._sync_callback = callback

    def _on_registry_sync(self, callback: Any, _callback_data: int) -> None:
        callback._destroy()
        if self._stopping.is_set():
            return
        callback = self._display.sync()
        callback.dispatcher["done"] = self._guard_callback(self._on_bindings_sync)
        self._sync_callback = callback

    def _on_bindings_sync(self, callback: Any, _callback_data: int) -> None:
        callback._destroy()
        self._sync_callback = None
        self._ready.set()

    def _on_global(
        self, registry: Any, name: int, interface_name: str, version: int
    ) -> None:
        assert self._bindings is not None
        interface = self._bindings.interfaces.get(interface_name)
        if interface is None:
            return

        self._announced_globals[name] = (interface_name, version)
        if interface_name in self._proxies:
            return
        self._bind_global(registry, name, interface_name, version)

    def _bind_global(
        self, registry: Any, name: int, interface_name: str, version: int
    ) -> None:
        assert self._bindings is not None
        interface = self._bindings.interfaces[interface_name]
        negotiated_version = min(version, interface.version)
        proxy = registry.bind(name, interface, negotiated_version)
        self._proxies[interface_name] = (name, proxy)
        with self._state_lock:
            self._globals[interface_name] = negotiated_version

        if interface_name == "zwlr_foreign_toplevel_manager_v1":
            proxy.dispatcher["toplevel"] = self._guard_callback(self._on_toplevel)
            proxy.dispatcher["finished"] = self._guard_callback(
                self._on_toplevel_manager_finished
            )

    def _on_global_remove(self, registry: Any, name: int) -> None:
        announcement = self._announced_globals.pop(name, None)
        if announcement is None:
            return
        interface_name, _version = announcement
        entry = self._proxies.get(interface_name)
        if entry is None or entry[0] != name:
            return

        _global_name, proxy = self._proxies.pop(interface_name)
        with self._state_lock:
            self._globals.pop(interface_name, None)
        if interface_name == "zwlr_foreign_toplevel_manager_v1":
            for handle in tuple(self._handles):
                if not handle.destroyed:
                    handle.destroy()
            self._handles.clear()
            with self._state_lock:
                self._snapshots.clear()
            proxy._destroy()
        elif not proxy.destroyed:
            proxy.destroy()

        for candidate_name, (candidate_interface, candidate_version) in (
            self._announced_globals.items()
        ):
            if candidate_interface == interface_name:
                self._bind_global(
                    registry,
                    candidate_name,
                    candidate_interface,
                    candidate_version,
                )
                break

    def _on_toplevel(self, _manager: Any, handle: Any) -> None:
        pending = _PendingToplevel(self._next_toplevel_id)
        self._next_toplevel_id += 1
        self._handles[handle] = pending
        handle.dispatcher["title"] = self._guard_callback(self._on_toplevel_title)
        handle.dispatcher["app_id"] = self._guard_callback(self._on_toplevel_app_id)
        handle.dispatcher["state"] = self._guard_callback(self._on_toplevel_state)
        handle.dispatcher["done"] = self._guard_callback(self._on_toplevel_done)
        handle.dispatcher["closed"] = self._guard_callback(self._on_toplevel_closed)

    def _on_toplevel_title(self, handle: Any, title: str) -> None:
        self._handles[handle].title = title

    def _on_toplevel_app_id(self, handle: Any, app_id: str) -> None:
        self._handles[handle].app_id = app_id

    def _on_toplevel_state(self, handle: Any, payload: bytes) -> None:
        self._handles[handle].states = decode_toplevel_states(payload)

    def _on_toplevel_done(self, handle: Any) -> None:
        pending = self._handles[handle]
        snapshot = ToplevelSnapshot(
            pending.id,
            pending.title,
            pending.app_id,
            pending.states,
        )
        with self._state_lock:
            self._snapshots[pending.id] = snapshot

    def _on_toplevel_closed(self, handle: Any) -> None:
        pending = self._handles.pop(handle, None)
        if pending is not None:
            with self._state_lock:
                self._snapshots.pop(pending.id, None)
        if not handle.destroyed:
            handle.destroy()

    def _on_toplevel_manager_finished(self, manager: Any) -> None:
        interface_name = "zwlr_foreign_toplevel_manager_v1"
        entry = self._proxies.get(interface_name)
        if entry is not None and entry[1] is manager:
            self._proxies.pop(interface_name, None)
            with self._state_lock:
                self._globals.pop(interface_name, None)
        manager._destroy()

    def _event_loop(self) -> None:
        assert self._bindings is not None
        assert self._display is not None
        assert self._wake_read is not None
        ffi = self._bindings.ffi
        lib = self._bindings.lib
        display = self._display
        display_fd = display.get_fd()

        with selectors.DefaultSelector() as selector:
            selector.register(self._wake_read, selectors.EVENT_READ, "wake")
            selector.register(display_fd, selectors.EVENT_READ, "display")

            while not self._stopping.is_set():
                while lib.wl_display_prepare_read(display._ptr) != 0:
                    display.dispatch(block=False)

                prepared = True
                try:
                    events = selectors.EVENT_READ
                    flush_result = display.flush()
                    if flush_result == -1:
                        if ffi.errno != errno.EAGAIN:
                            raise OSError(ffi.errno, "wl_display_flush failed")
                        events |= selectors.EVENT_WRITE
                    selector.modify(display_fd, events, "display")

                    selected = selector.select()
                    display_events = 0
                    for key, mask in selected:
                        if key.data == "wake":
                            self._drain_wakeup()
                        else:
                            display_events |= mask

                    if self._stopping.is_set():
                        lib.wl_display_cancel_read(display._ptr)
                        prepared = False
                        break

                    if display_events & selectors.EVENT_READ:
                        read_result = lib.wl_display_read_events(display._ptr)
                        prepared = False
                        if read_result == -1:
                            error = lib.wl_display_get_error(display._ptr)
                            raise RuntimeError(f"Wayland read failed with error {error}")
                        display.dispatch(block=False)
                    else:
                        lib.wl_display_cancel_read(display._ptr)
                        prepared = False
                finally:
                    if prepared:
                        lib.wl_display_cancel_read(display._ptr)

    def _drain_wakeup(self) -> None:
        assert self._wake_read is not None
        while True:
            try:
                if not self._wake_read.recv(4096):
                    return
            except BlockingIOError:
                return

    def _disconnect(self) -> None:
        display = self._display
        if display is None:
            return
        try:
            for handle in tuple(self._handles):
                if not handle.destroyed:
                    handle.destroy()
            manager_entry = self._proxies.get("zwlr_foreign_toplevel_manager_v1")
            if manager_entry is not None and not manager_entry[1].destroyed:
                manager_entry[1].stop()
            try:
                display.flush()
            except Exception:
                pass
        finally:
            try:
                display.disconnect()
            finally:
                self._display = None
                self._registry = None
                self._sync_callback = None
                self._handles.clear()
                self._proxies.clear()
                self._announced_globals.clear()
                with self._state_lock:
                    self._globals.clear()
                    self._snapshots.clear()
