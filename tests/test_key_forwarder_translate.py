import sys
import unittest
from pathlib import Path

class DotoolTranslateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        apps_dir = Path(__file__).resolve().parents[1] / "apps"
        added = False
        if str(apps_dir) not in sys.path:
            sys.path.insert(0, str(apps_dir))
            added = True
        try:
            from key_forwarder import dotool_translate

            cls.translate = dotool_translate
        finally:
            if added:
                sys.path.remove(str(apps_dir))

    def test_dotool_actions_to_input(self):
        self.assertEqual(self.translate.dotool_actions_to_input([]), "")
        self.assertEqual(
            self.translate.dotool_actions_to_input(["key ctrl+a", "key enter"]),
            "key ctrl+a\nkey enter\n",
        )

    def test_translate_basic_chords(self):
        self.assertEqual(
            self.translate.talon_key_to_dotool_actions("ctrl-a"),
            ["key ctrl+a"],
        )
        self.assertEqual(
            self.translate.talon_key_to_dotool_actions("ctrl:down ctrl-a ctrl:up"),
            ["keydown ctrl", "key ctrl+a", "keyup ctrl"],
        )

    def test_translate_repeat_suffix(self):
        self.assertEqual(
            self.translate.talon_key_to_dotool_actions("esc:3"),
            ["key esc", "key esc", "key esc"],
        )


if __name__ == "__main__":
    unittest.main()
