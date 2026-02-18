"""Translate Talon key specs to dotool actions.

Format:
- Input key spec: space-separated chords like "ctrl-, ctrl-f".
- Chord: modifiers joined by "-" plus a key name (e.g., "super-1").
- Suffixes: ":down", ":up", or ":N" for repeats.
- Output: dotool action lines like "key ctrl+f".
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from .dotool_keymap import KEY_NAME_MAP, MODIFIER_ALIASES, SYMBOL_KEY_MAP

KeySpec = str
DotoolAction = str
DotoolActions = list[DotoolAction]
LogUnknownKey = Callable[[str], None]

_VALID_KEY_RE = re.compile(r"^[a-z0-9]$|^f\d+$|^kp\d+$")
_KNOWN_KEYS = set(KEY_NAME_MAP.values())
_UNKNOWN_KEYS_SEEN: set[str] = set()


@dataclass(frozen=True)
class ChordSpec:
    """Parsed chord fields used to emit dotool actions."""

    mods: tuple[str, ...]
    key: str
    action: str
    repeat: int


DEFAULT_DEBUG_SAMPLES = [
    "ctrl-, ctrl-f",
    "super-1",
    "esc:2",
    "ctrl:down",
]


def debug_translate(samples: list[KeySpec] | None = None) -> list[str]:
    """Return human-readable translations for sample key specs.

    Args:
        samples: Optional list of Talon key specs.

    Returns:
        List of lines like "<spec> -> [actions]".
    """
    if samples is None:
        samples = DEFAULT_DEBUG_SAMPLES
    return [f"{spec} -> {talon_key_to_dotool_actions(spec)}" for spec in samples]


def talon_key_to_dotool_actions(
    key_spec: KeySpec, log_unknown: LogUnknownKey | None = None
) -> DotoolActions:
    """Convert a Talon key spec into dotool actions.

    Args:
        key_spec: Talon key spec with space-separated chords.
        log_unknown: Optional callback to log unknown key names.

    Returns:
        List of dotool action lines.
    """
    return [
        action
        for chord in key_spec.split()
        for action in _dotool_actions_for_chord(chord, log_unknown)
    ]


def _dotool_actions_for_chord(
    chord: str, log_unknown: LogUnknownKey | None
) -> DotoolActions:
    """Convert a single Talon chord to dotool actions.

    Args:
        chord: Talon chord string, e.g. "ctrl-a" or "esc:2".
        log_unknown: Optional callback to log unknown key names.

    Returns:
        List of dotool action lines.
    """
    spec = _parse_chord(chord, log_unknown)
    if spec is None:
        return []
    if not spec.key:
        return _mods_only_actions(spec.mods, spec.action)

    chord_str = _build_chord(spec.mods, spec.key)
    if spec.action != "key":
        return [f"{spec.action} {chord_str}"]
    if spec.repeat <= 1:
        return [f"key {chord_str}"]
    return [f"key {chord_str}" for _ in range(spec.repeat)]


def _parse_chord(
    chord: str, log_unknown: LogUnknownKey | None
) -> ChordSpec | None:
    """Parse a chord into a ChordSpec for dotool emission.

    Args:
        chord: Talon chord string.
        log_unknown: Optional callback to log unknown key names.

    Returns:
        Parsed ChordSpec or None for empty input.
    """
    chord = chord.strip()
    if not chord:
        return None

    base, action, repeat = _parse_suffix(chord)
    mods, key = _split_modifiers(base)
    mods, key = _normalize_alpha_key(key, mods)
    key = _normalize_key_name(key)
    _maybe_log_unknown_key(key, log_unknown)
    return ChordSpec(mods=mods, key=key, action=action, repeat=repeat)


def _parse_suffix(chord: str) -> tuple[str, str, int]:
    """Parse :down/:up or :N suffixes for a chord.

    Args:
        chord: Talon chord string, possibly with a suffix.

    Returns:
        Tuple of (base_chord, action, repeat).
    """
    if ":" not in chord:
        return chord, "key", 1
    base, suffix = chord.rsplit(":", 1)
    if suffix.isdigit():
        return base, "key", max(1, int(suffix))
    if suffix == "down":
        return base, "keydown", 1
    if suffix == "up":
        return base, "keyup", 1
    return chord, "key", 1


def _split_modifiers(chord: str) -> tuple[tuple[str, ...], str]:
    """Split a chord into modifiers and the base key.

    Args:
        chord: Talon chord string like "ctrl-shift-a".

    Returns:
        Tuple of (modifiers, key) where modifiers is a tuple.
    """
    parts = chord.split("-")
    mods: list[str] = []
    key_parts: list[str] = []
    for part in parts:
        if not key_parts and part in MODIFIER_ALIASES:
            mods.append(MODIFIER_ALIASES[part])
        else:
            key_parts.append(part)
    return tuple(mods), "-".join(key_parts)


def _normalize_alpha_key(key: str, mods: tuple[str, ...]) -> tuple[tuple[str, ...], str]:
    """Normalize single-letter uppercase keys without mutating inputs.

    Args:
        key: Single key string.
        mods: Modifier tuple.

    Returns:
        Tuple of (mods, key) with shift added if needed.
    """
    if key and len(key) == 1 and key.isalpha() and key.isupper():
        if "shift" in mods:
            return mods, key.lower()
        return mods + ("shift",), key.lower()
    return mods, key


def _normalize_key_name(key: str) -> str:
    """Normalize a Talon key name to a dotool-compatible name.

    Args:
        key: Talon key name or symbol.

    Returns:
        Dotool-compatible key name, possibly with x:/k: prefix.
    """
    if not key:
        return key
    if key in SYMBOL_KEY_MAP:
        return SYMBOL_KEY_MAP[key]
    if key.startswith("keypad_"):
        return "kp" + key[len("keypad_") :]
    if not key.startswith(("x:", "k:")):
        key = key.lower()
    return KEY_NAME_MAP.get(key, key)


def _mods_only_actions(mods: tuple[str, ...], action: str) -> DotoolActions:
    """Emit dotool actions for modifier-only chords.

    Args:
        mods: Modifier tuple.
        action: Action name (key, keydown, keyup).

    Returns:
        Dotool actions to press/release modifiers.
    """
    if not mods:
        return []
    if action == "keydown":
        return [f"keydown {mod}" for mod in mods]
    if action == "keyup":
        return [f"keyup {mod}" for mod in reversed(mods)]
    actions = [f"keydown {mod}" for mod in mods]
    actions.extend(f"keyup {mod}" for mod in reversed(mods))
    return actions


def _build_chord(mods: tuple[str, ...], key: str) -> str:
    """Build a dotool chord string from modifiers and a key.

    Args:
        mods: Modifier tuple.
        key: Normalized key name.

    Returns:
        Dotool chord string like "ctrl+shift+a".
    """
    parts = list(mods)
    if key:
        parts.append(key)
    return "+".join(parts)


def _maybe_log_unknown_key(key: str, log_unknown: LogUnknownKey | None) -> None:
    if not log_unknown or not key:
        return
    if _is_probably_valid_key(key):
        return
    if key in _UNKNOWN_KEYS_SEEN:
        return
    _UNKNOWN_KEYS_SEEN.add(key)
    log_unknown(key)


def _is_probably_valid_key(key: str) -> bool:
    if key.startswith(("x:", "k:")):
        return True
    if key.startswith("kp"):
        return True
    if _VALID_KEY_RE.match(key):
        return True
    return key in _KNOWN_KEYS
