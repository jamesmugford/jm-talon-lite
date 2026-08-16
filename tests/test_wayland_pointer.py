import math
import sys
import unittest
from pathlib import Path

_plugins_dir = Path(__file__).resolve().parents[1] / "plugins"
_added_plugins_path = str(_plugins_dir) not in sys.path
if _added_plugins_path:
    sys.path.insert(0, str(_plugins_dir))
try:
    from wayland_backend.pointer import (
        INT32_MAX,
        POINTER_EXTENT,
        WAYLAND_FIXED_MAX,
        linux_button_code,
        normalized_to_extent,
        validate_int32,
        validate_wayland_fixed,
    )
finally:
    if _added_plugins_path:
        sys.path.remove(str(_plugins_dir))


class WaylandPointerValueTests(unittest.TestCase):
    def test_normalized_coordinates_use_inclusive_extent(self):
        self.assertEqual(normalized_to_extent(0.0, 0.0), (0, 0))
        self.assertEqual(
            normalized_to_extent(1.0, 1.0),
            (POINTER_EXTENT, POINTER_EXTENT),
        )
        self.assertEqual(normalized_to_extent(0.5, 0.5), (32768, 32768))

    def test_normalized_coordinates_are_clamped(self):
        self.assertEqual(
            normalized_to_extent(-1.0, 2.0),
            (0, POINTER_EXTENT),
        )
        self.assertEqual(
            normalized_to_extent(-(10**400), 10**400),
            (0, POINTER_EXTENT),
        )

    def test_invalid_coordinates_and_extent_are_rejected(self):
        for value in (math.inf, -math.inf, math.nan):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalized_to_extent(value, 0.5)
        with self.assertRaises(TypeError):
            normalized_to_extent(True, 0.5)
        with self.assertRaises(TypeError):
            normalized_to_extent(0.5, False)
        with self.assertRaises(TypeError):
            normalized_to_extent(0.5, 0.5, extent=True)
        with self.assertRaises(TypeError):
            normalized_to_extent(0.5, 0.5, extent=1.0)
        with self.assertRaises(ValueError):
            normalized_to_extent(0.5, 0.5, extent=0)
        with self.assertRaises(ValueError):
            normalized_to_extent(0.5, 0.5, extent=1 << 32)

    def test_talon_buttons_map_to_linux_codes(self):
        self.assertEqual(linux_button_code(0), 0x110)
        self.assertEqual(linux_button_code(1), 0x111)
        self.assertEqual(linux_button_code(2), 0x112)
        with self.assertRaises(TypeError):
            linux_button_code(True)
        with self.assertRaises(TypeError):
            linux_button_code(1.0)
        with self.assertRaises(ValueError):
            linux_button_code(3)

    def test_wayland_wire_ranges_are_validated(self):
        self.assertEqual(validate_wayland_fixed(WAYLAND_FIXED_MAX, "value"), WAYLAND_FIXED_MAX)
        self.assertEqual(validate_int32(INT32_MAX, "value"), INT32_MAX)
        with self.assertRaises(ValueError):
            validate_wayland_fixed(WAYLAND_FIXED_MAX + 1, "value")
        with self.assertRaises(ValueError):
            validate_wayland_fixed(10**400, "value")
        with self.assertRaises(ValueError):
            validate_int32(INT32_MAX + 1, "value")
        with self.assertRaises(TypeError):
            validate_wayland_fixed(True, "value")
        with self.assertRaises(TypeError):
            validate_int32(1.0, "value")


if __name__ == "__main__":
    unittest.main()
