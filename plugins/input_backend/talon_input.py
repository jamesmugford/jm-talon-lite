"""Talon-oriented API for the native Linux input backend."""

from .backend import InputError, get_backend
from .events import Device, temporary
from .keyboard import KeyboardResolver, commands_from_talon, frames_for_commands
from .pointer import (
    BUTTON_CODES,
    button_frames,
    click_frames,
    move_frames,
    scroll_frames,
)
from .xkb import XkbKeymap


class TalonInput:
    def __init__(self) -> None:
        self._keyboard: KeyboardResolver | None = None

    def _resolver(self) -> KeyboardResolver:
        if self._keyboard is None:
            self._keyboard = KeyboardResolver(XkbKeymap())
        return self._keyboard

    def _key_frames(self, parsed_keys):
        commands = commands_from_talon(parsed_keys)
        frames = frames_for_commands(commands, self._resolver())
        if not commands or frames is None:
            raise InputError("Talon key command could not be translated.")
        return frames

    def initialize(self) -> None:
        self._resolver()
        get_backend().initialize()

    def key(self, parsed_keys) -> None:
        get_backend().send(self._key_frames(parsed_keys))

    def click(self, button: int) -> None:
        get_backend().send(click_frames(button))

    def button(self, button: int, pressed: bool) -> None:
        get_backend().send(button_frames(button, pressed))

    def button_pressed(self, button: int) -> bool:
        code = BUTTON_CODES.get(button)
        return bool(
            code is not None and get_backend().pressed(Device.POINTER, code)
        )

    def release_buttons(self) -> bool:
        pressed = [button for button in BUTTON_CODES if self.button_pressed(button)]
        get_backend().send(tuple(
            frame
            for button in pressed
            for frame in button_frames(button, False)
        ))
        return bool(pressed)

    def move(self, x: float, y: float) -> None:
        get_backend().send(move_frames(x, y))

    def scroll(self, vertical: int = 0, horizontal: int = 0) -> None:
        get_backend().send(scroll_frames(vertical, horizontal))

    def modified_click(self, parsed_down, parsed_up, button: int) -> None:
        if self.button_pressed(button):
            return
        frames = (
            *self._key_frames(parsed_down),
            *click_frames(button),
            *self._key_frames(parsed_up),
        )
        get_backend().send(temporary(frames))


_previous_input = globals().get("_input")
if _previous_input is not None:
    keyboard = getattr(_previous_input, "_keyboard", None)
    xkb = getattr(keyboard, "_xkb", None)
    if xkb is not None:
        try:
            xkb.close()
        except Exception:
            pass
_input = TalonInput()


def get_input() -> TalonInput:
    return _input
