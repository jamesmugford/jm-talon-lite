import importlib
import sys
import unittest
from pathlib import Path


class _EventCode:
    def __init__(self, event_type, code):
        self.event_type = event_type
        self.code = code


class _InputEvent:
    def __init__(self, code, value):
        self.code = code
        self.value = value


class _OutputDevice:
    def __init__(self, module):
        self.module = module
        self._uinput = self
        self._uinput_device = object()
        self.closed = False

    def _uinput_write_event(self, _device, event_type, code, value):
        self.module.writes.append((event_type, code, value))
        if self.module.write_results:
            return self.module.write_results.pop(0)
        return 0

    def __exit__(self, *_args):
        self.closed = True


class _SourceDevice:
    def __init__(self, module):
        self.module = module
        self.name = ""
        self.id = {}
        self.enabled = []
        module.sources.append(self)

    def enable(self, code, data=None):
        self.enabled.append((code.event_type, code.code, data))

    def create_uinput_device(self):
        if self.module.create_error_at == len(self.module.outputs):
            raise OSError("create failed")
        output = _OutputDevice(self.module)
        self.module.outputs.append(output)
        return output


class _FakeLibevdev:
    class InputAbsInfo:
        def __init__(self, **values):
            self.values = values

    InputEvent = _InputEvent

    def __init__(self):
        self.sources = []
        self.outputs = []
        self.writes = []
        self.write_results = []
        self.create_error_at = -1

    def Device(self):
        return _SourceDevice(self)

    @staticmethod
    def evbit(event_type, code):
        if event_type == 1 and code == 0:
            return None
        return _EventCode(event_type, code)


class InputBackendRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins = Path(__file__).resolve().parents[1] / "plugins"
        sys.path.insert(0, str(plugins))
        from input_backend import backend, events, keyboard, pointer

        cls.backend_module = backend
        cls.events = events
        cls.keyboard = keyboard
        cls.pointer = pointer

    @classmethod
    def tearDownClass(cls):
        plugins = str(Path(__file__).resolve().parents[1] / "plugins")
        if plugins in sys.path:
            sys.path.remove(plugins)

    def _backend(self, module=None):
        module = module or _FakeLibevdev()
        return self.backend_module.UInputBackend(lambda: module), module

    def test_creates_three_project_named_virtual_devices(self):
        backend, module = self._backend()
        backend.initialize()
        self.assertEqual(
            [source.name for source in module.sources],
            [
                "jm-talon-lite keyboard",
                "jm-talon-lite pointer",
                "jm-talon-lite absolute pointer",
            ],
        )
        self.assertEqual(
            [source.id for source in module.sources],
            [
                {"bustype": 6, "vendor": 0, "product": 1, "version": 1},
                {"bustype": 6, "vendor": 0, "product": 2, "version": 1},
                {"bustype": 6, "vendor": 0, "product": 3, "version": 1},
            ],
        )
        backend.close()
        self.assertTrue(all(output.closed for output in module.outputs))

    def test_each_frame_has_one_syn_report(self):
        backend, module = self._backend()
        backend.send(self.pointer.click_frames(0))
        self.assertEqual(
            module.writes,
            [
                (1, 0x110, 1),
                (0, 0, 0),
                (1, 0x110, 0),
                (0, 0, 0),
            ],
        )

    def test_tap_does_not_release_a_held_key(self):
        backend, module = self._backend()
        keyboard = self.events.Device.KEYBOARD
        backend.send((self.events.Frame(keyboard, (self.events.Event(1, 29, 1),)),))
        module.writes.clear()
        backend.send((
            self.events.Frame(keyboard, (self.events.Event(1, 29, 1, True),)),
            self.events.Frame(keyboard, (self.events.Event(1, 30, 1, True),)),
            self.events.Frame(keyboard, (self.events.Event(1, 30, 0, True),)),
            self.events.Frame(keyboard, (self.events.Event(1, 29, 0, True),)),
        ))
        self.assertNotIn((1, 29, 0), module.writes)
        self.assertTrue(backend.pressed(keyboard, 29))

    def test_hold_then_tap_then_release_in_one_batch(self):
        backend, module = self._backend()
        keyboard = self.events.Device.KEYBOARD
        backend.send((
            self.events.Frame(keyboard, (self.events.Event(1, 29, 1),)),
            self.events.Frame(keyboard, (self.events.Event(1, 29, 1, True),)),
            self.events.Frame(keyboard, (self.events.Event(1, 30, 1, True),)),
            self.events.Frame(keyboard, (self.events.Event(1, 30, 0, True),)),
            self.events.Frame(keyboard, (self.events.Event(1, 29, 0, True),)),
            self.events.Frame(keyboard, (self.events.Event(1, 29, 0),)),
        ))
        ctrl_events = [
            event
            for event in module.writes
            if event[:2] == (1, 29)
        ]
        self.assertEqual(ctrl_events, [(1, 29, 1), (1, 29, 0)])
        self.assertFalse(backend.pressed(keyboard, 29))

    def test_failure_closes_devices_and_can_retry(self):
        backend, module = self._backend()
        backend.initialize()
        module.write_results = [-5]
        with self.assertRaisesRegex(self.backend_module.InputError, "reset"):
            backend.send(self.pointer.click_frames(0))
        self.assertFalse(backend.ready)
        self.assertTrue(all(output.closed for output in module.outputs))
        backend.send(self.pointer.click_frames(0))
        self.assertTrue(backend.ready)

    def test_reload_closes_the_previous_singleton(self):
        previous = self.backend_module.get_backend()
        closed = []
        previous.close = lambda: closed.append(True)
        reloaded = importlib.reload(self.backend_module)
        self.assertEqual(closed, [True])
        self.assertIsNot(reloaded.get_backend(), previous)
        self.backend_module = reloaded


if __name__ == "__main__":
    unittest.main()
