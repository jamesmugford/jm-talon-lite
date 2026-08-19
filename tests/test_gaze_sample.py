import sys
import unittest
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
sys.path.insert(0, str(PLUGINS))
try:
    from tracking_forwarder.gaze_sample import GazeSample, format_gaze_sample
finally:
    sys.path.remove(str(PLUGINS))


class GazeSampleTests(unittest.TestCase):
    def test_formats_complete_missing_delta_and_empty_samples(self):
        complete = GazeSample(1.25, 100.0, 200.0, 0.4, 0.6, 2.5, -3.5)
        self.assertEqual(
            format_gaze_sample(complete),
            "control1 ts=1.250 xy_px=(100.0,200.0) "
            "delta=(2.50,-3.50) gaze_norm=(0.400,0.600)",
        )
        no_delta = GazeSample(1.25, 100.0, 200.0, 0.4, 0.6)
        self.assertNotIn("delta=", format_gaze_sample(no_delta))
        self.assertEqual(format_gaze_sample(None), "control1 no samples")


if __name__ == "__main__":
    unittest.main()
