"""Build generic Linux pointer events."""

from .events import Device, Event, Frame, Frames


EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

REL_HWHEEL = 6
REL_WHEEL = 8
ABS_X = 0
ABS_Y = 1
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113
BTN_EXTRA = 0x114

ABSOLUTE_MAX = 65535
BUTTON_CODES = {
    0: BTN_LEFT,
    1: BTN_RIGHT,
    2: BTN_MIDDLE,
    3: BTN_SIDE,
    4: BTN_EXTRA,
}


def button_frames(button: int, pressed: bool, *, temporary: bool = False) -> Frames:
    code = BUTTON_CODES.get(button)
    if code is None:
        raise ValueError(f"Unsupported mouse button: {button}")
    return (
        Frame(
            Device.POINTER,
            (Event(EV_KEY, code, int(pressed), temporary),),
        ),
    )


def click_frames(button: int) -> Frames:
    return (
        *button_frames(button, True, temporary=True),
        *button_frames(button, False, temporary=True),
    )


def scroll_frames(vertical: int = 0, horizontal: int = 0) -> Frames:
    events = []
    if vertical:
        events.append(Event(EV_REL, REL_WHEEL, vertical))
    if horizontal:
        events.append(Event(EV_REL, REL_HWHEEL, horizontal))
    if not events:
        return ()
    return (Frame(Device.POINTER, tuple(events)),)


def move_frames(x: float, y: float) -> Frames:
    x = min(1.0, max(0.0, x))
    y = min(1.0, max(0.0, y))
    return (
        Frame(
            Device.ABSOLUTE_POINTER,
            (
                Event(EV_ABS, ABS_X, round(x * ABSOLUTE_MAX)),
                Event(EV_ABS, ABS_Y, round(y * ABSOLUTE_MAX)),
            ),
        ),
    )
