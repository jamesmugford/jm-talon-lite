import sys
import types
import unittest
from pathlib import Path


class _FakeXkb:
    def __init__(self, resolved_type):
        self.modifier_codes = {
            "super": 125,
            "altgr": 100,
            "ctrl": 29,
            "alt": 56,
            "shift": 42,
        }
        self.symbols = {
            "a": resolved_type(30),
            "A": resolved_type(30, ("shift",)),
            "minus": resolved_type(12),
            "exclam": resolved_type(2, ("shift",)),
        }

    def resolve(self, name):
        return self.symbols.get(name)

    def resolve_character(self, character):
        return self.symbols.get(character)


class InputBackendPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins = Path(__file__).resolve().parents[1] / "plugins"
        sys.path.insert(0, str(plugins))
        from input_backend import events, keyboard, pointer, xkb

        cls.events = events
        cls.keyboard = keyboard
        cls.pointer = pointer
        cls.resolver = keyboard.KeyboardResolver(_FakeXkb(xkb.XkbResolvedKey))

    @classmethod
    def tearDownClass(cls):
        plugins = str(Path(__file__).resolve().parents[1] / "plugins")
        if plugins in sys.path:
            sys.path.remove(plugins)

    def _frames(self, *commands):
        return self.keyboard.frames_for_commands(list(commands), self.resolver)

    def test_copies_talon_parser_output(self):
        parsed = [types.SimpleNamespace(name="a", mods=("ctrl",), behavior="down")]
        self.assertEqual(
            self.keyboard.commands_from_talon(parsed),
            [self.keyboard.KeyCommand("a", ("ctrl",), "down")],
        )

    def test_tap_presses_modifiers_and_releases_in_reverse(self):
        frames = self._frames(self.keyboard.KeyCommand("a", ("ctrl",)))
        self.assertEqual(
            [(frame.events[0].code, frame.events[0].value) for frame in frames],
            [(29, 1), (30, 1), (30, 0), (29, 0)],
        )
        self.assertTrue(all(frame.events[0].temporary for frame in frames))

    def test_explicit_down_and_up_are_persistent(self):
        frames = self._frames(
            self.keyboard.KeyCommand("shift", ("ctrl",), "down"),
            self.keyboard.KeyCommand("shift", ("ctrl",), "up"),
        )
        self.assertEqual(
            [(frame.events[0].code, frame.events[0].value) for frame in frames],
            [(29, 1), (42, 1), (42, 0), (29, 0)],
        )
        self.assertFalse(any(frame.events[0].temporary for frame in frames))

    def test_layout_symbols_include_required_modifiers(self):
        frames = self._frames(self.keyboard.KeyCommand("!"))
        self.assertEqual(
            [(frame.events[0].code, frame.events[0].value) for frame in frames],
            [(42, 1), (2, 1), (2, 0), (42, 0)],
        )

    def test_named_keys_and_repeats_map_directly(self):
        frames = self._frames(self.keyboard.KeyCommand("printscreen", behavior="2"))
        self.assertEqual(
            [(frame.events[0].code, frame.events[0].value) for frame in frames],
            [(99, 1), (99, 0), (99, 1), (99, 0)],
        )

    def test_unknown_key_or_behavior_rejects_whole_sequence(self):
        self.assertIsNone(self._frames(self.keyboard.KeyCommand("not_a_key")))
        self.assertIsNone(
            self._frames(self.keyboard.KeyCommand("a", behavior="invalid"))
        )

    def test_pointer_frames_are_generic_and_compositor_neutral(self):
        move = self.pointer.move_frames(0.5, 1.5)
        self.assertEqual(len(move), 1)
        self.assertIs(move[0].device, self.events.Device.ABSOLUTE_POINTER)
        self.assertEqual(
            [(event.code, event.value) for event in move[0].events],
            [(0, 32768), (1, 65535)],
        )
        self.assertEqual(len(self.pointer.click_frames(0)), 2)
        self.assertEqual(len(self.pointer.scroll_frames(1, -1)[0].events), 2)


if __name__ == "__main__":
    unittest.main()
