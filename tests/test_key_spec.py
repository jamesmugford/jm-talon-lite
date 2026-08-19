import sys
import unittest
from pathlib import Path

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
sys.path.insert(0, str(PLUGINS))
try:
    from wayland_backend.key_spec import (
        KeyAction,
        KeyEvent,
        KeyStroke,
        ResolvedStroke,
        modifier_chord,
        parse_key_spec,
        plan_key_events,
    )
finally:
    sys.path.remove(str(PLUGINS))


class KeySpecTests(unittest.TestCase):
    def test_parses_sequences_chords_repeats_and_literal_punctuation(self):
        self.assertEqual(
            parse_key_spec("ctrl-, - : esc:2 shift:down shift:up"),
            (
                KeyStroke(("ctrl",), ",", KeyAction.TAP, 1),
                KeyStroke((), "-", KeyAction.TAP, 1),
                KeyStroke((), ":", KeyAction.TAP, 1),
                KeyStroke((), "esc", KeyAction.TAP, 2),
                KeyStroke(("shift",), None, KeyAction.DOWN, 1),
                KeyStroke(("shift",), None, KeyAction.UP, 1),
            ),
        )

    def test_modifier_chord_returns_ordered_down_and_up_strokes(self):
        down, up = modifier_chord("ctrl-shift")
        self.assertEqual(
            down,
            (KeyStroke(("ctrl", "shift"), None, KeyAction.DOWN, 1),),
        )
        self.assertEqual(
            up,
            (KeyStroke(("ctrl", "shift"), None, KeyAction.UP, 1),),
        )
        with self.assertRaises(ValueError):
            modifier_chord("ctrl-a")

    def test_plans_tap_without_mutating_input_state(self):
        held = frozenset({56})
        plan = plan_key_events(
            (ResolvedStroke((29, 42), 30, KeyAction.TAP, 2),),
            held,
        )
        self.assertEqual(
            plan.events,
            (
                KeyEvent(29, True),
                KeyEvent(42, True),
                KeyEvent(30, True),
                KeyEvent(30, False),
                KeyEvent(30, True),
                KeyEvent(30, False),
                KeyEvent(42, False),
                KeyEvent(29, False),
            ),
        )
        self.assertEqual(plan.held_after, held)

    def test_state_setting_strokes_are_idempotent(self):
        plan = plan_key_events(
            (
                ResolvedStroke((29,), None, KeyAction.DOWN, 1),
                ResolvedStroke((29,), None, KeyAction.DOWN, 1),
                ResolvedStroke((29,), None, KeyAction.UP, 1),
                ResolvedStroke((29,), None, KeyAction.UP, 1),
            ),
            frozenset(),
        )
        self.assertEqual(plan.events, (KeyEvent(29, True), KeyEvent(29, False)))
        self.assertFalse(plan.held_after)

    def test_rejects_tapping_an_already_held_key_without_a_plan(self):
        with self.assertRaisesRegex(RuntimeError, "while it is held"):
            plan_key_events(
                (ResolvedStroke((), 30, KeyAction.TAP, 1),),
                frozenset({30}),
            )

    def test_invalid_specs_are_rejected_and_empty_is_noop(self):
        self.assertEqual(parse_key_spec("  "), ())
        with self.assertRaises(TypeError):
            parse_key_spec(1)
        for value in (":down", "a:0"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_key_spec(value)


if __name__ == "__main__":
    unittest.main()
