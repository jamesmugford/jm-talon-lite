"""Virtual-keyboard keycode and keymap file-descriptor helpers."""

from __future__ import annotations

import mmap
import os
import tempfile


KEY_MAX = 0x2FF
KEYMAP_FORMAT_XKB_V1 = 1
MAX_KEYMAP_SIZE = 16 * 1024 * 1024


def validate_keycode(keycode: int) -> int:
    """Return a supported Linux evdev keycode."""
    if type(keycode) is not int:
        raise TypeError("Keyboard keycode must be an integer")
    if not 1 <= keycode <= KEY_MAX:
        raise ValueError(f"Keyboard keycode must be between 1 and {KEY_MAX}")
    return keycode


def read_keymap_fd(fd: int, size: int) -> bytes:
    """Copy an XKB-v1 keymap and close the received Wayland file descriptor."""
    try:
        if type(size) is not int:
            raise TypeError("Keyboard keymap size must be an integer")
        if not 1 <= size <= MAX_KEYMAP_SIZE:
            raise ValueError("Keyboard keymap size is outside the supported range")
        if os.fstat(fd).st_size < size:
            raise ValueError("Keyboard keymap file is shorter than its declared size")
        with mmap.mmap(
            fd,
            size,
            flags=mmap.MAP_PRIVATE,
            prot=mmap.PROT_READ,
        ) as mapping:
            data = mapping[:]
        if not data.endswith(b"\0"):
            raise ValueError("XKB-v1 keymap must be null-terminated")
        return data
    finally:
        os.close(fd)


def create_keymap_fd(data: bytes) -> int:
    """Return a caller-owned anonymous FD containing an XKB-v1 keymap copy."""
    if not isinstance(data, bytes):
        raise TypeError("Keyboard keymap must be bytes")
    if not 1 <= len(data) <= MAX_KEYMAP_SIZE:
        raise ValueError("Keyboard keymap size is outside the supported range")
    if not data.endswith(b"\0"):
        raise ValueError("XKB-v1 keymap must be null-terminated")

    with tempfile.TemporaryFile() as keymap_file:
        if keymap_file.write(data) != len(data):
            raise OSError("Could not write keyboard keymap")
        keymap_file.flush()
        fd = os.dup(keymap_file.fileno())
    os.lseek(fd, 0, os.SEEK_SET)
    return fd
