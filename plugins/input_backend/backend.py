"""Thread-safe owner of jm-talon-lite's virtual Linux input devices."""

import atexit
import os
import threading

from .dependency import load_libevdev
from .events import Device, Frame, Frames
from .pointer import ABSOLUTE_MAX


BUS_VIRTUAL = 0x06
SYN_REPORT = (0x00, 0x00, 0)

DEVICE_NAMES = {
    Device.KEYBOARD: "jm-talon-lite keyboard",
    Device.POINTER: "jm-talon-lite pointer",
    Device.ABSOLUTE_POINTER: "jm-talon-lite absolute pointer",
}


class InputError(RuntimeError):
    pass


class UInputBackend:
    """Create virtual devices and serialize complete input frames."""

    def __init__(self, loader=load_libevdev) -> None:
        self._loader = loader
        self._libevdev = None
        self._devices: dict[Device, object] = {}
        self._pressed: dict[Device, set[int]] = {
            device: set() for device in Device
        }
        self._lock = threading.RLock()

    @property
    def ready(self) -> bool:
        return len(self._devices) == len(Device)

    def _event_code(self, event_type: int, code: int):
        event_code = self._libevdev.evbit(event_type, code)
        if event_code is None:
            raise InputError(
                f"Unknown Linux input event type={event_type} code={code}."
            )
        return event_code

    def _new_device(self, device: Device):
        source = self._libevdev.Device()
        source.name = DEVICE_NAMES[device]
        source.id = {
            "bustype": BUS_VIRTUAL,
            "vendor": 0,
            "product": list(Device).index(device) + 1,
            "version": 1,
        }
        return source

    def _create_keyboard(self):
        source = self._new_device(Device.KEYBOARD)
        for code in range(1, 0x100):
            event_code = self._libevdev.evbit(0x01, code)
            if event_code is not None:
                source.enable(event_code)
        return source.create_uinput_device()

    def _create_pointer(self):
        source = self._new_device(Device.POINTER)
        for code in (0x110, 0x111, 0x112, 0x113, 0x114):
            source.enable(self._event_code(0x01, code))
        for code in (0, 1, 6, 8):
            source.enable(self._event_code(0x02, code))
        return source.create_uinput_device()

    def _create_absolute_pointer(self):
        source = self._new_device(Device.ABSOLUTE_POINTER)
        source.enable(self._event_code(0x01, 0x110))
        axis = self._libevdev.InputAbsInfo(minimum=0, maximum=ABSOLUTE_MAX)
        source.enable(self._event_code(0x03, 0), axis)
        source.enable(self._event_code(0x03, 1), axis)
        return source.create_uinput_device()

    @staticmethod
    def _destroy(device) -> None:
        uinput = getattr(device, "_uinput", None)
        if uinput is not None:
            uinput.__exit__(None, None, None)
            device._uinput = None

    @staticmethod
    def _checked_write(device, event_type: int, code: int, value: int) -> None:
        uinput = getattr(device, "_uinput", None)
        if uinput is None:
            raise OSError("uinput device is closed")
        result = uinput._uinput_write_event(
            uinput._uinput_device,
            event_type,
            code,
            value,
        )
        if result:
            error = -result if result < 0 else result
            raise OSError(error, os.strerror(error))

    def _close_unlocked(self) -> None:
        devices, self._devices = self._devices, {}
        for pressed in self._pressed.values():
            pressed.clear()
        for device in reversed(tuple(devices.values())):
            try:
                self._destroy(device)
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def _initialize_unlocked(self) -> None:
        if self.ready:
            return
        self._close_unlocked()
        created = {}
        try:
            self._libevdev = self._loader()
            created[Device.KEYBOARD] = self._create_keyboard()
            created[Device.POINTER] = self._create_pointer()
            created[Device.ABSOLUTE_POINTER] = self._create_absolute_pointer()
        except Exception as exc:
            for device in reversed(tuple(created.values())):
                try:
                    self._destroy(device)
                except Exception:
                    pass
            raise InputError(
                "Native input is unavailable; run setup/doctor."
            ) from exc
        self._devices = created

    def initialize(self) -> None:
        with self._lock:
            self._initialize_unlocked()

    def pressed(self, device: Device, code: int) -> bool:
        with self._lock:
            return code in self._pressed[device]

    def _send_frame(self, frame: Frame, protected: set[tuple[Device, int]]) -> None:
        events = tuple(
            event
            for event in frame.events
            if not (
                event.event_type == 0x01
                and event.temporary
                and (frame.device, event.code) in protected
            )
        )
        if not events:
            return

        device = self._devices[frame.device]
        for event in events:
            self._checked_write(
                device,
                event.event_type,
                event.code,
                event.value,
            )
        self._checked_write(device, *SYN_REPORT)

        pressed = self._pressed[frame.device]
        for event in events:
            if event.event_type != 0x01:
                continue
            if event.value == 1:
                pressed.add(event.code)
            elif event.value == 0:
                pressed.discard(event.code)

        for event in frame.events:
            if event.event_type != 0x01 or event.temporary:
                continue
            pair = (frame.device, event.code)
            if event.value == 1:
                protected.add(pair)
            elif event.value == 0:
                protected.discard(pair)

    def send(self, frames: Frames) -> None:
        if not frames:
            return
        with self._lock:
            self._initialize_unlocked()
            protected = {
                (device, code)
                for device, codes in self._pressed.items()
                for code in codes
            }
            try:
                for frame in frames:
                    self._send_frame(frame, protected)
            except Exception as exc:
                self._close_unlocked()
                raise InputError(
                    "Native input failed; virtual devices were reset."
                ) from exc


_previous_backend = globals().get("_backend")
if _previous_backend is not None:
    try:
        _previous_backend.close()
    except Exception:
        pass
_backend = UInputBackend()


def get_backend() -> UInputBackend:
    return _backend


def _close_backend() -> None:
    _backend.close()


if "_atexit_registered" not in globals():
    atexit.register(_close_backend)
    _atexit_registered = True
