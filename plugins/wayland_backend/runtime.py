"""Single-owner-thread Wayland registry, toplevel, and virtual-input runtime."""

from __future__ import annotations

import errno
import math
import os
import selectors
import socket
import struct
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from .keyboard import (
    KEYMAP_FORMAT_XKB_V1,
    KeyStroke,
    XkbKeymap,
    create_keymap_fd,
    parse_key_spec,
    read_keymap_fd,
    validate_keycode,
)
from .pointer import (
    POINTER_EXTENT,
    linux_button_code,
    normalized_to_extent,
    validate_int32,
    validate_wayland_fixed,
)


@dataclass(frozen=True)
class ToplevelSnapshot:
    id: int
    title: str
    app_id: str
    states: tuple[str, ...]


@dataclass(frozen=True)
class SeatSnapshot:
    global_name: int
    name: str
    capabilities: tuple[str, ...]
    selected: bool


@dataclass(frozen=True)
class RuntimeStatus:
    running: bool
    globals: tuple[tuple[str, int], ...]
    toplevels: tuple[ToplevelSnapshot, ...]
    seats: tuple[SeatSnapshot, ...]
    virtual_pointer_ready: bool
    virtual_keyboard_ready: bool
    error: str | None


@dataclass
class _PendingToplevel:
    id: int
    title: str = ""
    app_id: str = ""
    states: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class _Seat:
    global_name: int
    version: int
    proxy: Any
    name: str = ""
    capabilities: int = 0
    keyboard: Any = None
    keymap: bytes | None = None
    locked_modifiers: int = 0
    group: int = 0


@dataclass
class _Command:
    callback: Callable[[], Any]
    done: threading.Event = field(default_factory=threading.Event)
    # Transitions under _command_lock: queued -> claimed -> done,
    # queued -> cancelled -> done, or queued -> done on failure or shutdown.
    state: str = "queued"
    result: Any = None
    error: Exception | None = None


_STATE_NAMES = {
    0: "maximized",
    1: "minimized",
    2: "activated",
    3: "fullscreen",
}
_SEAT_CAPABILITY_NAMES = {
    1: "pointer",
    2: "keyboard",
    4: "touch",
}
_TOPLEVEL_MANAGER = "zwlr_foreign_toplevel_manager_v1"
_VIRTUAL_POINTER_MANAGER = "zwlr_virtual_pointer_manager_v1"
_VIRTUAL_KEYBOARD_MANAGER = "zwp_virtual_keyboard_manager_v1"
_SEAT_INTERFACE = "wl_seat"
_SEAT_CAPABILITY_KEYBOARD = 2
_AXIS_VERTICAL = 0
_AXIS_HORIZONTAL = 1
_AXIS_SOURCE_WHEEL = 0
_BUTTON_RELEASED = 0
_BUTTON_PRESSED = 1
_KEY_RELEASED = 0
_KEY_PRESSED = 1
_SCROLL_DISTANCE_PER_STEP = 15.0
_DISCONNECT_FLUSH_TIMEOUT = 0.25


def decode_toplevel_states(payload: bytes) -> tuple[str, ...]:
    """Decode the native-endian uint32 array used by the wlr protocol."""
    if len(payload) % 4:
        raise ValueError("Toplevel state payload is not uint32-aligned")
    values = struct.unpack(f"={len(payload) // 4}I", payload)
    return tuple(_STATE_NAMES.get(value, f"unknown:{value}") for value in values)


def _validate_timeout(timeout: float) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("Timeout must be a number")
    if isinstance(timeout, float) and not math.isfinite(timeout):
        raise ValueError("Timeout must be finite")
    if timeout <= 0 or timeout > threading.TIMEOUT_MAX:
        raise ValueError("Timeout must be positive and within threading.TIMEOUT_MAX")
    return float(timeout)


def _load_bindings() -> SimpleNamespace:
    from .vendor import activate

    activate()
    from pywayland import ffi, lib
    from pywayland.client import Display
    from pywayland.protocol.wayland import WlSeat
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
            WlSeat.name: WlSeat,
        },
    )


class WaylandRuntime:
    """Own a Wayland display and all its proxies on one worker thread."""

    def __init__(self) -> None:
        self._lifecycle_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._command_lock = threading.Lock()
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
        self._seats: dict[int, _Seat] = {}
        self._selected_seat_global: int | None = None
        self._virtual_pointer: Any = None
        self._pressed_pointer_buttons: set[int] = set()
        self._virtual_keyboard: Any = None
        self._virtual_keyboard_keymap: bytes | None = None
        self._xkb_keymap: XkbKeymap | None = None
        self._pressed_keyboard_keys: list[int] = []
        self._commands: deque[_Command] = deque()
        self._next_toplevel_id = 1
        self._bindings: SimpleNamespace | None = None
        self._display: Any = None
        self._registry: Any = None
        self._sync_callback: Any = None
        self._initialized = False
        self._owner_thread_id: int | None = None

    def start(self, timeout: float = 5.0) -> None:
        """Start the owner thread and wait for registry initialization."""
        timeout = _validate_timeout(timeout)
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
                    self._seats.clear()
                    self._selected_seat_global = None
                    self._virtual_pointer = None
                    self._virtual_keyboard = None
                    self._virtual_keyboard_keymap = None
                    self._xkb_keymap = None
                self._handles.clear()
                self._proxies.clear()
                self._announced_globals.clear()
                self._pressed_pointer_buttons.clear()
                self._pressed_keyboard_keys.clear()
                with self._command_lock:
                    self._commands.clear()
                self._next_toplevel_id = 1
                self._initialized = False
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
        timeout = _validate_timeout(timeout)
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                self._close_wakeup()
                return
            self._stopping.set()
            self._fail_pending_commands(RuntimeError("Wayland runtime is stopping"))
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
                seats=tuple(
                    SeatSnapshot(
                        global_name=seat.global_name,
                        name=seat.name or f"global-{seat.global_name}",
                        capabilities=tuple(
                            capability_name
                            for capability, capability_name in (
                                _SEAT_CAPABILITY_NAMES.items()
                            )
                            if seat.capabilities & capability
                        ),
                        selected=seat.global_name == self._selected_seat_global,
                    )
                    for seat in sorted(
                        self._seats.values(), key=lambda item: item.global_name
                    )
                ),
                virtual_pointer_ready=self._virtual_pointer is not None,
                virtual_keyboard_ready=(
                    self._virtual_keyboard is not None
                    and self._virtual_keyboard_keymap is not None
                    and self._xkb_keymap is not None
                ),
                error=self._error,
            )

    def pointer_move_absolute(
        self, x: float, y: float, timeout: float = 1.0
    ) -> None:
        """Move the virtual pointer to normalized desktop coordinates."""
        x_value, y_value = normalized_to_extent(x, y)
        self._submit(
            lambda: self._emit_pointer_absolute(x_value, y_value),
            timeout,
        )

    def pointer_move_relative(
        self, dx: float, dy: float, timeout: float = 1.0
    ) -> None:
        """Move the virtual pointer by a relative compositor-space delta."""
        dx = validate_wayland_fixed(dx, "Pointer x delta")
        dy = validate_wayland_fixed(dy, "Pointer y delta")
        self._submit(lambda: self._emit_pointer_relative(dx, dy), timeout)

    def pointer_button_down(self, button: int = 0, timeout: float = 1.0) -> None:
        """Press a supported Talon mouse button."""
        button_code = linux_button_code(button)
        self._submit(
            lambda: self._emit_pointer_button(button_code, pressed=True),
            timeout,
        )

    def pointer_button_up(self, button: int = 0, timeout: float = 1.0) -> None:
        """Release a supported Talon mouse button."""
        button_code = linux_button_code(button)
        self._submit(
            lambda: self._emit_pointer_button(button_code, pressed=False),
            timeout,
        )

    def pointer_click(self, button: int = 0, timeout: float = 1.0) -> None:
        """Press and release a supported Talon mouse button."""
        button_code = linux_button_code(button)
        self._submit(lambda: self._emit_pointer_click(button_code), timeout)

    def pointer_scroll(
        self,
        vertical_steps: int = 0,
        horizontal_steps: int = 0,
        timeout: float = 1.0,
    ) -> None:
        """Emit discrete wheel steps; positive vertical values scroll down."""
        vertical_steps = validate_int32(vertical_steps, "Vertical scroll steps")
        horizontal_steps = validate_int32(horizontal_steps, "Horizontal scroll steps")
        validate_wayland_fixed(
            vertical_steps * _SCROLL_DISTANCE_PER_STEP,
            "Vertical scroll distance",
        )
        validate_wayland_fixed(
            horizontal_steps * _SCROLL_DISTANCE_PER_STEP,
            "Horizontal scroll distance",
        )
        if vertical_steps == 0 and horizontal_steps == 0:
            self._submit(self._require_virtual_pointer, timeout)
            return
        self._submit(
            lambda: self._emit_pointer_scroll(vertical_steps, horizontal_steps),
            timeout,
        )

    def pointer_modified_click(
        self, modifiers: str, button: int = 0, timeout: float = 1.0
    ) -> None:
        """Click while holding one Talon modifier chord."""
        strokes = parse_key_spec(modifiers)
        if (
            len(strokes) != 1
            or strokes[0].key is not None
            or strokes[0].action != "tap"
        ):
            raise ValueError("Modified click requires one modifier-only chord")
        names = strokes[0].modifiers
        down = (KeyStroke(names, None, "down", 1),)
        up = (KeyStroke(names, None, "up", 1),)
        button_code = linux_button_code(button)
        self._submit(
            lambda: self._emit_pointer_modified_click(down, up, button_code),
            timeout,
        )

    def key(self, key_spec: str, timeout: float = 1.0) -> None:
        """Send a Talon key spec through the virtual keyboard."""
        strokes = parse_key_spec(key_spec)
        if strokes:
            self._submit(lambda: self._emit_key_spec(strokes), timeout)

    def _submit(self, callback: Callable[[], Any], timeout: float) -> Any:
        timeout = _validate_timeout(timeout)
        if not self._running.is_set() or self._stopping.is_set():
            raise RuntimeError("Wayland runtime is not running")
        if threading.get_ident() == self._owner_thread_id:
            return callback()

        command = _Command(callback)
        with self._command_lock:
            if not self._running.is_set() or self._stopping.is_set():
                raise RuntimeError("Wayland runtime is not running")
            self._commands.append(command)
        self._wake()

        if not command.done.wait(timeout):
            with self._command_lock:
                if command.state == "queued":
                    command.state = "cancelled"
                    cancelled = True
                else:
                    cancelled = False
            if cancelled:
                raise TimeoutError("Wayland command was cancelled before execution")
            # Internal command callbacks only marshal nonblocking requests. Once
            # claimed, wait for a definitive result rather than report a timeout
            # while input may still be emitted.
            command.done.wait()
        if command.error is not None:
            raise command.error
        return command.result

    def _drain_commands(self) -> None:
        while True:
            with self._command_lock:
                if not self._commands:
                    return
                command = self._commands.popleft()
                if command.state == "cancelled":
                    cancelled = True
                else:
                    command.state = "claimed"
                    cancelled = False
            if cancelled:
                command.done.set()
                continue
            if self._stopping.is_set():
                command.error = RuntimeError("Wayland runtime is stopping")
                with self._command_lock:
                    command.state = "done"
                command.done.set()
                continue
            try:
                command.result = command.callback()
            except Exception as exc:
                command.error = exc
            finally:
                with self._command_lock:
                    command.state = "done"
                command.done.set()

    def _fail_pending_commands(self, error: Exception) -> None:
        with self._command_lock:
            commands = tuple(self._commands)
            self._commands.clear()
            for command in commands:
                if command.state == "queued":
                    command.error = error
                command.state = "done"
        for command in commands:
            command.done.set()

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
        self._fail_pending_commands(exc)
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
        self._owner_thread_id = threading.get_ident()
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
            self._fail_pending_commands(RuntimeError("Wayland runtime stopped"))
            try:
                self._disconnect()
            except Exception as exc:
                self._record_failure(exc)
                traceback.print_exc()
            finally:
                self._owner_thread_id = None
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
        self._initialized = True
        self._select_seat()
        self._maybe_create_selected_seat_keyboard()
        self._maybe_create_virtual_pointer()
        self._maybe_create_virtual_keyboard()
        self._ready.set()

    def _on_global(
        self, registry: Any, name: int, interface_name: str, version: int
    ) -> None:
        assert self._bindings is not None
        interface = self._bindings.interfaces.get(interface_name)
        if interface is None:
            return

        self._announced_globals[name] = (interface_name, version)
        if interface_name == _SEAT_INTERFACE:
            self._bind_seat(registry, name, version)
            return
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

        if interface_name == _TOPLEVEL_MANAGER:
            proxy.dispatcher["toplevel"] = self._guard_callback(self._on_toplevel)
            proxy.dispatcher["finished"] = self._guard_callback(
                self._on_toplevel_manager_finished
            )
        elif interface_name == _VIRTUAL_POINTER_MANAGER:
            self._maybe_create_virtual_pointer()
        elif interface_name == _VIRTUAL_KEYBOARD_MANAGER:
            self._maybe_create_virtual_keyboard()

    def _bind_seat(self, registry: Any, global_name: int, version: int) -> None:
        assert self._bindings is not None
        interface = self._bindings.interfaces[_SEAT_INTERFACE]
        negotiated_version = min(version, interface.version)
        proxy = registry.bind(global_name, interface, negotiated_version)
        seat = _Seat(global_name, negotiated_version, proxy)
        with self._state_lock:
            self._seats[global_name] = seat
            self._globals[_SEAT_INTERFACE] = max(
                candidate.version for candidate in self._seats.values()
            )

        proxy.dispatcher["name"] = self._guard_callback(
            lambda _proxy, value: self._on_seat_name(global_name, value)
        )
        proxy.dispatcher["capabilities"] = self._guard_callback(
            lambda _proxy, value: self._on_seat_capabilities(global_name, value)
        )
        self._select_seat()

    def _on_seat_name(self, global_name: int, name: str) -> None:
        with self._state_lock:
            seat = self._seats.get(global_name)
            if seat is None:
                return
            seat.name = name
        self._select_seat()

    def _on_seat_capabilities(self, global_name: int, capabilities: int) -> None:
        with self._state_lock:
            seat = self._seats.get(global_name)
            if seat is None:
                return
            had_keyboard = bool(seat.capabilities & _SEAT_CAPABILITY_KEYBOARD)
            has_keyboard = bool(capabilities & _SEAT_CAPABILITY_KEYBOARD)
            seat.capabilities = capabilities
            selected = global_name == self._selected_seat_global
        if not selected or had_keyboard == has_keyboard:
            return
        if has_keyboard:
            self._maybe_create_selected_seat_keyboard()
            return
        self._destroy_virtual_keyboard()
        self._release_seat_keyboard(seat)

    def _select_seat(self) -> None:
        with self._state_lock:
            old_global = self._selected_seat_global
            old_seat = self._seats.get(old_global)
            if self._seats:
                # Prefer the conventional seat0, then the lowest registry ID.
                selected = min(
                    self._seats.values(),
                    key=lambda seat: (seat.name != "seat0", seat.global_name),
                )
                new_global = selected.global_name
            else:
                new_global = None
            self._selected_seat_global = new_global

        if new_global != old_global:
            self._destroy_virtual_keyboard()
            self._destroy_virtual_pointer()
            if old_seat is not None:
                self._release_seat_keyboard(old_seat)
            self._maybe_create_selected_seat_keyboard()
            self._maybe_create_virtual_pointer()
            self._maybe_create_virtual_keyboard()

    def _remove_seat(self, global_name: int) -> None:
        with self._state_lock:
            seat = self._seats.pop(global_name, None)
            was_selected = self._selected_seat_global == global_name
            if self._seats:
                self._globals[_SEAT_INTERFACE] = max(
                    candidate.version for candidate in self._seats.values()
                )
            else:
                self._globals.pop(_SEAT_INTERFACE, None)
        if seat is None:
            return
        if was_selected:
            self._destroy_virtual_keyboard()
            self._destroy_virtual_pointer()
        self._release_seat_keyboard(seat)
        self._release_seat(seat)
        self._select_seat()

    @staticmethod
    def _release_seat(seat: _Seat) -> None:
        if seat.proxy.destroyed:
            return
        if seat.version >= 5:
            seat.proxy.release()
        else:
            seat.proxy._destroy()

    def _maybe_create_selected_seat_keyboard(self) -> None:
        if not self._initialized or self._stopping.is_set():
            return
        with self._state_lock:
            seat = self._seats.get(self._selected_seat_global)
            if (
                seat is None
                or not seat.capabilities & _SEAT_CAPABILITY_KEYBOARD
                or seat.keyboard is not None
            ):
                return
        keyboard = seat.proxy.get_keyboard()
        with self._state_lock:
            seat.keyboard = keyboard
            seat.keymap = None
            seat.locked_modifiers = 0
            seat.group = 0
        keyboard.dispatcher["keymap"] = self._guard_callback(
            lambda source, format, fd, size: self._on_seat_keymap(
                seat.global_name,
                source,
                format,
                fd,
                size,
            )
        )
        def on_modifiers(source, _serial, _depressed, _latched, locked, group):
            # Depressed masks include our own virtual device and would feed back.
            self._on_seat_modifiers(
                seat.global_name,
                source,
                locked,
                group,
            )

        keyboard.dispatcher["modifiers"] = self._guard_callback(on_modifiers)

    def _release_seat_keyboard(self, seat: _Seat) -> None:
        with self._state_lock:
            keyboard = seat.keyboard
            seat.keyboard = None
            seat.keymap = None
        if keyboard is None or keyboard.destroyed:
            return
        if seat.version >= 3:
            keyboard.release()
        else:
            keyboard._destroy()

    def _on_seat_keymap(
        self,
        global_name: int,
        source: Any,
        format: int,
        fd: int,
        size: int,
    ) -> None:
        with self._state_lock:
            seat = self._seats.get(global_name)
            current = seat is not None and seat.keyboard is source
        if not current or self._stopping.is_set():
            if fd >= 0:
                os.close(fd)
            return
        if format != KEYMAP_FORMAT_XKB_V1:
            if fd >= 0:
                os.close(fd)
            with self._state_lock:
                if seat.keyboard is not source:
                    return
                seat.keymap = None
                selected = global_name == self._selected_seat_global
            if selected:
                self._destroy_virtual_keyboard()
            return

        keymap = read_keymap_fd(fd, size)
        with self._state_lock:
            if seat.keyboard is not source:
                return
            unchanged = seat.keymap == keymap
            seat.keymap = keymap
            selected = global_name == self._selected_seat_global
            virtual_keyboard = self._virtual_keyboard
        if not selected:
            return
        if unchanged:
            self._maybe_create_virtual_keyboard()
            return
        if virtual_keyboard is None:
            self._maybe_create_virtual_keyboard()
            return
        self._apply_virtual_keyboard_keymap(seat, virtual_keyboard)

    def _on_seat_modifiers(
        self,
        global_name: int,
        source: Any,
        locked_modifiers: int,
        group: int,
    ) -> None:
        with self._state_lock:
            seat = self._seats.get(global_name)
            if seat is None or seat.keyboard is not source:
                return
            seat.locked_modifiers = locked_modifiers
            seat.group = group
            selected = global_name == self._selected_seat_global
            keyboard = self._virtual_keyboard
            xkb_keymap = self._xkb_keymap
        if not selected:
            return
        if keyboard is None or xkb_keymap is None:
            self._maybe_create_virtual_keyboard()
            return
        modifiers = xkb_keymap.set_external_state(locked_modifiers, group)
        if modifiers is not None:
            keyboard.modifiers(*modifiers)

    def _maybe_create_virtual_keyboard(self) -> None:
        if not self._initialized or self._stopping.is_set():
            return
        with self._state_lock:
            if self._virtual_keyboard is not None:
                return
            seat = self._seats.get(self._selected_seat_global)
            if (
                seat is None
                or seat.keyboard is None
                or seat.keyboard.destroyed
                or seat.keymap is None
            ):
                return
        manager_entry = self._proxies.get(_VIRTUAL_KEYBOARD_MANAGER)
        if manager_entry is None:
            return
        keyboard = manager_entry[1].create_virtual_keyboard(seat.proxy)
        with self._state_lock:
            self._virtual_keyboard = keyboard
            self._virtual_keyboard_keymap = None
        try:
            self._apply_virtual_keyboard_keymap(seat, keyboard)
        except Exception:
            with self._state_lock:
                if self._virtual_keyboard is keyboard:
                    self._virtual_keyboard = None
                    self._virtual_keyboard_keymap = None
            if not keyboard.destroyed:
                keyboard.destroy()
            raise

    def _apply_virtual_keyboard_keymap(self, seat: _Seat, keyboard: Any) -> None:
        keymap = seat.keymap
        if keymap is None:
            raise RuntimeError("Selected Wayland seat has no XKB-v1 keymap")
        with self._state_lock:
            if (
                self._virtual_keyboard is not keyboard
                or self._virtual_keyboard_keymap == keymap
            ):
                return
            self._virtual_keyboard_keymap = None
        xkb_keymap = XkbKeymap(
            keymap,
            locked_modifiers=seat.locked_modifiers,
            group=seat.group,
        )
        try:
            self._release_pressed_keyboard_keys(keyboard)
            fd = create_keymap_fd(keymap)
            try:
                keyboard.keymap(KEYMAP_FORMAT_XKB_V1, fd, len(keymap))
            finally:
                os.close(fd)
            modifiers = xkb_keymap.modifiers()
            if any(modifiers):
                keyboard.modifiers(*modifiers)
        except Exception:
            xkb_keymap.close()
            raise
        old_xkb_keymap = self._xkb_keymap
        self._xkb_keymap = xkb_keymap
        if old_xkb_keymap is not None:
            old_xkb_keymap.close()
        with self._state_lock:
            if self._virtual_keyboard is keyboard:
                self._virtual_keyboard_keymap = keymap

    def _release_pressed_keyboard_keys(self, keyboard: Any) -> None:
        for keycode in reversed(tuple(self._pressed_keyboard_keys)):
            self._send_keyboard_key(keyboard, keycode, pressed=False)

    def _destroy_virtual_keyboard(self) -> None:
        with self._state_lock:
            keyboard = self._virtual_keyboard
            self._virtual_keyboard = None
            self._virtual_keyboard_keymap = None
        xkb_keymap = self._xkb_keymap
        if keyboard is None:
            self._pressed_keyboard_keys.clear()
            if xkb_keymap is not None:
                xkb_keymap.close()
                self._xkb_keymap = None
            return
        try:
            try:
                if not keyboard.destroyed:
                    self._release_pressed_keyboard_keys(keyboard)
            except Exception as release_error:
                try:
                    if not keyboard.destroyed:
                        keyboard.destroy()
                except Exception as destroy_error:
                    release_error.add_note(
                        "Virtual keyboard destroy also failed: "
                        f"{type(destroy_error).__name__}: {destroy_error}"
                    )
                raise
            if not keyboard.destroyed:
                keyboard.destroy()
        finally:
            self._pressed_keyboard_keys.clear()
            if xkb_keymap is not None:
                xkb_keymap.close()
            if self._xkb_keymap is xkb_keymap:
                self._xkb_keymap = None

    def _maybe_create_virtual_pointer(self) -> None:
        if not self._initialized or self._stopping.is_set():
            return
        with self._state_lock:
            if self._virtual_pointer is not None:
                return
            seat = self._seats.get(self._selected_seat_global)
        manager_entry = self._proxies.get(_VIRTUAL_POINTER_MANAGER)
        if manager_entry is None or seat is None:
            return
        pointer = manager_entry[1].create_virtual_pointer(seat.proxy)
        with self._state_lock:
            self._virtual_pointer = pointer

    def _destroy_virtual_pointer(self) -> None:
        with self._state_lock:
            pointer = self._virtual_pointer
            self._virtual_pointer = None
        if pointer is None:
            self._pressed_pointer_buttons.clear()
            return
        try:
            try:
                if not pointer.destroyed and self._pressed_pointer_buttons:
                    timestamp = self._timestamp_ms()
                    for button_code in sorted(self._pressed_pointer_buttons):
                        pointer.button(timestamp, button_code, _BUTTON_RELEASED)
                    pointer.frame()
            except Exception as release_error:
                try:
                    if not pointer.destroyed:
                        pointer.destroy()
                except Exception as destroy_error:
                    release_error.add_note(
                        "Virtual pointer destroy also failed: "
                        f"{type(destroy_error).__name__}: {destroy_error}"
                    )
                raise
            if not pointer.destroyed:
                pointer.destroy()
        finally:
            self._pressed_pointer_buttons.clear()

    @staticmethod
    def _timestamp_ms() -> int:
        return (time.monotonic_ns() // 1_000_000) & 0xFFFFFFFF

    def _require_virtual_keyboard(self) -> tuple[Any, XkbKeymap]:
        with self._state_lock:
            keyboard = self._virtual_keyboard
            keymap = self._virtual_keyboard_keymap
            xkb_keymap = self._xkb_keymap
            seat = self._seats.get(self._selected_seat_global)
            ready = (
                keyboard is not None
                and keymap is not None
                and xkb_keymap is not None
                and seat is not None
                and seat.keyboard is not None
                and not seat.keyboard.destroyed
                and seat.keymap == keymap
            )
        if not ready or keyboard.destroyed:
            raise RuntimeError("Wayland virtual keyboard is not ready")
        return keyboard, xkb_keymap

    def _send_keyboard_key(
        self, keyboard: Any, keycode: int, *, pressed: bool
    ) -> None:
        keycode = validate_keycode(keycode)
        if pressed and keycode in self._pressed_keyboard_keys:
            return
        if not pressed and keycode not in self._pressed_keyboard_keys:
            return
        try:
            keyboard.key(
                self._timestamp_ms(),
                keycode,
                _KEY_PRESSED if pressed else _KEY_RELEASED,
            )
            if pressed:
                self._pressed_keyboard_keys.append(keycode)
            else:
                self._pressed_keyboard_keys.remove(keycode)
            if self._xkb_keymap is not None:
                modifiers = self._xkb_keymap.update_key(keycode, pressed)
                if modifiers is not None:
                    keyboard.modifiers(*modifiers)
        except Exception as exc:
            self._record_failure(exc)
            raise

    def _emit_pointer_modified_click(
        self,
        down: tuple[KeyStroke, ...],
        up: tuple[KeyStroke, ...],
        button_code: int,
    ) -> None:
        self._require_virtual_keyboard()
        self._require_virtual_pointer()
        if button_code in self._pressed_pointer_buttons:
            raise RuntimeError("Cannot click a pointer button that is already held")
        self._emit_key_spec(down)
        try:
            try:
                self._emit_pointer_click(button_code)
            except Exception as exc:
                self._record_failure(exc)
                raise
        finally:
            self._emit_key_spec(up)

    def _emit_key_spec(self, strokes: tuple[KeyStroke, ...]) -> None:
        keyboard, xkb_keymap = self._require_virtual_keyboard()
        resolved_strokes = []
        for stroke in strokes:
            modifiers = [
                xkb_keymap.resolve_modifier(name) for name in stroke.modifiers
            ]
            keycode = None
            if stroke.key is not None:
                keycode, implicit_modifiers = xkb_keymap.resolve_key(stroke.key)
                modifiers.extend(implicit_modifiers)
            modifiers = list(dict.fromkeys(modifiers))
            resolved_strokes.append((stroke, keycode, modifiers))

        for stroke, keycode, modifiers in resolved_strokes:
            if stroke.action == "down":
                for modifier in modifiers:
                    self._send_keyboard_key(keyboard, modifier, pressed=True)
                if keycode is not None:
                    self._send_keyboard_key(keyboard, keycode, pressed=True)
                continue

            if stroke.action == "up":
                if keycode is not None:
                    self._send_keyboard_key(keyboard, keycode, pressed=False)
                for modifier in reversed(modifiers):
                    self._send_keyboard_key(keyboard, modifier, pressed=False)
                continue

            if keycode is None:
                for _ in range(stroke.repeat):
                    pressed_here = [
                        modifier
                        for modifier in modifiers
                        if modifier not in self._pressed_keyboard_keys
                    ]
                    try:
                        for modifier in pressed_here:
                            self._send_keyboard_key(keyboard, modifier, pressed=True)
                    finally:
                        for modifier in reversed(pressed_here):
                            self._send_keyboard_key(keyboard, modifier, pressed=False)
                continue

            pressed_here = [
                modifier
                for modifier in modifiers
                if modifier not in self._pressed_keyboard_keys
            ]
            try:
                for modifier in pressed_here:
                    self._send_keyboard_key(keyboard, modifier, pressed=True)
                if keycode in self._pressed_keyboard_keys:
                    raise RuntimeError(
                        f"Cannot tap keyboard keycode {keycode} while it is held"
                    )
                for _ in range(stroke.repeat):
                    self._send_keyboard_key(keyboard, keycode, pressed=True)
                    self._send_keyboard_key(keyboard, keycode, pressed=False)
            finally:
                for modifier in reversed(pressed_here):
                    self._send_keyboard_key(keyboard, modifier, pressed=False)

    def _require_virtual_pointer(self) -> Any:
        with self._state_lock:
            pointer = self._virtual_pointer
        if pointer is None or pointer.destroyed:
            raise RuntimeError("Wayland virtual pointer is not ready")
        return pointer

    def _emit_pointer_absolute(self, x: int, y: int) -> None:
        pointer = self._require_virtual_pointer()
        pointer.motion_absolute(
            self._timestamp_ms(),
            x,
            y,
            POINTER_EXTENT,
            POINTER_EXTENT,
        )
        pointer.frame()

    def _emit_pointer_relative(self, dx: float, dy: float) -> None:
        dx = validate_wayland_fixed(dx, "Pointer x delta")
        dy = validate_wayland_fixed(dy, "Pointer y delta")
        pointer = self._require_virtual_pointer()
        pointer.motion(self._timestamp_ms(), dx, dy)
        pointer.frame()

    def _emit_pointer_button(self, button_code: int, *, pressed: bool) -> None:
        if pressed and button_code in self._pressed_pointer_buttons:
            return
        if not pressed and button_code not in self._pressed_pointer_buttons:
            return
        pointer = self._require_virtual_pointer()
        pointer.button(
            self._timestamp_ms(),
            button_code,
            _BUTTON_PRESSED if pressed else _BUTTON_RELEASED,
        )
        if pressed:
            self._pressed_pointer_buttons.add(button_code)
        else:
            self._pressed_pointer_buttons.remove(button_code)
        pointer.frame()

    def _emit_pointer_click(self, button_code: int) -> None:
        if button_code in self._pressed_pointer_buttons:
            raise RuntimeError("Cannot click a pointer button that is already held")
        pointer = self._require_virtual_pointer()
        timestamp = self._timestamp_ms()
        pointer.button(timestamp, button_code, _BUTTON_PRESSED)
        self._pressed_pointer_buttons.add(button_code)
        pointer.frame()
        pointer.button(timestamp, button_code, _BUTTON_RELEASED)
        self._pressed_pointer_buttons.remove(button_code)
        pointer.frame()

    def _emit_pointer_scroll(
        self, vertical_steps: int, horizontal_steps: int
    ) -> None:
        vertical_steps = validate_int32(vertical_steps, "Vertical scroll steps")
        horizontal_steps = validate_int32(horizontal_steps, "Horizontal scroll steps")
        vertical_value = validate_wayland_fixed(
            vertical_steps * _SCROLL_DISTANCE_PER_STEP,
            "Vertical scroll distance",
        )
        horizontal_value = validate_wayland_fixed(
            horizontal_steps * _SCROLL_DISTANCE_PER_STEP,
            "Horizontal scroll distance",
        )
        pointer = self._require_virtual_pointer()
        timestamp = self._timestamp_ms()
        pointer.axis_source(_AXIS_SOURCE_WHEEL)
        if vertical_steps:
            pointer.axis_discrete(
                timestamp,
                _AXIS_VERTICAL,
                vertical_value,
                vertical_steps,
            )
        if horizontal_steps:
            pointer.axis_discrete(
                timestamp,
                _AXIS_HORIZONTAL,
                horizontal_value,
                horizontal_steps,
            )
        pointer.frame()

    def _on_global_remove(self, registry: Any, name: int) -> None:
        announcement = self._announced_globals.pop(name, None)
        if announcement is None:
            return
        interface_name, _version = announcement
        if interface_name == _SEAT_INTERFACE:
            self._remove_seat(name)
            return
        entry = self._proxies.get(interface_name)
        if entry is None or entry[0] != name:
            return

        _global_name, proxy = self._proxies.pop(interface_name)
        with self._state_lock:
            self._globals.pop(interface_name, None)
        if interface_name == _VIRTUAL_POINTER_MANAGER:
            self._destroy_virtual_pointer()
        if interface_name == _VIRTUAL_KEYBOARD_MANAGER:
            self._destroy_virtual_keyboard()
        if interface_name == _TOPLEVEL_MANAGER:
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
        pending = self._handles.get(handle)
        if pending is not None:
            pending.title = title

    def _on_toplevel_app_id(self, handle: Any, app_id: str) -> None:
        pending = self._handles.get(handle)
        if pending is not None:
            pending.app_id = app_id

    def _on_toplevel_state(self, handle: Any, payload: bytes) -> None:
        pending = self._handles.get(handle)
        if pending is not None:
            pending.states = decode_toplevel_states(payload)

    def _on_toplevel_done(self, handle: Any) -> None:
        pending = self._handles.get(handle)
        if pending is None:
            return
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
        interface_name = _TOPLEVEL_MANAGER
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
                self._drain_commands()
                if self._stopping.is_set():
                    break
                while lib.wl_display_prepare_read(display._ptr) != 0:
                    display.dispatch(block=False)

                # Every successful prepare_read must be paired with either
                # read_events or cancel_read, including exceptional paths.
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

    def _flush_for_disconnect(self) -> None:
        assert self._display is not None
        display = self._display
        bindings = self._bindings
        deadline = time.monotonic() + _DISCONNECT_FLUSH_TIMEOUT
        while display.flush() == -1:
            if bindings is None:
                raise RuntimeError("Wayland bindings are unavailable during shutdown")
            if bindings.ffi.errno != errno.EAGAIN:
                raise OSError(
                    bindings.ffi.errno,
                    "wl_display_flush failed during shutdown",
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out flushing Wayland shutdown requests")
            with selectors.DefaultSelector() as selector:
                selector.register(display.get_fd(), selectors.EVENT_WRITE)
                if not selector.select(remaining):
                    raise TimeoutError(
                        "Timed out flushing Wayland shutdown requests"
                    )

    def _disconnect(self) -> None:
        display = self._display
        if display is None:
            return

        failures: list[tuple[str, Exception]] = []

        def attempt(label: str, operation: Callable[[], Any]) -> None:
            try:
                operation()
            except Exception as exc:
                failures.append((label, exc))

        try:
            attempt("virtual keyboard cleanup", self._destroy_virtual_keyboard)
            attempt("virtual pointer cleanup", self._destroy_virtual_pointer)
            for handle in tuple(self._handles):
                if not handle.destroyed:
                    attempt("toplevel handle cleanup", handle.destroy)
            for seat in tuple(self._seats.values()):
                attempt(
                    "seat keyboard cleanup",
                    lambda seat=seat: self._release_seat_keyboard(seat),
                )
                attempt("seat cleanup", lambda seat=seat: self._release_seat(seat))
            manager_entry = self._proxies.get(_TOPLEVEL_MANAGER)
            if manager_entry is not None and not manager_entry[1].destroyed:
                attempt("toplevel manager cleanup", manager_entry[1].stop)
            attempt("shutdown flush", self._flush_for_disconnect)
        finally:
            try:
                display.disconnect()
            except Exception as exc:
                failures.append(("display disconnect", exc))
            finally:
                self._display = None
                self._registry = None
                self._sync_callback = None
                self._handles.clear()
                self._proxies.clear()
                self._announced_globals.clear()
                self._initialized = False
                with self._state_lock:
                    self._seats.clear()
                    self._selected_seat_global = None
                    self._virtual_pointer = None
                    self._virtual_keyboard = None
                    self._virtual_keyboard_keymap = None
                    self._xkb_keymap = None
                    self._globals.clear()
                    self._snapshots.clear()
                self._pressed_keyboard_keys.clear()

        if failures:
            _label, error = failures[0]
            for label, secondary in failures[1:]:
                error.add_note(
                    f"{label} also failed: {type(secondary).__name__}: {secondary}"
                )
            raise error.with_traceback(error.__traceback__)
