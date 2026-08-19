"""Pure Wayland session detection."""

from collections.abc import Mapping


def is_wayland_session(environment: Mapping[str, str]) -> bool:
    """Return whether standard environment values identify Wayland."""
    return bool(
        environment.get("WAYLAND_DISPLAY")
        or environment.get("SWAYSOCK")
        or environment.get("XDG_SESSION_TYPE", "").casefold() == "wayland"
    )
