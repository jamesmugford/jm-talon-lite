"""Translate Talon key parser output to Linux keyboard events."""

from dataclasses import dataclass
from typing import Protocol

from .events import Device, Event, Frame, Frames
from .xkb import XkbResolvedKey


EV_KEY = 0x01


@dataclass(frozen=True)
class KeyCommand:
    name: str
    modifiers: tuple[str, ...] = ()
    behavior: str | None = None


@dataclass(frozen=True)
class ResolvedKey:
    code: int
    modifiers: tuple[int, ...] = ()


class XkbResolver(Protocol):
    modifier_codes: dict[str, int]

    def resolve(self, keysym_name: str) -> XkbResolvedKey | None: ...

    def resolve_character(self, character: str) -> XkbResolvedKey | None: ...


_MODIFIERS = {
    "cmd": "super",
    "win": "super",
    "super": "super",
    "ctrl": "ctrl",
    "alt": "alt",
    "shift": "shift",
}

_SYMBOLS = {
    "-": "minus",
    "=": "equal",
    ",": "comma",
    ".": "period",
    "/": "slash",
    ";": "semicolon",
    "'": "apostrophe",
    "[": "bracketleft",
    "]": "bracketright",
    "\\": "backslash",
    "`": "grave",
    "!": "exclam",
    "@": "at",
    "#": "numbersign",
    "$": "dollar",
    "%": "percent",
    "^": "asciicircum",
    "&": "ampersand",
    "*": "asterisk",
    "(": "parenleft",
    ")": "parenright",
    "_": "underscore",
    "+": "plus",
    "{": "braceleft",
    "}": "braceright",
    "|": "bar",
    ":": "colon",
    '"': "quotedbl",
    "<": "less",
    ">": "greater",
    "?": "question",
    "~": "asciitilde",
}

_NAMED_SYMBOLS = {
    "minus": "minus",
    "equal": "equal",
    "comma": "comma",
    "period": "period",
    "dot": "period",
    "slash": "slash",
    "semicolon": "semicolon",
    "apostrophe": "apostrophe",
    "leftbrace": "bracketleft",
    "rightbrace": "bracketright",
    "backslash": "backslash",
    "grave": "grave",
    "plus": "plus",
}

_KEY_CODES = {
    "esc": 1,
    "escape": 1,
    "backspace": 14,
    "bksp": 14,
    "tab": 15,
    "enter": 28,
    "return": 28,
    "space": 57,
    "lctrl": 29,
    "leftctrl": 29,
    "lshift": 42,
    "leftshift": 42,
    "lalt": 56,
    "leftalt": 56,
    "lsuper": 125,
    "lwin": 125,
    "leftmeta": 125,
    "capslock": 58,
    "numlock": 69,
    "scrolllock": 70,
    "rctrl": 97,
    "rightctrl": 97,
    "rshift": 54,
    "rightshift": 54,
    "ralt": 100,
    "rightalt": 100,
    "altgr": 100,
    "rsuper": 126,
    "rwin": 126,
    "rightmeta": 126,
    "home": 102,
    "up": 103,
    "pageup": 104,
    "pgup": 104,
    "left": 105,
    "right": 106,
    "end": 107,
    "down": 108,
    "pagedown": 109,
    "pgdown": 109,
    "insert": 110,
    "delete": 111,
    "del": 111,
    "mute": 113,
    "voldown": 114,
    "volumedown": 114,
    "volup": 115,
    "volumeup": 115,
    "power": 116,
    "pause": 119,
    "compose": 127,
    "stop": 128,
    "menu": 139,
    "sleep": 142,
    "wakeup": 143,
    "next": 163,
    "nextsong": 163,
    "play_pause": 164,
    "playpause": 164,
    "prev": 165,
    "previoussong": 165,
    "record": 167,
    "rewind": 168,
    "play": 207,
    "fast_forward": 208,
    "fastforward": 208,
    "printscreen": 99,
    "printscr": 99,
    "brightness_down": 224,
    "brightnessdown": 224,
    "brightness_up": 225,
    "brightnessup": 225,
    "micmute": 248,
    "keypad_7": 71,
    "keypad_8": 72,
    "keypad_9": 73,
    "keypad_minus": 74,
    "keypad_4": 75,
    "keypad_5": 76,
    "keypad_6": 77,
    "keypad_plus": 78,
    "keypad_1": 79,
    "keypad_2": 80,
    "keypad_3": 81,
    "keypad_0": 82,
    "keypad_decimal": 83,
    "keypad_enter": 96,
    "keypad_divide": 98,
    "keypad_equals": 117,
    "keypad_multiply": 55,
}


def _function_key_code(name: str) -> int | None:
    if not name.startswith("f") or not name[1:].isdigit():
        return None
    number = int(name[1:])
    if 1 <= number <= 10:
        return 58 + number
    if number == 11:
        return 87
    if number == 12:
        return 88
    if 13 <= number <= 24:
        return 170 + number
    return None


class KeyboardResolver:
    def __init__(self, xkb: XkbResolver):
        self._xkb = xkb

    def modifier(self, name: str) -> int | None:
        canonical = _MODIFIERS.get(name.lower())
        return self._xkb.modifier_codes.get(canonical) if canonical else None

    def resolve(self, name: str) -> ResolvedKey | None:
        lowered = name.lower()
        modifier = self.modifier(lowered)
        if modifier is not None:
            return ResolvedKey(modifier)

        code = _KEY_CODES.get(lowered)
        if code is None and lowered.startswith("kp") and lowered[2:].isdigit():
            code = _KEY_CODES.get(f"keypad_{lowered[2:]}")
        if code is None:
            code = _function_key_code(lowered)
        if code is not None:
            return ResolvedKey(code)

        keysym = _SYMBOLS.get(name) or _NAMED_SYMBOLS.get(lowered)
        resolved = None
        if keysym is not None:
            resolved = self._xkb.resolve(keysym)
        elif len(name) == 1:
            resolved = self._xkb.resolve_character(name)
        if resolved is None:
            return None
        modifiers = tuple(
            self._xkb.modifier_codes[item] for item in resolved.modifiers
        )
        return ResolvedKey(resolved.code, modifiers)


def commands_from_talon(parsed_keys) -> list[KeyCommand]:
    return [
        KeyCommand(key.name, tuple(key.mods), key.behavior)
        for key in parsed_keys
    ]


def _frame(code: int, value: int, temporary: bool = False) -> Frame:
    return Frame(Device.KEYBOARD, (Event(EV_KEY, code, value, temporary),))


def _unique(items: list[int]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(items))


def frames_for_commands(
    commands: list[KeyCommand],
    resolver: KeyboardResolver,
) -> Frames | None:
    """Resolve a complete Talon key sequence or reject it atomically."""
    frames: list[Frame] = []
    for command in commands:
        if command.behavior not in (None, "down", "up") and not (
            command.behavior and command.behavior.isdigit()
        ):
            return None

        key = resolver.resolve(command.name)
        if key is None:
            return None
        explicit_modifiers = [resolver.modifier(name) for name in command.modifiers]
        if any(code is None for code in explicit_modifiers):
            return None
        modifiers = _unique([
            *(code for code in explicit_modifiers if code is not None),
            *key.modifiers,
        ])
        modifiers = tuple(code for code in modifiers if code != key.code)
        chord = (*modifiers, key.code)

        if command.behavior == "down":
            frames.extend(_frame(code, 1) for code in chord)
            continue
        if command.behavior == "up":
            frames.extend(_frame(code, 0) for code in reversed(chord))
            continue

        repeats = int(command.behavior) if command.behavior else 1
        repeats = max(1, repeats)
        for _ in range(repeats):
            frames.extend(_frame(code, 1, temporary=True) for code in chord)
            frames.extend(
                _frame(code, 0, temporary=True) for code in reversed(chord)
            )
    return tuple(frames)
