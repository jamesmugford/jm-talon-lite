import errno
import math
import socket
import struct
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_plugins_dir = Path(__file__).resolve().parents[1] / "plugins"
_added_plugins_path = str(_plugins_dir) not in sys.path
if _added_plugins_path:
    sys.path.insert(0, str(_plugins_dir))
try:
    from wayland_backend.runtime import WaylandRuntime, decode_toplevel_states
finally:
    if _added_plugins_path:
        sys.path.remove(str(_plugins_dir))


class DecodeToplevelStatesTests(unittest.TestCase):
    def test_decodes_known_and_unknown_states(self):
        payload = struct.pack("=IIIII", 0, 1, 2, 3, 99)

        self.assertEqual(
            decode_toplevel_states(payload),
            ("maximized", "minimized", "activated", "fullscreen", "unknown:99"),
        )

    def test_rejects_misaligned_payload(self):
        with self.assertRaises(ValueError):
            decode_toplevel_states(b"\0")

    def test_empty_payload_has_no_states(self):
        self.assertEqual(decode_toplevel_states(b""), ())


class _FakeLib:
    def __init__(
        self,
        runtime,
        *,
        read_result=0,
        stop_on_cancel=False,
        prepare_results=None,
        prepared_event=None,
    ):
        self.runtime = runtime
        self.read_result = read_result
        self.stop_on_cancel = stop_on_cancel
        self.prepare_results = list(prepare_results or [0])
        self.prepared_event = prepared_event
        self.cancel_count = 0

    def wl_display_prepare_read(self, _display):
        if self.prepared_event is not None:
            self.prepared_event.set()
        if len(self.prepare_results) > 1:
            return self.prepare_results.pop(0)
        return self.prepare_results[0]

    def wl_display_cancel_read(self, _display):
        self.cancel_count += 1
        if self.stop_on_cancel:
            self.runtime._stopping.set()

    def wl_display_read_events(self, _display):
        return self.read_result

    def wl_display_get_error(self, _display):
        return 5


class _FakeCallback:
    def __init__(self):
        self.dispatcher = {}
        self.destroyed = False

    def _destroy(self):
        self.destroyed = True


class _FakeDisplay:
    def __init__(self, file_descriptor=-1, registry=None, flush_results=None):
        self._ptr = object()
        self.file_descriptor = file_descriptor
        self.registry = registry
        self.flush_results = list(flush_results or [0])
        self.callbacks = []
        self.dispatch_count = 0
        self.disconnected = False

    def connect(self):
        pass

    def get_registry(self):
        return self.registry

    def sync(self):
        callback = _FakeCallback()
        self.callbacks.append(callback)
        return callback

    def get_fd(self):
        return self.file_descriptor

    def flush(self):
        if len(self.flush_results) > 1:
            return self.flush_results.pop(0)
        return self.flush_results[0]

    def dispatch(self, *, block=False):
        self.dispatch_count += 1

    def disconnect(self):
        self.disconnected = True


class _FakeProxy:
    def __init__(self, event_log=None):
        self.destroyed = False
        self.dispatcher = {}
        self.calls = []
        self.created_pointers = []
        self.event_log = event_log

    def _record(self, call):
        self.calls.append(call)
        if self.event_log is not None:
            self.event_log.append((self, call[0]))

    def destroy(self):
        self._record(("destroy",))
        self.destroyed = True

    def _destroy(self):
        self._record(("_destroy",))
        self.destroyed = True

    def release(self):
        self._record(("release",))
        self.destroyed = True

    def create_virtual_pointer(self, seat):
        pointer = _FakeProxy(self.event_log)
        self._record(("create_virtual_pointer", seat))
        self.created_pointers.append(pointer)
        return pointer

    def motion_absolute(self, timestamp, x, y, x_extent, y_extent):
        self._record(
            ("motion_absolute", timestamp, x, y, x_extent, y_extent)
        )

    def motion(self, timestamp, dx, dy):
        self._record(("motion", timestamp, dx, dy))

    def button(self, timestamp, button, state):
        self._record(("button", timestamp, button, state))

    def axis_source(self, source):
        self._record(("axis_source", source))

    def axis_discrete(self, timestamp, axis, value, discrete):
        self._record(("axis_discrete", timestamp, axis, value, discrete))

    def frame(self):
        self._record(("frame",))


class _FakeRegistry:
    def __init__(self):
        self.bound = []
        self.event_log = []

    def bind(self, name, interface, version):
        proxy = _FakeProxy(self.event_log)
        self.bound.append((name, interface, version, proxy))
        return proxy


class WaylandRuntimeTests(unittest.TestCase):
    @staticmethod
    def _input_bindings():
        return SimpleNamespace(
            interfaces={
                "wl_seat": SimpleNamespace(version=11),
                "zwlr_virtual_pointer_manager_v1": SimpleNamespace(version=2),
            }
        )

    def test_connect_retains_registry_proxy(self):
        runtime = WaylandRuntime()
        registry = SimpleNamespace(dispatcher={})
        display = _FakeDisplay(registry=registry)
        runtime._bindings = SimpleNamespace(Display=lambda: display)

        runtime._connect()

        self.assertIs(runtime._registry, registry)
        self.assertEqual(len(display.callbacks), 1)
        self.assertFalse(runtime._ready.is_set())

        first_callback = display.callbacks[0]
        first_callback.dispatcher["done"](first_callback, 0)
        self.assertTrue(first_callback.destroyed)
        self.assertEqual(len(display.callbacks), 2)
        self.assertFalse(runtime._ready.is_set())

        second_callback = display.callbacks[1]
        second_callback.dispatcher["done"](second_callback, 0)
        self.assertTrue(second_callback.destroyed)
        self.assertTrue(runtime._ready.is_set())

    def test_overlapping_globals_keep_proxy_identity_until_removal(self):
        runtime = WaylandRuntime()
        interface = SimpleNamespace(version=2)
        runtime._bindings = SimpleNamespace(interfaces={"test_manager": interface})
        registry = _FakeRegistry()

        runtime._on_global(registry, 10, "test_manager", 3)
        first_proxy = registry.bound[0][3]
        runtime._on_global(registry, 11, "test_manager", 1)

        self.assertEqual(len(registry.bound), 1)
        self.assertEqual(runtime._proxies["test_manager"], (10, first_proxy))
        self.assertEqual(runtime.status().globals, (("test_manager", 2),))

        runtime._on_global_remove(registry, 10)

        self.assertTrue(first_proxy.destroyed)
        self.assertEqual(len(registry.bound), 2)
        self.assertEqual(registry.bound[1][:3], (11, interface, 1))
        self.assertEqual(runtime.status().globals, (("test_manager", 1),))

    def test_removed_global_is_destroyed_and_rebound_on_reannouncement(self):
        runtime = WaylandRuntime()
        interface = SimpleNamespace(version=2)
        runtime._bindings = SimpleNamespace(interfaces={"test_manager": interface})
        registry = _FakeRegistry()

        runtime._on_global(registry, 10, "test_manager", 3)
        first_proxy = registry.bound[0][3]
        runtime._on_global_remove(registry, 10)
        runtime._on_global(registry, 11, "test_manager", 1)

        self.assertTrue(first_proxy.destroyed)
        self.assertEqual(len(registry.bound), 2)
        self.assertEqual(runtime.status().globals, (("test_manager", 1),))
        self.assertIs(runtime._proxies["test_manager"][1], registry.bound[1][3])

    def test_seat0_is_selected_and_pointer_follows_seat_removal(self):
        runtime = WaylandRuntime()
        runtime._bindings = self._input_bindings()
        registry = _FakeRegistry()

        runtime._on_global(
            registry, 10, "zwlr_virtual_pointer_manager_v1", 2
        )
        runtime._on_global(registry, 20, "wl_seat", 11)
        seat1 = registry.bound[1][3]
        seat1.dispatcher["name"](seat1, "seat1")
        seat1.dispatcher["capabilities"](seat1, 3)
        runtime._on_global(registry, 21, "wl_seat", 11)
        seat0 = registry.bound[2][3]
        seat0.dispatcher["name"](seat0, "seat0")
        seat0.dispatcher["capabilities"](seat0, 1)
        runtime._initialized = True
        runtime._maybe_create_virtual_pointer()

        manager = registry.bound[0][3]
        first_pointer = manager.created_pointers[0]
        status = runtime.status()
        self.assertEqual(
            [(seat.name, seat.selected) for seat in status.seats],
            [("seat1", False), ("seat0", True)],
        )
        self.assertEqual(status.seats[0].capabilities, ("pointer", "keyboard"))
        self.assertTrue(status.virtual_pointer_ready)
        self.assertEqual(manager.calls[0], ("create_virtual_pointer", seat0))

        runtime._on_global_remove(registry, 21)

        self.assertTrue(first_pointer.destroyed)
        self.assertIn(("release",), seat0.calls)
        self.assertLess(
            registry.event_log.index((first_pointer, "destroy")),
            registry.event_log.index((seat0, "release")),
        )
        self.assertEqual(len(manager.created_pointers), 2)
        self.assertEqual(manager.calls[-1], ("create_virtual_pointer", seat1))
        self.assertTrue(runtime.status().seats[0].selected)

    def test_pointer_is_created_when_manager_arrives_after_seat(self):
        runtime = WaylandRuntime()
        runtime._bindings = self._input_bindings()
        runtime._initialized = True
        registry = _FakeRegistry()

        runtime._on_global(registry, 20, "wl_seat", 11)
        seat = registry.bound[0][3]
        seat.dispatcher["name"](seat, "seat0")
        self.assertFalse(runtime.status().virtual_pointer_ready)

        runtime._on_global(
            registry, 10, "zwlr_virtual_pointer_manager_v1", 2
        )

        manager = registry.bound[1][3]
        self.assertEqual(manager.calls[0], ("create_virtual_pointer", seat))
        self.assertTrue(runtime.status().virtual_pointer_ready)

    def test_pointer_is_destroyed_before_manager_on_global_removal(self):
        runtime = WaylandRuntime()
        runtime._bindings = self._input_bindings()
        runtime._initialized = True
        registry = _FakeRegistry()
        runtime._on_global(registry, 20, "wl_seat", 11)
        runtime._on_global(
            registry, 10, "zwlr_virtual_pointer_manager_v1", 2
        )
        manager = registry.bound[1][3]
        pointer = manager.created_pointers[0]
        registry.event_log.clear()

        runtime._on_global_remove(registry, 10)

        self.assertLess(
            registry.event_log.index((pointer, "destroy")),
            registry.event_log.index((manager, "destroy")),
        )
        self.assertFalse(runtime.status().virtual_pointer_ready)

    def test_disconnect_destroys_pointer_before_releasing_seat(self):
        runtime = WaylandRuntime()
        runtime._bindings = self._input_bindings()
        runtime._initialized = True
        runtime._display = _FakeDisplay()
        registry = _FakeRegistry()
        runtime._on_global(registry, 20, "wl_seat", 11)
        runtime._on_global(
            registry, 10, "zwlr_virtual_pointer_manager_v1", 2
        )
        seat = registry.bound[0][3]
        pointer = registry.bound[1][3].created_pointers[0]
        registry.event_log.clear()

        runtime._disconnect()

        self.assertLess(
            registry.event_log.index((pointer, "destroy")),
            registry.event_log.index((seat, "release")),
        )

    def test_old_seat_version_is_destroyed_without_release_request(self):
        runtime = WaylandRuntime()
        runtime._bindings = self._input_bindings()
        registry = _FakeRegistry()

        runtime._on_global(registry, 20, "wl_seat", 4)
        seat = registry.bound[0][3]
        runtime._on_global_remove(registry, 20)

        self.assertIn(("_destroy",), seat.calls)
        self.assertNotIn(("release",), seat.calls)
        self.assertEqual(runtime.status().seats, ())

    def test_pointer_requests_have_expected_protocol_order(self):
        runtime = WaylandRuntime()
        pointer = _FakeProxy()
        runtime._running.set()
        runtime._owner_thread_id = threading.get_ident()
        runtime._virtual_pointer = pointer

        with patch(
            "wayland_backend.runtime.time.monotonic_ns",
            return_value=1_234_000_000,
        ):
            runtime.pointer_move_absolute(-1.0, 2.0)
            runtime.pointer_move_relative(2.5, -3.5)
            runtime.pointer_button_down(0)
            runtime.pointer_button_down(0)
            runtime.pointer_button_up(0)
            runtime.pointer_click(1)
            runtime.pointer_scroll(vertical_steps=2, horizontal_steps=-1)

        self.assertEqual(
            pointer.calls,
            [
                ("motion_absolute", 1234, 0, 65535, 65535, 65535),
                ("frame",),
                ("motion", 1234, 2.5, -3.5),
                ("frame",),
                ("button", 1234, 0x110, 1),
                ("frame",),
                ("button", 1234, 0x110, 0),
                ("frame",),
                ("button", 1234, 0x111, 1),
                ("frame",),
                ("button", 1234, 0x111, 0),
                ("frame",),
                ("axis_source", 0),
                ("axis_discrete", 1234, 0, 30.0, 2),
                ("axis_discrete", 1234, 1, -15.0, -1),
                ("frame",),
            ],
        )

    def test_pointer_teardown_releases_held_buttons(self):
        runtime = WaylandRuntime()
        pointer = _FakeProxy()
        runtime._running.set()
        runtime._owner_thread_id = threading.get_ident()
        runtime._virtual_pointer = pointer

        with patch(
            "wayland_backend.runtime.time.monotonic_ns",
            return_value=5_000_000,
        ):
            runtime.pointer_button_down(2)
            runtime._destroy_virtual_pointer()

        self.assertEqual(
            pointer.calls[-3:],
            [
                ("button", 5, 0x112, 0),
                ("frame",),
                ("destroy",),
            ],
        )
        self.assertFalse(runtime._pressed_pointer_buttons)
        self.assertFalse(runtime.status().virtual_pointer_ready)

    def test_pointer_teardown_destroys_after_release_failure(self):
        runtime = WaylandRuntime()
        pointer = _FakeProxy()
        runtime._virtual_pointer = pointer
        runtime._pressed_pointer_buttons.add(0x110)

        with (
            patch.object(
                pointer,
                "frame",
                side_effect=RuntimeError("release failed"),
            ),
            patch.object(
                pointer,
                "destroy",
                side_effect=RuntimeError("destroy failed"),
            ) as destroy,
        ):
            with self.assertRaisesRegex(RuntimeError, "release failed") as raised:
                runtime._destroy_virtual_pointer()

        destroy.assert_called_once_with()
        self.assertEqual(
            raised.exception.__notes__,
            ["Virtual pointer destroy also failed: RuntimeError: destroy failed"],
        )
        self.assertFalse(runtime._pressed_pointer_buttons)
        self.assertFalse(runtime.status().virtual_pointer_ready)

    def test_out_of_range_pointer_values_emit_no_requests(self):
        runtime = WaylandRuntime()
        pointer = _FakeProxy()
        runtime._running.set()
        runtime._owner_thread_id = threading.get_ident()
        runtime._virtual_pointer = pointer

        with self.assertRaises(ValueError):
            runtime.pointer_move_relative(1 << 23, 0)
        with self.assertRaises(ValueError):
            runtime.pointer_scroll(vertical_steps=(1 << 31) - 1)

        self.assertEqual(pointer.calls, [])

    def test_invalid_command_timeouts_emit_no_requests(self):
        runtime = WaylandRuntime()
        pointer = _FakeProxy()
        runtime._running.set()
        runtime._owner_thread_id = threading.get_ident()
        runtime._virtual_pointer = pointer

        invalid_values = (
            0,
            -1,
            math.inf,
            -math.inf,
            math.nan,
            threading.TIMEOUT_MAX * 2,
            10**400,
        )
        for timeout in invalid_values:
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    runtime.pointer_click(timeout=timeout)
        for timeout in (True, "1"):
            with self.subTest(timeout=timeout):
                with self.assertRaises(TypeError):
                    runtime.pointer_click(timeout=timeout)

        self.assertEqual(pointer.calls, [])

    def test_invalid_lifecycle_timeouts_have_no_side_effects(self):
        runtime = WaylandRuntime()

        for operation in (runtime.start, runtime.stop):
            for timeout in (
                0,
                math.inf,
                math.nan,
                threading.TIMEOUT_MAX * 2,
                10**400,
            ):
                with self.subTest(operation=operation.__name__, timeout=timeout):
                    with self.assertRaises(ValueError):
                        operation(timeout=timeout)
            with self.subTest(operation=operation.__name__, timeout=True):
                with self.assertRaises(TypeError):
                    operation(timeout=True)

        self.assertIsNone(runtime._thread)

    def test_zero_step_scroll_requires_a_ready_runtime_without_emitting(self):
        runtime = WaylandRuntime()
        pointer = _FakeProxy()
        runtime._running.set()
        runtime._owner_thread_id = threading.get_ident()
        runtime._virtual_pointer = pointer

        runtime.pointer_scroll()

        self.assertEqual(pointer.calls, [])
        with self.assertRaisesRegex(RuntimeError, "not running"):
            WaylandRuntime().pointer_scroll()
        not_ready = WaylandRuntime()
        not_ready._running.set()
        not_ready._owner_thread_id = threading.get_ident()
        with self.assertRaisesRegex(RuntimeError, "virtual pointer is not ready"):
            not_ready.pointer_scroll()
        with self.assertRaises(ValueError):
            runtime.pointer_scroll(timeout=math.nan)

    def test_mailbox_cancels_prepared_read_before_running_command(self):
        runtime = WaylandRuntime()
        wake_read, wake_write = socket.socketpair()
        display_read, display_write = socket.socketpair()
        prepared = threading.Event()
        callback_observations = []
        errors = []
        owner = None
        try:
            wake_read.setblocking(False)
            runtime._wake_read = wake_read
            runtime._wake_write = wake_write
            runtime._display = _FakeDisplay(display_read.fileno())
            lib = _FakeLib(runtime, prepared_event=prepared)
            runtime._bindings = SimpleNamespace(
                ffi=SimpleNamespace(errno=0),
                lib=lib,
            )
            runtime._running.set()

            def run_loop():
                runtime._owner_thread_id = threading.get_ident()
                try:
                    runtime._event_loop()
                except Exception as exc:
                    errors.append(exc)

            owner = threading.Thread(target=run_loop)
            owner.start()
            self.assertTrue(prepared.wait(1))

            def command():
                callback_observations.append(lib.cancel_count)
                runtime._stopping.set()
                return "executed"

            self.assertEqual(runtime._submit(command, 1), "executed")
            owner.join(1)

            self.assertFalse(owner.is_alive())
            self.assertFalse(errors)
            self.assertEqual(callback_observations, [1])
        finally:
            runtime._stopping.set()
            runtime._wake()
            if owner is not None:
                owner.join(1)
            wake_read.close()
            wake_write.close()
            display_read.close()
            display_write.close()

    def test_queued_command_timeout_prevents_late_execution(self):
        runtime = WaylandRuntime()
        executed = []
        runtime._running.set()

        with self.assertRaisesRegex(TimeoutError, "cancelled before execution"):
            runtime._submit(lambda: executed.append(True), 0.01)

        runtime._owner_thread_id = threading.get_ident()
        runtime._drain_commands()
        self.assertEqual(executed, [])

    def test_claimed_command_finishes_instead_of_reporting_timeout(self):
        runtime = WaylandRuntime()
        runtime._running.set()
        queued = threading.Event()
        timed_wait_started = threading.Event()
        allow_timeout = threading.Event()
        definitive_wait_started = threading.Event()
        completed = threading.Event()
        claimed = threading.Event()
        release = threading.Event()
        result = []
        errors = []

        class ControlledDone:
            def wait(self, timeout=None):
                if timeout is not None:
                    timed_wait_started.set()
                    allow_timeout.wait()
                    return False
                definitive_wait_started.set()
                completed.wait()
                return True

            def set(self):
                completed.set()

        done = ControlledDone()

        def make_command(callback):
            return SimpleNamespace(
                callback=callback,
                done=done,
                state="queued",
                result=None,
                error=None,
            )

        def command():
            claimed.set()
            release.wait()
            return "complete"

        def submit():
            try:
                result.append(runtime._submit(command, 1))
            except Exception as exc:
                errors.append(exc)

        submitter = None
        owner = None
        with (
            patch.object(runtime, "_wake", queued.set),
            patch("wayland_backend.runtime._Command", side_effect=make_command),
        ):
            try:
                submitter = threading.Thread(target=submit)
                submitter.start()
                self.assertTrue(queued.wait(1))
                self.assertTrue(timed_wait_started.wait(1))

                owner = threading.Thread(target=runtime._drain_commands)
                owner.start()
                self.assertTrue(claimed.wait(1))
                allow_timeout.set()
                self.assertTrue(definitive_wait_started.wait(1))
                self.assertTrue(submitter.is_alive())

                release.set()
                owner.join(1)
                submitter.join(1)
                self.assertFalse(owner.is_alive())
                self.assertFalse(submitter.is_alive())
                self.assertFalse(errors)
                self.assertEqual(result, ["complete"])
            finally:
                allow_timeout.set()
                release.set()
                completed.set()
                if owner is not None:
                    owner.join(1)
                if submitter is not None:
                    submitter.join(1)

    def test_runtime_failure_releases_queued_submitter_with_original_error(self):
        runtime = WaylandRuntime()
        runtime._running.set()
        queued = threading.Event()
        executed = []
        errors = []
        failure = ValueError("bad event")
        pending = None

        def submit():
            try:
                runtime._submit(lambda: executed.append(True), 1)
            except Exception as exc:
                errors.append(exc)

        submitter = threading.Thread(target=submit)
        with patch.object(runtime, "_wake", queued.set):
            submitter.start()
            try:
                self.assertTrue(queued.wait(1))
                with runtime._command_lock:
                    pending = runtime._commands[0]
                runtime._record_failure(failure)
                submitter.join(1)
            finally:
                if pending is not None:
                    pending.done.set()
                submitter.join(1)

        self.assertFalse(submitter.is_alive())
        self.assertEqual(executed, [])
        self.assertEqual(len(errors), 1)
        self.assertIs(errors[0], failure)

    def test_read_error_does_not_cancel_consumed_preparation(self):
        runtime = WaylandRuntime()
        wake_read, wake_write = socket.socketpair()
        display_read, display_write = socket.socketpair()
        try:
            wake_read.setblocking(False)
            runtime._wake_read = wake_read
            runtime._wake_write = wake_write
            runtime._display = _FakeDisplay(display_read.fileno())
            lib = _FakeLib(runtime, read_result=-1)
            runtime._bindings = SimpleNamespace(
                ffi=SimpleNamespace(errno=0),
                lib=lib,
            )
            display_write.send(b"event")

            with self.assertRaisesRegex(RuntimeError, "Wayland read failed"):
                runtime._event_loop()

            self.assertEqual(lib.cancel_count, 0)
        finally:
            wake_read.close()
            wake_write.close()
            display_read.close()
            display_write.close()

    def test_flush_eagain_waits_for_writable_and_cancels_read(self):
        runtime = WaylandRuntime()
        wake_read, wake_write = socket.socketpair()
        display_read, display_write = socket.socketpair()
        try:
            wake_read.setblocking(False)
            runtime._wake_read = wake_read
            runtime._wake_write = wake_write
            runtime._display = _FakeDisplay(
                display_read.fileno(), flush_results=[-1, 0]
            )
            lib = _FakeLib(runtime, stop_on_cancel=True)
            runtime._bindings = SimpleNamespace(
                ffi=SimpleNamespace(errno=errno.EAGAIN),
                lib=lib,
            )

            runtime._event_loop()

            self.assertEqual(lib.cancel_count, 1)
        finally:
            wake_read.close()
            wake_write.close()
            display_read.close()
            display_write.close()

    def test_hard_flush_error_cancels_prepared_read(self):
        runtime = WaylandRuntime()
        wake_read, wake_write = socket.socketpair()
        display_read, display_write = socket.socketpair()
        try:
            wake_read.setblocking(False)
            runtime._wake_read = wake_read
            runtime._wake_write = wake_write
            runtime._display = _FakeDisplay(
                display_read.fileno(), flush_results=[-1]
            )
            lib = _FakeLib(runtime)
            runtime._bindings = SimpleNamespace(
                ffi=SimpleNamespace(errno=5),
                lib=lib,
            )

            with self.assertRaisesRegex(OSError, "wl_display_flush failed"):
                runtime._event_loop()

            self.assertEqual(lib.cancel_count, 1)
        finally:
            wake_read.close()
            wake_write.close()
            display_read.close()
            display_write.close()

    def test_pending_events_are_dispatched_before_prepare(self):
        runtime = WaylandRuntime()
        wake_read, wake_write = socket.socketpair()
        display_read, display_write = socket.socketpair()
        try:
            wake_read.setblocking(False)
            runtime._wake_read = wake_read
            runtime._wake_write = wake_write
            display = _FakeDisplay(display_read.fileno())
            runtime._display = display
            lib = _FakeLib(runtime, stop_on_cancel=True, prepare_results=[-1, 0])
            runtime._bindings = SimpleNamespace(
                ffi=SimpleNamespace(errno=0),
                lib=lib,
            )
            wake_write.send(b"wake")

            runtime._event_loop()

            self.assertEqual(display.dispatch_count, 1)
            self.assertEqual(lib.cancel_count, 1)
        finally:
            wake_read.close()
            wake_write.close()
            display_read.close()
            display_write.close()

    def test_wakeup_without_display_event_cancels_preparation(self):
        runtime = WaylandRuntime()
        wake_read, wake_write = socket.socketpair()
        display_read, display_write = socket.socketpair()
        try:
            wake_read.setblocking(False)
            runtime._wake_read = wake_read
            runtime._wake_write = wake_write
            runtime._display = _FakeDisplay(display_read.fileno())
            lib = _FakeLib(runtime, stop_on_cancel=True)
            runtime._bindings = SimpleNamespace(
                ffi=SimpleNamespace(errno=0),
                lib=lib,
            )
            wake_write.send(b"wake")

            runtime._event_loop()

            self.assertEqual(lib.cancel_count, 1)
        finally:
            wake_read.close()
            wake_write.close()
            display_read.close()
            display_write.close()

    def test_start_propagates_binding_initialization_failure(self):
        runtime = WaylandRuntime()
        with (
            patch(
                "wayland_backend.runtime._load_bindings",
                side_effect=ValueError("broken bindings"),
            ),
            patch("wayland_backend.runtime.traceback.print_exc"),
        ):
            with self.assertRaisesRegex(RuntimeError, "broken bindings"):
                runtime.start(timeout=1)

        self.assertFalse(runtime.status().running)
        self.assertIsNone(runtime._thread)
        self.assertIsNone(runtime._wake_read)
        self.assertIsNone(runtime._wake_write)

    def test_start_timeout_interrupts_initial_sync(self):
        runtime = WaylandRuntime()
        display_read, display_write = socket.socketpair()
        registry = SimpleNamespace(dispatcher={})
        display = _FakeDisplay(display_read.fileno(), registry=registry)
        bindings = SimpleNamespace(
            Display=lambda: display,
            interfaces={},
            ffi=SimpleNamespace(errno=0),
            lib=_FakeLib(runtime),
        )
        try:
            with (
                patch(
                    "wayland_backend.runtime._load_bindings",
                    return_value=bindings,
                ),
                patch.object(runtime._ready, "wait", return_value=False),
            ):
                with self.assertRaisesRegex(TimeoutError, "Timed out starting"):
                    runtime.start(timeout=1)

            self.assertTrue(display.disconnected)
            self.assertIsNone(runtime._thread)
            self.assertIsNone(runtime._wake_read)
            self.assertIsNone(runtime._wake_write)
        finally:
            display_read.close()
            display_write.close()

    def test_callback_failure_is_reported_and_stops_runtime(self):
        runtime = WaylandRuntime()

        def fail():
            raise ValueError("bad event")

        with patch("wayland_backend.runtime.traceback.print_exc"):
            runtime._guard_callback(fail)()

        self.assertEqual(runtime.status().error, "ValueError: bad event")
        self.assertTrue(runtime._stopping.is_set())
        self.assertTrue(runtime._ready.is_set())

    def test_disconnect_clears_published_state(self):
        runtime = WaylandRuntime()
        runtime._display = _FakeDisplay()
        runtime._globals["test_manager"] = 1
        runtime._snapshots[1] = SimpleNamespace()

        runtime._disconnect()

        self.assertEqual(runtime.status().globals, ())
        self.assertEqual(runtime.status().toplevels, ())

    def test_autonomous_worker_failure_closes_wakeup_sockets(self):
        runtime = WaylandRuntime()
        runtime._wake_read, runtime._wake_write = socket.socketpair()
        bindings = SimpleNamespace()

        with (
            patch("wayland_backend.runtime._load_bindings", return_value=bindings),
            patch.object(runtime, "_connect"),
            patch.object(runtime, "_event_loop", side_effect=RuntimeError("failed")),
            patch.object(runtime, "_disconnect"),
            patch("wayland_backend.runtime.traceback.print_exc"),
        ):
            runtime._run()

        self.assertEqual(runtime.status().error, "RuntimeError: failed")
        self.assertIsNone(runtime._wake_read)
        self.assertIsNone(runtime._wake_write)


if __name__ == "__main__":
    unittest.main()
