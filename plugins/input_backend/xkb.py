"""Narrow ctypes adapter for resolving XKB keysyms to evdev chords."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os


_XKB_KEYCODE_OFFSET = 8
_XKB_KEYCODE_LIMIT = 256
_XKB_MOD_INVALID = 0xFFFFFFFF


class XkbError(RuntimeError):
    pass


@dataclass(frozen=True)
class XkbResolvedKey:
    code: int
    modifiers: tuple[str, ...] = ()


class _RuleNames(ctypes.Structure):
    _fields_ = [
        ("rules", ctypes.c_char_p),
        ("model", ctypes.c_char_p),
        ("layout", ctypes.c_char_p),
        ("variant", ctypes.c_char_p),
        ("options", ctypes.c_char_p),
    ]


def _encoded(value: str | None) -> bytes | None:
    return value.encode("utf-8") if value else None


class XkbKeymap:
    """Compile one XKB layout for Talon key translation."""

    def __init__(
        self,
        layout: str | None = None,
        variant: str | None = None,
        library=ctypes.CDLL,
    ) -> None:
        if layout is None:
            layout = os.environ.get("XKB_DEFAULT_LAYOUT") or None
        if variant is None:
            variant = os.environ.get("XKB_DEFAULT_VARIANT") or None
        if not layout:
            raise XkbError(
                "XKB_DEFAULT_LAYOUT must be set to one keyboard layout."
            )
        if variant and not layout:
            raise XkbError("XKB_DEFAULT_VARIANT requires XKB_DEFAULT_LAYOUT.")
        if layout and "," in layout:
            raise XkbError(
                "Only one XKB_DEFAULT_LAYOUT is supported; layout switching is not tracked."
            )
        if variant and "," in variant:
            raise XkbError("Only one XKB_DEFAULT_VARIANT is supported.")

        try:
            self._lib = library("libxkbcommon.so.0")
        except OSError as exc:
            raise XkbError("libxkbcommon.so.0 is unavailable.") from exc

        self._configure_api()
        self._context = self._lib.xkb_context_new(0)
        if not self._context:
            raise XkbError("Could not create an XKB context.")

        names = _RuleNames(
            None,
            None,
            _encoded(layout),
            _encoded(variant),
            None,
        )
        self._keymap = self._lib.xkb_keymap_new_from_names(
            self._context,
            ctypes.byref(names),
            0,
        )
        if not self._keymap:
            self.close()
            raise XkbError("Could not compile the requested XKB keymap.")

        self._symbols = self._build_symbol_map()
        self.modifier_codes = {
            "super": self._symbol_code("Super_L", 125),
            "altgr": self._symbol_code("ISO_Level3_Shift", 100),
            "ctrl": self._symbol_code("Control_L", 29),
            "alt": self._symbol_code("Alt_L", 56),
            "shift": self._symbol_code("Shift_L", 42),
        }

    def _configure_api(self) -> None:
        lib = self._lib
        lib.xkb_context_new.argtypes = (ctypes.c_int,)
        lib.xkb_context_new.restype = ctypes.c_void_p
        lib.xkb_context_unref.argtypes = (ctypes.c_void_p,)
        lib.xkb_context_unref.restype = None
        lib.xkb_keymap_new_from_names.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(_RuleNames),
            ctypes.c_int,
        )
        lib.xkb_keymap_new_from_names.restype = ctypes.c_void_p
        lib.xkb_keymap_unref.argtypes = (ctypes.c_void_p,)
        lib.xkb_keymap_unref.restype = None
        lib.xkb_keymap_min_keycode.argtypes = (ctypes.c_void_p,)
        lib.xkb_keymap_min_keycode.restype = ctypes.c_uint32
        lib.xkb_keymap_max_keycode.argtypes = (ctypes.c_void_p,)
        lib.xkb_keymap_max_keycode.restype = ctypes.c_uint32
        lib.xkb_keymap_num_levels_for_key.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        )
        lib.xkb_keymap_num_levels_for_key.restype = ctypes.c_uint32
        lib.xkb_keymap_key_get_syms_by_level.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)),
        )
        lib.xkb_keymap_key_get_syms_by_level.restype = ctypes.c_int
        lib.xkb_keymap_key_get_mods_for_level.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_size_t,
        )
        lib.xkb_keymap_key_get_mods_for_level.restype = ctypes.c_size_t
        lib.xkb_keymap_mod_get_index.argtypes = (
            ctypes.c_void_p,
            ctypes.c_char_p,
        )
        lib.xkb_keymap_mod_get_index.restype = ctypes.c_uint32
        lib.xkb_keysym_get_name.argtypes = (
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_size_t,
        )
        lib.xkb_keysym_get_name.restype = ctypes.c_int
        lib.xkb_utf32_to_keysym.argtypes = (ctypes.c_uint32,)
        lib.xkb_utf32_to_keysym.restype = ctypes.c_uint32

    def _modifier_masks(self) -> tuple[tuple[str, int], ...]:
        masks: list[tuple[str, int]] = []
        for name, xkb_name in (
            ("altgr", "Mod5"),
            ("ctrl", "Control"),
            ("alt", "Mod1"),
            ("shift", "Shift"),
        ):
            index = self._lib.xkb_keymap_mod_get_index(
                self._keymap,
                xkb_name.encode("ascii"),
            )
            if index != _XKB_MOD_INVALID:
                masks.append((name, 1 << index))
        return tuple(masks)

    def _level_modifiers(
        self,
        keycode: int,
        level: int,
        modifier_masks: tuple[tuple[str, int], ...],
    ) -> tuple[str, ...]:
        masks = (ctypes.c_uint32 * 8)()
        count = self._lib.xkb_keymap_key_get_mods_for_level(
            self._keymap,
            keycode,
            0,
            level,
            masks,
            len(masks),
        )
        supported = sum(bit for _name, bit in modifier_masks)
        for mask in masks[:count]:
            if mask & ~supported == 0:
                return tuple(name for name, bit in modifier_masks if mask & bit)
        raise XkbError("XKB symbol requires unsupported modifiers.")

    def _keysym_name(self, keysym: int) -> str | None:
        buffer = ctypes.create_string_buffer(64)
        length = self._lib.xkb_keysym_get_name(keysym, buffer, len(buffer))
        if length <= 0 or length >= len(buffer):
            return None
        return buffer.value.decode("ascii")

    def _build_symbol_map(self) -> dict[str, tuple[int, XkbResolvedKey]]:
        symbols: dict[str, tuple[int, XkbResolvedKey]] = {}
        modifier_masks = self._modifier_masks()
        first = self._lib.xkb_keymap_min_keycode(self._keymap)
        last = min(
            self._lib.xkb_keymap_max_keycode(self._keymap),
            _XKB_KEYCODE_LIMIT - 1,
        )
        for keycode in range(first, last + 1):
            levels = self._lib.xkb_keymap_num_levels_for_key(
                self._keymap,
                keycode,
                0,
            )
            for level in range(levels):
                keysyms = ctypes.POINTER(ctypes.c_uint32)()
                count = self._lib.xkb_keymap_key_get_syms_by_level(
                    self._keymap,
                    keycode,
                    0,
                    level,
                    ctypes.byref(keysyms),
                )
                if count <= 0 or not keysyms:
                    continue
                try:
                    modifiers = self._level_modifiers(
                        keycode,
                        level,
                        modifier_masks,
                    )
                except XkbError:
                    continue
                resolved = XkbResolvedKey(
                    code=keycode - _XKB_KEYCODE_OFFSET,
                    modifiers=modifiers,
                )
                for index in range(count):
                    name = self._keysym_name(keysyms[index])
                    previous = symbols.get(name) if name else None
                    if name and (previous is None or level < previous[0]):
                        symbols[name] = (level, resolved)
        return symbols

    def _symbol_code(self, name: str, fallback: int) -> int:
        resolved = self.resolve(name)
        return resolved.code if resolved else fallback

    def resolve(self, keysym_name: str) -> XkbResolvedKey | None:
        match = self._symbols.get(keysym_name)
        return match[1] if match else None

    def resolve_character(self, character: str) -> XkbResolvedKey | None:
        if len(character) != 1:
            return None
        keysym = self._lib.xkb_utf32_to_keysym(ord(character))
        name = self._keysym_name(keysym)
        return self.resolve(name) if name else None

    def close(self) -> None:
        keymap = getattr(self, "_keymap", None)
        if keymap:
            self._lib.xkb_keymap_unref(keymap)
            self._keymap = None
        context = getattr(self, "_context", None)
        if context:
            self._lib.xkb_context_unref(context)
            self._context = None
