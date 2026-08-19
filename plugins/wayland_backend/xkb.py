"""Stateful libxkbcommon adapter and keymap file-descriptor helpers."""

from __future__ import annotations

import ctypes
import mmap
import os
import tempfile
from functools import cache
from itertools import combinations

KEY_MAX = 0x2FF
KEYMAP_FORMAT_XKB_V1 = 1
MAX_KEYMAP_SIZE = 16 * 1024 * 1024

_XKB_KEY_UP = 0
_XKB_KEY_DOWN = 1
_XKB_KEYSYM_CASE_INSENSITIVE = 1
_XKB_STATE_MODS_DEPRESSED = 1 << 0
_XKB_STATE_MODS_LATCHED = 1 << 1
_XKB_STATE_MODS_LOCKED = 1 << 2
_XKB_STATE_LAYOUT_EFFECTIVE = 1 << 7
_XKB_STATE_MODIFIERS = (
    _XKB_STATE_MODS_DEPRESSED | _XKB_STATE_MODS_LATCHED | _XKB_STATE_MODS_LOCKED
)

_MODIFIER_KEYSYMS = {
    "ctrl": "Control_L",
    "alt": "Alt_L",
    "shift": "Shift_L",
    "super": "Super_L",
}
_LEVEL_MODIFIER_KEYSYMS = (
    "Shift_L",
    "ISO_Level3_Shift",
    "ISO_Level5_Shift",
    "Mode_switch",
)
_KEYSYM_ALIASES = {
    "esc": "Escape",
    "enter": "Return",
    "space": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "Page_Up",
    "pagedown": "Page_Down",
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
    "menu": "Menu",
    "printscr": "Print",
    "minus": "-",
    "volup": "XF86AudioRaiseVolume",
    "voldown": "XF86AudioLowerVolume",
    "mute": "XF86AudioMute",
    "play": "XF86AudioPlay",
    "play_pause": "XF86AudioPlay",
    "next": "XF86AudioNext",
    "prev": "XF86AudioPrev",
}
_KEYPAD_KEY_NAMES = {
    **{str(number): f"KP{number}" for number in range(10)},
    "decimal": "KPDL",
    "plus": "KPAD",
    "minus": "KPSU",
    "multiply": "KPMU",
    "divide": "KPDV",
    "equals": "KPEQ",
    "clear": "KP5",
    "enter": "KPEN",
}


class XkbKeymap:
    """Resolve keysyms and track modifiers for one XKB-v1 keymap."""

    def __init__(self, data: bytes, locked_modifiers: int = 0, group: int = 0) -> None:
        """Create an XKB context and state from null-terminated keymap data."""
        if not isinstance(data, bytes) or not data.endswith(b"\0"):
            raise ValueError("XKB-v1 keymap must be null-terminated bytes")

        self._lib = _load_xkbcommon()
        self._context = self._lib.xkb_context_new(0)
        self._keymap = None
        self._state = None
        self._pressed_keys: list[int] = []
        self._locked_modifiers = _validate_uint32(
            locked_modifiers, "XKB locked modifiers"
        )
        self._group = _validate_uint32(group, "XKB layout group")
        if not self._context:
            raise RuntimeError("Could not create an XKB context")
        try:
            self._keymap = self._lib.xkb_keymap_new_from_string(
                self._context,
                data,
                KEYMAP_FORMAT_XKB_V1,
                0,
            )
            if not self._keymap:
                raise ValueError("Could not parse the compositor XKB keymap")
            self._state = self._new_state()
            self._keys, self._modifiers = self._build_key_index()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Release every libxkbcommon resource owned by this keymap."""
        if self._state:
            self._lib.xkb_state_unref(self._state)
            self._state = None
        if self._keymap:
            self._lib.xkb_keymap_unref(self._keymap)
            self._keymap = None
        if self._context:
            self._lib.xkb_context_unref(self._context)
            self._context = None

    def resolve_key(self, name: str) -> tuple[int, tuple[int, ...]]:
        """Return a Linux keycode and implicit modifiers for a Talon key."""
        normalized = name.lower()
        if normalized.startswith("keypad_"):
            key_name = _KEYPAD_KEY_NAMES.get(normalized.removeprefix("keypad_"))
            if key_name is None:
                raise ValueError(f"Unknown Talon key: {name!r}")
            xkb_keycode = self._lib.xkb_keymap_key_by_name(
                self._keymap, key_name.encode("ascii")
            )
            if xkb_keycode != 0xFFFFFFFF:
                return validate_keycode(xkb_keycode - 8), ()
            raise ValueError(f"Key {name!r} is not available in the active keymap")

        keysym = self._keysym(name)
        resolved = self._keys.get(keysym)
        if resolved is None:
            raise ValueError(f"Key {name!r} is not available in the active keymap")
        return resolved

    def resolve_modifier(self, name: str) -> int:
        """Return the active keymap's Linux keycode for a Talon modifier."""
        try:
            return self._modifiers[name]
        except KeyError as exc:
            raise ValueError(
                f"Modifier {name!r} is not available in the active keymap"
            ) from exc

    def modifiers(self) -> tuple[int, int, int, int]:
        """Return depressed, latched, locked, and group protocol values."""
        return self._serialize_modifiers()

    def set_external_state(
        self, locked_modifiers: int, group: int
    ) -> tuple[int, int, int, int] | None:
        """Apply source-keyboard lock and layout state without physical holds."""
        locked_modifiers = _validate_uint32(locked_modifiers, "XKB locked modifiers")
        group = _validate_uint32(group, "XKB layout group")
        if locked_modifiers == self._locked_modifiers and group == self._group:
            return None

        self._locked_modifiers = locked_modifiers
        self._group = group
        state = self._new_state()
        try:
            for keycode in self._pressed_keys:
                self._lib.xkb_state_update_key(state, keycode + 8, _XKB_KEY_DOWN)
        except Exception:
            self._lib.xkb_state_unref(state)
            raise
        old_state = self._state
        self._state = state
        self._lib.xkb_state_unref(old_state)
        self._keys, self._modifiers = self._build_key_index()
        return self._serialize_modifiers()

    def update_key(
        self, keycode: int, pressed: bool
    ) -> tuple[int, int, int, int] | None:
        """Update one key state and return changed protocol modifiers."""
        changed = self._lib.xkb_state_update_key(
            self._state,
            validate_keycode(keycode) + 8,
            _XKB_KEY_DOWN if pressed else _XKB_KEY_UP,
        )
        if pressed and keycode not in self._pressed_keys:
            self._pressed_keys.append(keycode)
        if not pressed and keycode in self._pressed_keys:
            self._pressed_keys.remove(keycode)
        if not changed & (_XKB_STATE_MODIFIERS | _XKB_STATE_LAYOUT_EFFECTIVE):
            return None
        modifiers = self._serialize_modifiers()
        if modifiers[2] != self._locked_modifiers or modifiers[3] != self._group:
            self._locked_modifiers = modifiers[2]
            self._group = modifiers[3]
            self._keys, self._modifiers = self._build_key_index()
        return modifiers

    def _serialize_modifiers(self) -> tuple[int, int, int, int]:
        """Serialize the current XKB modifier and layout state."""
        return (
            self._lib.xkb_state_serialize_mods(self._state, _XKB_STATE_MODS_DEPRESSED),
            self._lib.xkb_state_serialize_mods(self._state, _XKB_STATE_MODS_LATCHED),
            self._lib.xkb_state_serialize_mods(self._state, _XKB_STATE_MODS_LOCKED),
            self._lib.xkb_state_serialize_layout(
                self._state, _XKB_STATE_LAYOUT_EFFECTIVE
            ),
        )

    def _new_state(self):
        """Create an XKB state initialized with external lock and group values."""
        state = self._lib.xkb_state_new(self._keymap)
        if not state:
            raise RuntimeError("Could not create XKB keyboard state")
        self._lib.xkb_state_update_mask(
            state,
            0,
            0,
            self._locked_modifiers,
            0,
            0,
            self._group,
        )
        return state

    def _build_key_index(
        self,
    ) -> tuple[dict[int, tuple[int, tuple[int, ...]]], dict[str, int]]:
        """Index keysyms and modifiers for the current layout and lock state."""
        minimum = self._lib.xkb_keymap_min_keycode(self._keymap)
        maximum = self._lib.xkb_keymap_max_keycode(self._keymap)
        base_state = self._new_state()
        try:
            base_keys = {
                self._lib.xkb_state_key_get_one_sym(base_state, keycode): keycode - 8
                for keycode in range(minimum, maximum + 1)
                if keycode >= 9
            }
        finally:
            self._lib.xkb_state_unref(base_state)

        modifiers = {}
        for name, keysym_name in _MODIFIER_KEYSYMS.items():
            keycode = base_keys.get(self._named_keysym(keysym_name))
            if keycode is not None:
                modifiers[name] = keycode

        level_modifiers = []
        for keysym_name in _LEVEL_MODIFIER_KEYSYMS:
            keycode = base_keys.get(self._named_keysym(keysym_name))
            if keycode is not None and keycode not in level_modifiers:
                level_modifiers.append(keycode)

        keys = {}
        for count in range(len(level_modifiers) + 1):
            for active_modifiers in combinations(level_modifiers, count):
                state = self._new_state()
                try:
                    for keycode in active_modifiers:
                        self._lib.xkb_state_update_key(
                            state, keycode + 8, _XKB_KEY_DOWN
                        )
                    for xkb_keycode in range(minimum, maximum + 1):
                        if xkb_keycode < 9:
                            continue
                        keysym = self._lib.xkb_state_key_get_one_sym(state, xkb_keycode)
                        if keysym:
                            keys.setdefault(
                                keysym,
                                (xkb_keycode - 8, active_modifiers),
                            )
                finally:
                    self._lib.xkb_state_unref(state)
        return keys, modifiers

    def _keysym(self, name: str) -> int:
        """Resolve a Talon key name to an XKB keysym."""
        if len(name) == 1:
            keysym = self._lib.xkb_utf32_to_keysym(ord(name))
        else:
            normalized = name.lower()
            keysym_name = _KEYSYM_ALIASES.get(normalized, name)
            if len(keysym_name) == 1:
                keysym = self._lib.xkb_utf32_to_keysym(ord(keysym_name))
            else:
                keysym = self._named_keysym(keysym_name)
        if not keysym:
            raise ValueError(f"Unknown Talon key: {name!r}")
        return keysym

    def _named_keysym(self, name: str) -> int:
        """Resolve an ASCII XKB symbol name case-insensitively."""
        return self._lib.xkb_keysym_from_name(
            name.encode("ascii"), _XKB_KEYSYM_CASE_INSENSITIVE
        )


@cache
def _load_xkbcommon():
    """Load and configure the process-wide libxkbcommon C interface."""
    lib = ctypes.CDLL("libxkbcommon.so.0")
    void_pointer = ctypes.c_void_p
    uint32_pointer = ctypes.c_uint32

    lib.xkb_context_new.argtypes = [ctypes.c_int]
    lib.xkb_context_new.restype = void_pointer
    lib.xkb_context_unref.argtypes = [void_pointer]
    lib.xkb_context_unref.restype = None
    lib.xkb_keymap_new_from_string.argtypes = [
        void_pointer,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.xkb_keymap_new_from_string.restype = void_pointer
    lib.xkb_keymap_unref.argtypes = [void_pointer]
    lib.xkb_keymap_unref.restype = None
    lib.xkb_keymap_min_keycode.argtypes = [void_pointer]
    lib.xkb_keymap_min_keycode.restype = uint32_pointer
    lib.xkb_keymap_max_keycode.argtypes = [void_pointer]
    lib.xkb_keymap_max_keycode.restype = uint32_pointer
    lib.xkb_keymap_key_by_name.argtypes = [void_pointer, ctypes.c_char_p]
    lib.xkb_keymap_key_by_name.restype = uint32_pointer
    lib.xkb_state_new.argtypes = [void_pointer]
    lib.xkb_state_new.restype = void_pointer
    lib.xkb_state_unref.argtypes = [void_pointer]
    lib.xkb_state_unref.restype = None
    lib.xkb_state_key_get_one_sym.argtypes = [void_pointer, uint32_pointer]
    lib.xkb_state_key_get_one_sym.restype = uint32_pointer
    lib.xkb_state_update_key.argtypes = [
        void_pointer,
        uint32_pointer,
        ctypes.c_int,
    ]
    lib.xkb_state_update_key.restype = ctypes.c_int
    lib.xkb_state_update_mask.argtypes = [
        void_pointer,
        uint32_pointer,
        uint32_pointer,
        uint32_pointer,
        uint32_pointer,
        uint32_pointer,
        uint32_pointer,
    ]
    lib.xkb_state_update_mask.restype = ctypes.c_int
    lib.xkb_state_serialize_mods.argtypes = [void_pointer, ctypes.c_int]
    lib.xkb_state_serialize_mods.restype = uint32_pointer
    lib.xkb_state_serialize_layout.argtypes = [void_pointer, ctypes.c_int]
    lib.xkb_state_serialize_layout.restype = uint32_pointer
    lib.xkb_keysym_from_name.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.xkb_keysym_from_name.restype = uint32_pointer
    lib.xkb_utf32_to_keysym.argtypes = [uint32_pointer]
    lib.xkb_utf32_to_keysym.restype = uint32_pointer

    return lib


def _validate_uint32(value: int, label: str) -> int:
    """Return an integer that fits the Wayland unsigned 32-bit range."""
    if type(value) is not int:
        raise TypeError(f"{label} must be an integer")
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{label} must fit an unsigned 32-bit integer")
    return value


def validate_keycode(keycode: int) -> int:
    """Return a supported Linux evdev keycode."""
    if type(keycode) is not int:
        raise TypeError("Keyboard keycode must be an integer")
    if not 1 <= keycode <= KEY_MAX:
        raise ValueError(f"Keyboard keycode must be between 1 and {KEY_MAX}")
    return keycode


def read_keymap_fd(fd: int, size: int) -> bytes:
    """Copy an XKB-v1 keymap and close the received Wayland descriptor."""
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
    """Return a caller-owned anonymous descriptor containing an XKB keymap."""
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
