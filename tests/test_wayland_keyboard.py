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
        create_keymap_fd,
        read_keymap_fd,
        validate_keycode,
    )
finally:
    if _added_plugins_path:
        sys.path.remove(str(_plugins_dir))


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
