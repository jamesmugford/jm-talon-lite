import os
import sys
import tempfile
import unittest
from pathlib import Path

_plugins_dir = Path(__file__).resolve().parents[1] / "plugins"
_added_plugins_path = str(_plugins_dir) not in sys.path
if _added_plugins_path:
    sys.path.insert(0, str(_plugins_dir))
try:
    from wayland_backend.keyboard import (
        KEY_MAX,
        KeyStroke,
        XkbKeymap,
        create_keymap_fd,
        parse_key_spec,
        read_keymap_fd,
        validate_keycode,
    )
finally:
    if _added_plugins_path:
        sys.path.remove(str(_plugins_dir))


_US_KEYMAP = b"""xkb_keymap {
    xkb_keycodes { include "evdev+aliases(qwerty)" };
    xkb_types { include "complete" };
    xkb_compatibility { include "complete" };
    xkb_symbols { include "pc+us" };
};
\0"""

_US_GB_KEYMAP = b"""xkb_keymap {
    xkb_keycodes { include "evdev+aliases(qwerty)" };
    xkb_types { include "complete" };
    xkb_compatibility { include "complete" };
    xkb_symbols { include "pc+us+gb:2+inet(evdev)" };
};
\0"""


class TalonKeySpecTests(unittest.TestCase):
    def test_parses_sequences_chords_and_repeats(self):
        self.assertEqual(
            parse_key_spec("ctrl-, ctrl-f esc:2 shift:down shift:up"),
            (
                KeyStroke(("ctrl",), ",", "tap", 1),
                KeyStroke(("ctrl",), "f", "tap", 1),
                KeyStroke((), "esc", "tap", 2),
                KeyStroke(("shift",), None, "down", 1),
                KeyStroke(("shift",), None, "up", 1),
            ),
        )

    def test_literal_hyphen_and_colon_remain_keys(self):
        self.assertEqual(
            parse_key_spec("- ctrl-- :"),
            (
                KeyStroke((), "-", "tap", 1),
                KeyStroke(("ctrl",), "-", "tap", 1),
                KeyStroke((), ":", "tap", 1),
            ),
        )

    def test_empty_spec_is_a_noop(self):
        self.assertEqual(parse_key_spec("  "), ())

    def test_invalid_spec_is_rejected(self):
        for value in (":down", "a:0"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_key_spec(value)
        with self.assertRaises(TypeError):
            parse_key_spec(1)


class XkbKeymapTests(unittest.TestCase):
    def setUp(self):
        self.keymap = XkbKeymap(_US_KEYMAP)

    def tearDown(self):
        self.keymap.close()

    def test_resolves_characters_with_keymap_modifiers(self):
        self.assertEqual(self.keymap.resolve_key("a"), (30, ()))
        self.assertEqual(self.keymap.resolve_key("A"), (30, (42,)))
        self.assertEqual(self.keymap.resolve_key("!"), (2, (42,)))

    def test_resolves_talon_named_keys(self):
        self.assertEqual(self.keymap.resolve_key("esc"), (1, ()))
        self.assertEqual(self.keymap.resolve_key("pageup"), (104, ()))
        self.assertEqual(self.keymap.resolve_key("keypad_1"), (79, ()))
        self.assertEqual(self.keymap.resolve_modifier("ctrl"), 29)

    def test_tracks_modifier_protocol_state(self):
        depressed = self.keymap.update_key(42, True)
        released = self.keymap.update_key(42, False)

        self.assertIsNotNone(depressed)
        self.assertNotEqual(depressed[0], 0)
        self.assertEqual(depressed[1:], (0, 0, 0))
        self.assertEqual(released, (0, 0, 0, 0))

    def test_locked_modifiers_change_character_resolution(self):
        self.assertEqual(self.keymap.resolve_key("a"), (30, ()))

        self.assertEqual(self.keymap.set_external_state(2, 0), (0, 0, 2, 0))

        self.assertEqual(self.keymap.resolve_key("a"), (30, (42,)))
        self.assertEqual(self.keymap.resolve_key("A"), (30, ()))

    def test_active_layout_changes_character_resolution(self):
        keymap = XkbKeymap(_US_GB_KEYMAP)
        try:
            with self.assertRaisesRegex(ValueError, "not available"):
                keymap.resolve_key("£")

            self.assertEqual(keymap.set_external_state(0, 1), (0, 0, 0, 1))

            self.assertEqual(keymap.resolve_key("£"), (4, (42,)))
        finally:
            keymap.close()

    def test_rejects_unknown_or_unavailable_keys(self):
        with self.assertRaisesRegex(ValueError, "Unknown Talon key"):
            self.keymap.resolve_key("definitely_not_a_key")
        with self.assertRaisesRegex(ValueError, "not available"):
            self.keymap.resolve_key("£")


class WaylandKeyboardValueTests(unittest.TestCase):
    @staticmethod
    def _keymap_fd(data: bytes) -> int:
        with tempfile.TemporaryFile() as keymap_file:
            keymap_file.write(data)
            keymap_file.flush()
            return os.dup(keymap_file.fileno())

    def test_linux_keycodes_are_validated(self):
        self.assertEqual(validate_keycode(1), 1)
        self.assertEqual(validate_keycode(KEY_MAX), KEY_MAX)
        for value in (0, KEY_MAX + 1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_keycode(value)
        for value in (True, 1.0, "1"):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    validate_keycode(value)

    def test_received_keymap_is_copied_and_fd_is_closed(self):
        data = b"xkb_keymap {}\n\0"
        fd = self._keymap_fd(data)

        self.assertEqual(read_keymap_fd(fd, len(data)), data)
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_invalid_received_keymap_still_closes_fd(self):
        data = b"not-null-terminated"
        fd = self._keymap_fd(data)

        with self.assertRaisesRegex(ValueError, "null-terminated"):
            read_keymap_fd(fd, len(data))
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_outgoing_keymap_fd_contains_exact_bytes(self):
        data = b"xkb_keymap {}\n\0"
        fd = create_keymap_fd(data)
        try:
            self.assertEqual(os.pread(fd, len(data), 0), data)
            self.assertEqual(os.lseek(fd, 0, os.SEEK_CUR), 0)
        finally:
            os.close(fd)


if __name__ == "__main__":
    unittest.main()
