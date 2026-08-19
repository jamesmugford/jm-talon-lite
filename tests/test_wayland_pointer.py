import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

if __package__:
    from .wayland_fakes import FakeRegistry, ImmediateConnection, interface
else:
    from wayland_fakes import FakeRegistry, ImmediateConnection, interface

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
sys.path.insert(0, str(PLUGINS))
try:
    from wayland_backend.pointer import (
        INT32_MAX,
        POINTER_EXTENT,
        WAYLAND_FIXED_MAX,
        VirtualPointer,
        linux_button_code,
        normalized_to_extent,
        validate_int32,
        validate_wayland_fixed,
    )
    from wayland_backend.seats import SeatRegistry
finally:
    sys.path.remove(str(PLUGINS))


class PointerValueTests(unittest.TestCase):
    def test_normalized_coordinates_are_clamped_to_inclusive_extent(self):
        self.assertEqual(normalized_to_extent(0.0, 0.0), (0, 0))
        self.assertEqual(normalized_to_extent(0.5, 0.5), (32768, 32768))
        self.assertEqual(
            normalized_to_extent(-1.0, 2.0),
            (0, POINTER_EXTENT),
        )

    def test_invalid_coordinates_and_wire_values_are_rejected(self):
        for value in (math.inf, -math.inf, math.nan):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalized_to_extent(value, 0.5)
        with self.assertRaises(TypeError):
            normalized_to_extent(True, 0.5)
        self.assertEqual(
            validate_wayland_fixed(WAYLAND_FIXED_MAX, "value"), WAYLAND_FIXED_MAX
        )
        self.assertEqual(validate_int32(INT32_MAX, "value"), INT32_MAX)
        with self.assertRaises(ValueError):
            validate_wayland_fixed(WAYLAND_FIXED_MAX + 1, "value")

    def test_talon_buttons_map_to_linux_codes(self):
        self.assertEqual(
            [linux_button_code(index) for index in range(3)], [0x110, 0x111, 0x112]
        )
        with self.assertRaises(TypeError):
            linux_button_code(True)
        with self.assertRaises(ValueError):
            linux_button_code(3)


class VirtualPointerTests(unittest.TestCase):
    def setUp(self):
        self.connection = ImmediateConnection()
        self.seats = SeatRegistry(self.connection)
        self.pointer_adapter = VirtualPointer(
            self.connection,
            self.seats,
            timestamp_ms=lambda: 1234,
        )
        self.registry = FakeRegistry()
        self.seats.bind(self.registry, 20, 11, interface(11))
        self.pointer_adapter.bind(self.registry, 10, 2, interface(2))
        self.manager = self.registry.bound[1][3]
        self.pointer = self.manager.created_pointers[0]
        self.pointer.calls.clear()

    def test_emits_expected_motion_button_and_scroll_order(self):
        self.pointer_adapter.move_absolute(-1.0, 2.0, refresh_hover=True)
        self.pointer_adapter.move_relative(2.5, -3.5)
        self.pointer_adapter.set_button(0, True)
        self.pointer_adapter.set_button(0, True)
        self.pointer_adapter.set_button(0, False)
        self.pointer_adapter.click(1)
        self.pointer_adapter.scroll(2, -1)

        self.assertEqual(
            self.pointer.calls,
            [
                ("motion_absolute", 1234, 0, 65535, 65535, 65535),
                ("frame",),
                ("motion", 1234, 1.0, 0.0),
                ("frame",),
                ("motion", 1234, -1.0, 0.0),
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

    def test_toggle_release_and_teardown_are_state_safe(self):
        self.assertTrue(self.pointer_adapter.toggle_button(2))
        self.assertFalse(self.pointer_adapter.toggle_button(2))
        self.pointer_adapter.set_button(2, True)
        self.assertTrue(self.pointer_adapter.release_all())
        self.assertFalse(self.pointer_adapter.release_all())
        self.pointer_adapter.set_button(0, True)
        self.pointer_adapter.close()
        self.pointer_adapter.close()
        self.assertFalse(self.pointer_adapter.available())
        self.assertEqual(
            self.pointer.calls[-3:],
            [("button", 1234, 0x110, 0), ("frame",), ("destroy",)],
        )
        self.assertEqual(self.manager.calls.count(("destroy",)), 1)

    def test_seat_replacement_recreates_pointer_before_old_seat_release(self):
        first_pointer = self.pointer
        first_seat = self.registry.bound[0][3]
        self.registry.event_log.clear()
        self.seats.bind(self.registry, 21, 11, interface(11))
        second_seat = self.registry.bound[2][3]
        second_seat.dispatcher["name"](second_seat, "seat0")

        self.assertTrue(first_pointer.destroyed)
        self.assertLess(
            self.registry.event_log.index((first_pointer, "destroy")),
            self.registry.event_log.index((self.manager, "create_virtual_pointer")),
        )
        self.assertFalse(first_seat.destroyed)

    def test_protocol_failure_stops_connection_and_preserves_uncertain_state(self):
        with patch.object(
            self.pointer,
            "frame",
            side_effect=RuntimeError("frame failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "frame failed"):
                self.pointer_adapter.click()

        self.assertTrue(self.connection.stopping)
        self.assertEqual(str(self.connection.failures[0]), "frame failed")
        self.pointer_adapter.close()
        self.assertFalse(self.pointer_adapter.available())

    def test_close_releases_manager_after_button_cleanup_failure(self):
        self.pointer_adapter.set_button(0, True)
        with patch.object(
            self.pointer,
            "frame",
            side_effect=RuntimeError("release failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "release failed"):
                self.pointer_adapter.close()
        self.assertTrue(self.pointer.destroyed)
        self.assertTrue(self.manager.destroyed)
        self.assertFalse(self.pointer_adapter.available())

    def test_close_continues_releasing_buttons_after_one_failure(self):
        self.pointer_adapter.set_button(0, True)
        self.pointer_adapter.set_button(1, True)
        original_button = self.pointer.button
        attempted = []

        def release(timestamp, code, state):
            attempted.append(code)
            if code == 0x110:
                raise RuntimeError("left release failed")
            original_button(timestamp, code, state)

        with patch.object(self.pointer, "button", side_effect=release):
            with self.assertRaisesRegex(RuntimeError, "left release failed"):
                self.pointer_adapter.close()

        self.assertEqual(attempted, [0x110, 0x111])
        self.assertIn(("frame",), self.pointer.calls)
        self.assertTrue(self.pointer.destroyed)
        self.assertTrue(self.manager.destroyed)

    def test_release_all_continues_after_one_button_failure(self):
        self.pointer_adapter.set_button(0, True)
        self.pointer_adapter.set_button(1, True)
        original_button = self.pointer.button
        attempted = []

        def release(timestamp, code, state):
            attempted.append(code)
            if code == 0x110:
                raise RuntimeError("left release failed")
            original_button(timestamp, code, state)

        with patch.object(self.pointer, "button", side_effect=release):
            with self.assertRaisesRegex(RuntimeError, "left release failed"):
                self.pointer_adapter.release_all()

        self.assertEqual(attempted, [0x110, 0x111])
        self.assertEqual(self.pointer_adapter._held_buttons, {0x110})

    def test_zero_scroll_validates_availability_without_emitting(self):
        self.pointer_adapter.scroll()
        self.assertEqual(self.pointer.calls, [])
        self.pointer_adapter.close()
        with self.assertRaisesRegex(RuntimeError, "not available"):
            self.pointer_adapter.scroll()


if __name__ == "__main__":
    unittest.main()
