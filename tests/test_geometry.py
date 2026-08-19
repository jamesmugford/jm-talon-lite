import sys
import unittest
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
sys.path.insert(0, str(PLUGINS))
try:
    from wayland_backend.geometry import desktop_bounds, local_point, normalize_point
    from wayland_backend.scroll import accumulate_steps
finally:
    sys.path.remove(str(PLUGINS))


class GeometryTests(unittest.TestCase):
    def test_desktop_bounds_cover_multiple_offset_screens(self):
        rects = (
            (0.0, 0.0, 1920.0, 1080.0),
            (1920.0, 0.0, 1280.0, 1024.0),
            (-1200.0, 0.0, 1200.0, 1920.0),
        )
        self.assertEqual(desktop_bounds(rects), (-1200.0, 0.0, 4400.0, 1920.0))
        self.assertEqual(desktop_bounds(()), (0.0, 0.0, 1.0, 1.0))

    def test_normalization_and_local_points_are_bounded(self):
        bounds = (0.0, 0.0, 100.0, 200.0)
        self.assertEqual(normalize_point(bounds, 50.0, 100.0), (0.5, 0.5))
        self.assertEqual(normalize_point(bounds, -1.0, 500.0), (0.0, 1.0))
        self.assertEqual(local_point((10.0, 20.0, 100.0, 60.0), 15.0, 25.0), (5.0, 5.0))
        self.assertIsNone(local_point((10.0, 20.0, 100.0, 60.0), 9.0, 25.0))

    def test_scroll_accumulator_preserves_fractional_remainder(self):
        steps, remainder = accumulate_steps(0.4, 0.0)
        self.assertEqual(steps, 0)
        steps, remainder = accumulate_steps(0.7, remainder)
        self.assertEqual(steps, 1)
        self.assertAlmostEqual(remainder, 0.1)
        steps, remainder = accumulate_steps(-1.3, remainder)
        self.assertEqual(steps, -1)
        self.assertAlmostEqual(remainder, -0.2)


if __name__ == "__main__":
    unittest.main()
