"""Event-driven diagnostic logging for Control Mouse gaze samples."""

import sys

from talon import Module, actions, app, settings, tracking_system

_CALLBACK_KEY = "_jm_talon_lite_control1_gaze_logger_callback"
_STATE_KEY = "_jm_talon_lite_control1_gaze_logger_enabled"

_legacy_state_present = "_registered" in globals()
_legacy_registered = bool(globals().get("_registered", False))
_legacy_callback = globals().get("_on_gaze")
_retained_callback = getattr(sys, _CALLBACK_KEY, None)
_had_retained_state = (
    hasattr(sys, _STATE_KEY) or _legacy_state_present or _retained_callback is not None
)
_resume_registered = bool(
    getattr(
        sys,
        _STATE_KEY,
        _legacy_registered or _retained_callback is not None,
    )
)
_previous_callbacks = {
    _legacy_callback,
    _retained_callback,
}
for _previous_callback in _previous_callbacks - {None}:
    for _ in range(16):
        tracking_system.unregister("gaze", _previous_callback)
_resume_callback = _retained_callback or _legacy_callback
if _resume_registered and _resume_callback is not None:
    setattr(sys, _CALLBACK_KEY, _resume_callback)
elif hasattr(sys, _CALLBACK_KEY):
    delattr(sys, _CALLBACK_KEY)
if _had_retained_state:
    setattr(sys, _STATE_KEY, _resume_registered)

from talon.plugins import eye_mouse  # noqa: E402

from .gaze_sample import GazeSample, format_gaze_sample  # noqa: E402

mod = Module()
mod.setting(
    "control1_gaze_logger_autostart",
    type=bool,
    default=False,
    desc="Auto-start control1 gaze logger at Talon startup.",
)
_registered = False


def _control1_sample_line() -> str:
    """Return a formatted line for the latest Control Mouse sample."""
    m = eye_mouse.mouse
    if not m.xy_hist or not m.eye_hist:
        return format_gaze_sample(None)

    xy = m.xy_hist[-1]
    d = m.delta_hist[-1] if m.delta_hist else None
    g = m.eye_hist[-1]
    return format_gaze_sample(
        GazeSample(
            timestamp=g.ts,
            x=xy.x,
            y=xy.y,
            gaze_x=g.gaze.x,
            gaze_y=g.gaze.y,
            delta_x=None if d is None else d.x,
            delta_y=None if d is None else d.y,
        )
    )


def _on_gaze(*_args) -> None:
    """Log the latest sample while Control Mouse is enabled."""
    if not actions.tracking.control1_enabled():
        return
    print(_control1_sample_line())


def _clear_gaze_subscriptions(callback) -> None:
    """Remove every retained registration for one gaze callback."""
    for _ in range(16):
        tracking_system.unregister("gaze", callback)


def _register_gaze() -> None:
    """Register exactly one process-retained gaze callback."""
    global _registered
    _clear_gaze_subscriptions(_on_gaze)
    tracking_system.register("gaze", _on_gaze)
    setattr(sys, _CALLBACK_KEY, _on_gaze)
    setattr(sys, _STATE_KEY, True)
    _registered = True


def _unregister_gaze() -> None:
    """Remove this module generation's gaze callback idempotently."""
    global _registered
    _clear_gaze_subscriptions(_on_gaze)
    if getattr(sys, _CALLBACK_KEY, None) is _on_gaze:
        delattr(sys, _CALLBACK_KEY)
    setattr(sys, _STATE_KEY, False)
    _registered = False


@mod.action_class
class Actions:
    @staticmethod
    def control1_gaze_logger_start() -> None:
        """Enable control1 gaze logger (gaze-event driven)."""
        _register_gaze()
        print(
            "control1_gaze_logger started mode=gaze "
            f"enabled={actions.tracking.control1_enabled()}"
        )

    @staticmethod
    def control1_gaze_logger_stop() -> None:
        """Disable control1 gaze logger."""
        _unregister_gaze()
        print("control1_gaze_logger stopped")

    @staticmethod
    def control1_gaze_logger_once() -> None:
        """Log one control1 eye tracking sample."""
        print(_control1_sample_line())


def _on_ready() -> None:
    """Start logging when its Talon autostart setting is enabled."""
    if _had_retained_state or not settings.get("user.control1_gaze_logger_autostart"):
        return
    actions.user.control1_gaze_logger_start()


def _on_quit() -> None:
    """Release gaze subscriptions before Talon exits."""
    _unregister_gaze()


setattr(sys, _STATE_KEY, _resume_registered)
if _resume_registered:
    _register_gaze()

app.register("ready", _on_ready)
app.register("quit", _on_quit)
