import unittest
from unittest import mock
import sys
from pathlib import Path


class XkbResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins_dir = Path(__file__).resolve().parents[1] / "plugins"
        sys.path.insert(0, str(plugins_dir))
        from input_backend.xkb import XkbKeymap

        cls.XkbKeymap = XkbKeymap

    @classmethod
    def tearDownClass(cls):
        plugins_dir = str(Path(__file__).resolve().parents[1] / "plugins")
        if plugins_dir in sys.path:
            sys.path.remove(plugins_dir)

    def test_us_layout_resolves_symbols_and_modifiers(self):
        keymap = self.XkbKeymap(layout="us")
        try:
            self.assertEqual(keymap.resolve("minus").code, 12)
            exclam = keymap.resolve("exclam")
            self.assertEqual(exclam.code, 2)
            self.assertEqual(exclam.modifiers, ("shift",))
            self.assertEqual(keymap.modifier_codes["ctrl"], 29)
            self.assertEqual(keymap.modifier_codes["altgr"], 84)
        finally:
            keymap.close()

    def test_non_us_layouts_resolve_logical_keys(self):
        french = self.XkbKeymap(layout="fr")
        german = self.XkbKeymap(layout="de")
        try:
            self.assertEqual(french.resolve("a").code, 16)
            self.assertEqual(french.resolve("1").modifiers, ("shift",))
            self.assertEqual(french.resolve("at").modifiers, ("altgr",))
            self.assertEqual(german.resolve("z").code, 21)
        finally:
            french.close()
            german.close()

    def test_unicode_character_resolves_through_xkb(self):
        keymap = self.XkbKeymap(layout="gb")
        try:
            sterling = keymap.resolve_character("£")
            self.assertIsNotNone(sterling)
            self.assertEqual(sterling.modifiers, ("shift",))
        finally:
            keymap.close()

    def test_multiple_layouts_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Only one"):
            self.XkbKeymap(layout="us,fr")

    def test_layout_is_required(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "XKB_DEFAULT_LAYOUT"):
                self.XkbKeymap()


if __name__ == "__main__":
    unittest.main()
