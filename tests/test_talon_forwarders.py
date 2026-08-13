import sys
import types
import unittest
from pathlib import Path


class _FakeContext:
    def __init__(self):
        self.matches = ""

    def action_class(self, *_args):
        return lambda action_class: action_class


class _FakeModule:
    def setting(self, *_args, **_kwargs):
        pass

    def action_class(self, action_class=None):
        if isinstance(action_class, type):
            return action_class
        return lambda value: value


class _FakeInput:
    def __init__(self):
        self.calls = []
        self.pressed = set()

    def key(self, parsed):
        self.calls.append(("key", parsed))

    def click(self, button):
        self.calls.append(("click", button))

    def button(self, button, pressed):
        self.calls.append(("button", button, pressed))
        if pressed:
            self.pressed.add(button)
        else:
            self.pressed.discard(button)

    def button_pressed(self, button):
        return button in self.pressed

    def move(self, x, y):
        self.calls.append(("move", x, y))

    def scroll(self, vertical=0, horizontal=0):
        self.calls.append(("scroll", vertical, horizontal))

    def modified_click(self, down, up, button):
        self.calls.append(("modified_click", down, up, button))

    def release_buttons(self):
        released = bool(self.pressed)
        self.pressed.clear()
        return released


class TalonForwarderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))

        cls.notifications = []
        fake_talon = types.ModuleType("talon")
        fake_talon.Context = _FakeContext
        fake_talon.Module = _FakeModule
        fake_talon.app = types.SimpleNamespace(
            notify=cls.notifications.append,
            register=lambda *_args: None,
        )
        fake_talon.settings = types.SimpleNamespace(get=lambda _name: 120)
        fake_talon.actions = types.SimpleNamespace()
        fake_talon.ui = types.SimpleNamespace(
            screens=lambda: [
                types.SimpleNamespace(
                    rect=types.SimpleNamespace(x=0, y=0, width=200, height=100)
                )
            ],
            register=lambda *_args: None,
        )
        fake_talon.tracking_system = types.SimpleNamespace(
            register=lambda *_args: None,
            unregister=lambda *_args: None,
        )
        fake_talon_lib = types.ModuleType("talon.lib")
        fake_talon_keys = types.ModuleType("talon.lib.keys")
        fake_talon_keys.parse_keys = lambda spec: [spec]
        fake_talon_plugins = types.ModuleType("talon.plugins")
        fake_eye_mouse = types.ModuleType("talon.plugins.eye_mouse")
        fake_eye_mouse.mouse = types.SimpleNamespace(xy_hist=[])
        fake_talon.plugins = fake_talon_plugins
        fake_talon_lib.keys = fake_talon_keys
        fake_talon_plugins.eye_mouse = fake_eye_mouse

        fake_modules = {
            "talon": fake_talon,
            "talon.lib": fake_talon_lib,
            "talon.lib.keys": fake_talon_keys,
            "talon.plugins": fake_talon_plugins,
            "talon.plugins.eye_mouse": fake_eye_mouse,
        }
        previous = {name: sys.modules.get(name) for name in fake_modules}
        sys.modules.update(fake_modules)
        try:
            from plugins import hiss_mouse, native_mouse
            from plugins.key_forwarder import forwarder
            from plugins.tracking_forwarder import control1_pointer_forwarder

            cls.hiss = hiss_mouse
            cls.keyboard = forwarder
            cls.mouse = native_mouse
            cls.pointer = control1_pointer_forwarder
            cls.eye_mouse = fake_eye_mouse
        finally:
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    def setUp(self):
        self.input = _FakeInput()
        self.keyboard.get_input = lambda: self.input
        self.mouse.get_input = lambda: self.input
        self.pointer.get_input = lambda: self.input
        self.mouse.settings = types.SimpleNamespace(get=lambda _name: 120)
        self.mouse._vertical_scroll_remainder = 0
        self.mouse._horizontal_scroll_remainder = 0
        self.mouse._last_error = None

    def test_keyboard_parses_and_sends_directly(self):
        self.keyboard.MainActions.key("ctrl-a")
        self.assertEqual(self.input.calls, [("key", ["ctrl-a"])])

    def test_mouse_move_is_normalized_once(self):
        self.mouse.MainActions.mouse_move(50, 75)
        self.assertEqual(self.input.calls, [("move", 0.25, 0.75)])

    def test_click_does_not_release_an_existing_drag(self):
        self.input.pressed.add(0)
        self.mouse.MainActions.mouse_click(0)
        self.assertEqual(self.input.calls, [])
        self.assertEqual(self.input.pressed, {0})

    def test_scroll_accumulates_fractional_steps(self):
        self.mouse.UserActions.native_scroll(0.2)
        self.assertEqual(self.input.calls, [])
        for _ in range(4):
            self.mouse.UserActions.native_scroll(0.2)
        self.assertEqual(self.input.calls[-1], ("scroll", -1, 0))

    def test_line_scroll_uses_values_as_steps(self):
        self.mouse.MainActions.mouse_scroll(2, -1, by_lines=True)
        self.assertEqual(self.input.calls, [("scroll", -2, -1)])

    def test_hiss_pop_uses_the_main_mouse_action(self):
        clicks = []
        self.hiss._hiss_mouse_enabled = True
        self.hiss.actions = types.SimpleNamespace(
            mouse_click=clicks.append,
            tracking=types.SimpleNamespace(
                control1_enabled=lambda: False,
                control1_toggle=lambda _state: None,
            ),
        )
        self.hiss.UserActions.noise_trigger_pop()
        self.assertEqual(clicks, [0])

    def test_gaze_emits_one_absolute_move_without_a_nudge(self):
        self.pointer._desktop_bounds = (0, 0, 200, 100)
        self.pointer.actions = types.SimpleNamespace(
            tracking=types.SimpleNamespace(control1_enabled=lambda: True)
        )
        self.eye_mouse.mouse.xy_hist = [types.SimpleNamespace(x=50, y=75)]
        self.pointer._on_gaze()
        self.assertEqual(self.input.calls, [("move", 0.25, 0.75)])


if __name__ == "__main__":
    unittest.main()
