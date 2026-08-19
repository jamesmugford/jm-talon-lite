import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeContext:
    def __init__(self):
        self.matches = ""
        self.tags = []

    def action_class(self, _action_namespace):
        return lambda cls: cls


class FakeModule:
    def tag(self, _name, *, desc):
        pass

    def action_class(self, cls):
        return cls


class FakeApp:
    def register(self, _event, _callback):
        pass


class FakeSettings:
    _values = {
        "user.mouse_wheel_down_amount": 1.0,
        "user.mouse_wheel_horizontal_amount": 1.0,
    }

    def get(self, name):
        return self._values[name]


class FakeActions:
    def __init__(self):
        self.next_calls = []
        self.scroll_attempts = []
        self.scroll_emissions = []
        self.fail_scroll_call = None
        self.scroll_failure = None
        self.key_calls = []
        self.click_calls = []
        self.modifier_starts = []
        self.modifier_ends = []
        self.pointer_available = True
        self.native_button_down = []
        self.native_button_up = []
        self.user = types.SimpleNamespace(
            wayland_pointer_available=lambda: self.pointer_available,
            wayland_keyboard_available=lambda: True,
            wayland_keyboard_modifiers_begin=self._begin_modifiers,
            wayland_keyboard_modifiers_end=self.modifier_ends.append,
            wayland_pointer_button_down=self.native_button_down.append,
            wayland_pointer_button_up=self.native_button_up.append,
            wayland_pointer_scroll=self._scroll,
        )

    def next(self, *args):
        self.next_calls.append(args)

    def key(self, key_spec):
        self.key_calls.append(key_spec)

    def mouse_click(self, button):
        self.click_calls.append(button)

    def _begin_modifiers(self, modifiers):
        self.modifier_starts.append(modifiers)
        return 7

    def _scroll(self, vertical_steps=0, horizontal_steps=0):
        scroll = (vertical_steps, horizontal_steps)
        self.scroll_attempts.append(scroll)
        if len(self.scroll_attempts) == self.fail_scroll_call:
            raise self.scroll_failure
        self.scroll_emissions.append(scroll)


def load_mouse_forwarder_module():
    root = Path(__file__).resolve().parents[1]
    talon = types.ModuleType("talon")
    talon.Context = FakeContext
    talon.Module = FakeModule
    talon.actions = FakeActions()
    talon.app = FakeApp()
    talon.settings = FakeSettings()
    talon.ui = types.SimpleNamespace(screens=lambda: ())
    path = root / "plugins" / "mouse_forwarder.py"
    spec = importlib.util.spec_from_file_location(
        "plugins.mouse_forwarder_under_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    with (
        patch.dict(sys.modules, {"talon": talon}),
        patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=True),
    ):
        spec.loader.exec_module(module)
    return module, talon


class MouseForwarderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module, cls.talon = load_mouse_forwarder_module()

    def setUp(self):
        self.module._vertical_scroll_remainder = 0.0
        self.module._horizontal_scroll_remainder = 0.0
        self.module._fallback_held_buttons.clear()
        self.module._publish_fallback_buttons()
        self.talon.settings._values = {
            "user.mouse_wheel_down_amount": 1.0,
            "user.mouse_wheel_horizontal_amount": 1.0,
        }
        self.talon.actions.pointer_available = True
        self.talon.actions.next_calls.clear()
        self.talon.actions.scroll_attempts.clear()
        self.talon.actions.scroll_emissions.clear()
        self.talon.actions.fail_scroll_call = None
        self.talon.actions.scroll_failure = None
        self.talon.actions.key_calls.clear()
        self.talon.actions.click_calls.clear()
        self.talon.actions.modifier_starts.clear()
        self.talon.actions.modifier_ends.clear()
        self.talon.actions.native_button_down.clear()
        self.talon.actions.native_button_up.clear()

    def test_two_axis_scroll_is_one_native_transaction(self):
        self.module._vertical_scroll_remainder = 0.4
        self.module._horizontal_scroll_remainder = 0.3
        self.talon.actions.fail_scroll_call = 2
        self.talon.actions.scroll_failure = self.module.CapabilityUnavailable("lost")

        with patch.dict(
            os.environ,
            {"XDG_SESSION_TYPE": "wayland"},
            clear=True,
        ):
            self.module.MainActions.mouse_scroll(0.8, 0.9)

        self.assertEqual(self.talon.actions.scroll_attempts, [(1, 1)])
        self.assertEqual(self.talon.actions.scroll_emissions, [(1, 1)])
        self.assertAlmostEqual(self.module._vertical_scroll_remainder, 0.2)
        self.assertAlmostEqual(self.module._horizontal_scroll_remainder, 0.2)
        self.assertEqual(self.talon.actions.next_calls, [])

    def test_unavailable_scroll_preserves_accumulated_remainders(self):
        self.module._vertical_scroll_remainder = 0.4
        self.module._horizontal_scroll_remainder = 0.3
        self.talon.actions.fail_scroll_call = 1
        self.talon.actions.scroll_failure = self.module.CapabilityUnavailable("lost")

        with patch.dict(
            os.environ,
            {"XDG_SESSION_TYPE": "wayland"},
            clear=True,
        ):
            self.module.MainActions.mouse_scroll(0.8, 0.9)

        self.assertAlmostEqual(self.module._vertical_scroll_remainder, 0.4)
        self.assertAlmostEqual(self.module._horizontal_scroll_remainder, 0.3)
        self.assertEqual(self.talon.actions.scroll_attempts, [(1, 1)])
        self.assertEqual(self.talon.actions.scroll_emissions, [])
        self.assertEqual(self.talon.actions.next_calls, [(0.8, 0.9, False)])

    def test_modified_click_uses_native_temporary_modifier_token(self):
        with patch.dict(
            os.environ,
            {"XDG_SESSION_TYPE": "wayland"},
            clear=True,
        ):
            self.module._fallback_modified_click("ctrl", 1)

        self.assertEqual(self.talon.actions.modifier_starts, ["ctrl"])
        self.assertEqual(self.talon.actions.click_calls, [1])
        self.assertEqual(self.talon.actions.modifier_ends, [7])
        self.assertEqual(self.talon.actions.key_calls, [])

    def test_line_scroll_values_are_already_native_steps(self):
        self.talon.settings._values = {
            "user.mouse_wheel_down_amount": 120.0,
            "user.mouse_wheel_horizontal_amount": 80.0,
        }

        self.module.MainActions.mouse_scroll(1.0, -2.0, by_lines=True)

        self.assertEqual(self.talon.actions.scroll_emissions, [(1, -2)])
        self.assertEqual(self.module._vertical_scroll_remainder, 0.0)
        self.assertEqual(self.module._horizontal_scroll_remainder, 0.0)

    def test_fallback_drag_release_stays_with_fallback_after_capability_appears(self):
        self.talon.actions.pointer_available = False
        self.module.MainActions.mouse_drag(0)
        self.talon.actions.pointer_available = True
        self.module.MainActions.mouse_release(0)

        self.assertEqual(self.talon.actions.next_calls, [(0,), (0,)])
        self.assertEqual(self.talon.actions.native_button_down, [])
        self.assertEqual(self.talon.actions.native_button_up, [])
        self.assertEqual(self.module._fallback_held_buttons, set())


if __name__ == "__main__":
    unittest.main()
