import errno
import socket
import struct
import sys
import time
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
    ):
        self.runtime = runtime
        self.read_result = read_result
        self.stop_on_cancel = stop_on_cancel
        self.prepare_results = list(prepare_results or [0])
        self.cancel_count = 0

    def wl_display_prepare_read(self, _display):
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
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class _FakeRegistry:
    def __init__(self):
        self.bound = []

    def bind(self, name, interface, version):
        proxy = _FakeProxy()
        self.bound.append((name, interface, version, proxy))
        return proxy


class WaylandRuntimeTests(unittest.TestCase):
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
        started = time.monotonic()
        try:
            with patch("wayland_backend.runtime._load_bindings", return_value=bindings):
                with self.assertRaisesRegex(TimeoutError, "Timed out starting"):
                    runtime.start(timeout=0.05)

            self.assertLess(time.monotonic() - started, 0.5)
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
