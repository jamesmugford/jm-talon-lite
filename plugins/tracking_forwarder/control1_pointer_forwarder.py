from talon import Module, actions, app, settings, tracking_system, ui
from talon.plugins import eye_mouse

from ..input_backend.backend import InputError
from ..input_backend.talon_input import get_input
from ..shared.pure_utils import desktop_bounds_from_rects, normalize_point

mod = Module()

mod.setting(
    "control1_pointer_forwarder_autostart",
    type=bool,
    default=False,
    desc="Auto-start control1 pointer forwarder at Talon startup.",
)
mod.setting(
    "control1_pointer_forwarder_autostart_log",
    type=bool,
    default=True,
    desc="Log when control1 pointer forwarder auto-starts.",
)

_desktop_bounds = (0.0, 0.0, 1.0, 1.0)
_last_error: str | None = None


def _refresh_desktop_bounds() -> None:
    global _desktop_bounds
    rects = [
        (screen.rect.x, screen.rect.y, screen.rect.width, screen.rect.height)
        for screen in ui.screens()
    ]
    _desktop_bounds = desktop_bounds_from_rects(rects)


def _clear_gaze_subscriptions() -> None:
    for _ in range(16):
        tracking_system.unregister("gaze", _on_gaze)


def _register_gaze() -> None:
    _clear_gaze_subscriptions()
    tracking_system.register("gaze", _on_gaze)


def _unregister_gaze() -> None:
    _clear_gaze_subscriptions()


def _on_gaze(*_args) -> None:
    global _last_error
    if not actions.tracking.control1_enabled():
        return

    hist = eye_mouse.mouse.xy_hist
    if not hist:
        return

    point = hist[-1]
    x, y = normalize_point(_desktop_bounds, point.x, point.y)
    try:
        get_input().move(x, y)
    except (InputError, RuntimeError) as exc:
        message = str(exc)
        if message != _last_error:
            _last_error = message
            print(f"control1_pointer_forwarder native error: {message}")
    else:
        _last_error = None


def _on_screen_change(_screens) -> None:
    _refresh_desktop_bounds()


@mod.action_class
class Actions:
    @staticmethod
    def control1_pointer_forwarder_start() -> None:
        """Start control1 pointer forwarding through uinput."""
        _refresh_desktop_bounds()
        _register_gaze()
        print(
            "control1_pointer_forwarder started "
            f"enabled={actions.tracking.control1_enabled()}"
        )

    @staticmethod
    def control1_pointer_forwarder_stop() -> None:
        """Stop control1 pointer forwarding."""
        _unregister_gaze()
        print("control1_pointer_forwarder stopped")

    @staticmethod
    def control1_pointer_forwarder_toggle(state: bool | None = None) -> None:
        """Enable or disable control1 pointer forwarding."""
        target = True if state is None else bool(state)
        if not target:
            actions.user.control1_pointer_forwarder_stop()
            return
        actions.user.control1_pointer_forwarder_start()


def _on_ready() -> None:
    ui.register("screen_change", _on_screen_change)
    _refresh_desktop_bounds()
    if settings.get("user.control1_pointer_forwarder_autostart"):
        actions.user.control1_pointer_forwarder_start()
        if settings.get("user.control1_pointer_forwarder_autostart_log"):
            print(
                "control1_pointer_forwarder autostarted "
                f"enabled={actions.tracking.control1_enabled()}"
            )
        return


app.register("ready", _on_ready)
