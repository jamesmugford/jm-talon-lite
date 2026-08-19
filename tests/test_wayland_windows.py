import io
import struct
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

if __package__:
    from .wayland_fakes import FakeProxy, FakeRegistry, ImmediateConnection, interface
else:
    from wayland_fakes import FakeProxy, FakeRegistry, ImmediateConnection, interface

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
sys.path.insert(0, str(PLUGINS))
try:
    from wayland_backend.windows import (
        ForeignToplevels,
        Window,
        choose_active_window,
        decode_window_states,
    )
finally:
    sys.path.remove(str(PLUGINS))


class WindowCoreTests(unittest.TestCase):
    def test_decodes_known_unknown_and_empty_states(self):
        payload = struct.pack("=IIIII", 0, 1, 2, 3, 99)
        self.assertEqual(
            decode_window_states(payload),
            ("maximized", "minimized", "activated", "fullscreen", "unknown:99"),
        )
        self.assertEqual(decode_window_states(b""), ())
        with self.assertRaises(ValueError):
            decode_window_states(b"\0")

    def test_active_selection_prefers_new_then_current_then_first(self):
        first = Window(1, "First", "first", ("activated",))
        second = Window(2, "Second", "second", ("activated",))
        self.assertIs(choose_active_window((first, second), 1), first)
        self.assertIs(choose_active_window((first, second), 1, 2), second)
        self.assertIsNone(choose_active_window((), 1))


class ForeignToplevelTests(unittest.TestCase):
    def setUp(self):
        self.connection = ImmediateConnection()
        self.windows = ForeignToplevels(self.connection)
        self.registry = FakeRegistry()
        self.windows.bind(self.registry, 10, 3, interface(3))
        self.manager = self.registry.bound[0][3]

    def announce(self, title: str, app_id: str, states: tuple[int, ...]):
        handle = FakeProxy()
        self.manager.dispatcher["toplevel"](self.manager, handle)
        handle.dispatcher["title"](handle, title)
        handle.dispatcher["app_id"](handle, app_id)
        handle.dispatcher["state"](handle, struct.pack(f"={len(states)}I", *states))
        handle.dispatcher["done"](handle)
        return handle

    def test_publishes_only_meaningful_active_window_changes(self):
        observed = []
        unsubscribe = self.windows.on_active_changed(observed.append)
        first = self.announce("First", "first.app", (0,))
        self.assertEqual(observed, [])

        first.dispatcher["state"](first, struct.pack("=I", 2))
        first.dispatcher["done"](first)
        first.dispatcher["done"](first)
        self.assertEqual(
            observed,
            [Window(1, "First", "first.app", ("activated",))],
        )

        second = self.announce("Second", "second.app", (2,))
        first.dispatcher["title"](first, "Stale")
        first.dispatcher["done"](first)
        self.assertEqual(
            observed[-1], Window(2, "Second", "second.app", ("activated",))
        )
        second.dispatcher["closed"](second)
        self.assertEqual(observed[-1].app_id, "first.app")

        unsubscribe()
        unsubscribe()
        first.dispatcher["closed"](first)
        self.assertNotIn(None, observed)

    def test_late_events_after_close_are_ignored(self):
        handle = self.announce("Title", "app", (2,))
        handle.dispatcher["closed"](handle)
        handle.dispatcher["title"](handle, "Late")
        handle.dispatcher["done"](handle)
        self.assertEqual(self.windows.snapshots(), ())
        self.assertTrue(handle.destroyed)

    def test_consumer_failure_is_logged_without_failing_connection(self):
        def fail(_window):
            raise RuntimeError("observer failed")

        self.windows.on_active_changed(fail)
        with redirect_stderr(io.StringIO()) as stderr:
            self.announce("Title", "app", (2,))
        self.assertIn("observer failed", stderr.getvalue())
        self.assertFalse(self.connection.failures)

    def test_finished_manager_clears_state_and_deactivates_protocol(self):
        observed = []
        self.windows.on_active_changed(observed.append)
        self.announce("Title", "app", (2,))
        self.manager.dispatcher["finished"](self.manager)
        self.assertFalse(self.windows.available())
        self.assertEqual(self.windows.snapshots(), ())
        self.assertIsNone(observed[-1])
        self.assertEqual(
            self.connection.deactivated,
            [("zwlr_foreign_toplevel_manager_v1", 10)],
        )

    def test_finished_manager_publishes_unavailability_without_active_window(self):
        observed = []
        availability = []
        self.windows.on_active_changed(
            lambda window: (
                observed.append(window),
                availability.append(self.windows.available()),
            )
        )

        self.manager.dispatcher["finished"](self.manager)

        self.assertEqual(observed, [None])
        self.assertEqual(availability, [False])

    def test_close_is_idempotent_and_stops_manager(self):
        handle = self.announce("Title", "app", ())
        self.windows.close()
        self.windows.close()
        self.assertTrue(handle.destroyed)
        self.assertEqual(self.manager.calls.count(("stop",)), 1)


if __name__ == "__main__":
    unittest.main()
