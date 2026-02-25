import sys
import unittest
from pathlib import Path

class SharedPureUtilsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins_dir = Path(__file__).resolve().parents[1] / "plugins"
        added = False
        if str(plugins_dir) not in sys.path:
            sys.path.insert(0, str(plugins_dir))
            added = True
        try:
            from shared import pure_utils

            cls.core = pure_utils
        finally:
            if added:
                sys.path.remove(str(plugins_dir))

    def test_should_emit_state_change(self):
        self.assertFalse(self.core.should_emit_state_change(False, False))
        self.assertFalse(self.core.should_emit_state_change(True, True))
        self.assertTrue(self.core.should_emit_state_change(False, True))
        self.assertTrue(self.core.should_emit_state_change(True, False))

    def test_desktop_bounds_empty_defaults(self):
        self.assertEqual(
            self.core.desktop_bounds_from_rects([]),
            (0.0, 0.0, 1.0, 1.0),
        )

    def test_desktop_bounds_multi_screen(self):
        rects = [
            (0.0, 0.0, 1920.0, 1080.0),
            (1920.0, 0.0, 1280.0, 1024.0),
            (-1200.0, 0.0, 1200.0, 1920.0),
        ]
        self.assertEqual(
            self.core.desktop_bounds_from_rects(rects),
            (-1200.0, 0.0, 4400.0, 1920.0),
        )

    def test_normalize_point_clamps(self):
        bounds = (0.0, 0.0, 100.0, 200.0)
        self.assertEqual(self.core.normalize_point(bounds, 50.0, 100.0), (0.5, 0.5))
        self.assertEqual(self.core.normalize_point(bounds, -10.0, -5.0), (0.0, 0.0))
        self.assertEqual(self.core.normalize_point(bounds, 1000.0, 500.0), (1.0, 1.0))

    def test_rect_local_point(self):
        rect = (10.0, 20.0, 100.0, 60.0)
        self.assertEqual(self.core.rect_local_point(rect, 15.0, 25.0), (5.0, 5.0))
        self.assertEqual(self.core.rect_local_point(rect, 110.0, 80.0), (100.0, 60.0))
        self.assertIsNone(self.core.rect_local_point(rect, 9.9, 25.0))

    def test_format_control1_sample(self):
        line_no_delta = self.core.format_control1_sample(
            timestamp=1.2345,
            xy_px=(100.0, 200.0),
            gaze_norm=(0.25, 0.75),
            delta=None,
        )
        self.assertIn("control1 ts=1.234", line_no_delta)
        self.assertIn("xy_px=(100.0,200.0)", line_no_delta)
        self.assertIn("gaze_norm=(0.250,0.750)", line_no_delta)
        self.assertNotIn("delta=", line_no_delta)

        line_with_delta = self.core.format_control1_sample(
            timestamp=2.0,
            xy_px=(50.0, 60.0),
            gaze_norm=(0.1, 0.2),
            delta=(1.234, -2.345),
        )
        self.assertIn("delta=(1.23,-2.35)", line_with_delta)


if __name__ == "__main__":
    unittest.main()
