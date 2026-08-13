"""Small immutable model for Linux input events."""

from dataclasses import dataclass
from enum import Enum


class Device(Enum):
    KEYBOARD = "keyboard"
    POINTER = "pointer"
    ABSOLUTE_POINTER = "absolute_pointer"


@dataclass(frozen=True)
class Event:
    event_type: int
    code: int
    value: int
    temporary: bool = False


@dataclass(frozen=True)
class Frame:
    device: Device
    events: tuple[Event, ...]


Frames = tuple[Frame, ...]


def temporary(frames: Frames) -> Frames:
    """Mark key/button events as temporary without changing other events."""
    return tuple(
        Frame(
            frame.device,
            tuple(
                Event(event.event_type, event.code, event.value, event.event_type == 1)
                for event in frame.events
            ),
        )
        for frame in frames
    )
