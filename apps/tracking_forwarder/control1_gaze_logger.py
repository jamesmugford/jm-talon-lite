from talon import Context, Module, actions, app, tracking_system
from talon.plugins import eye_mouse

from .core import format_control1_sample

ctx = Context()
mod = Module()

_control1_gaze_logger_armed = True
_control1_gaze_subscribed = False


def _control1_sample_line() -> str:
    m = eye_mouse.mouse
    if not m.xy_hist or not m.eye_hist:
        return "control1 no samples"

    xy = m.xy_hist[-1]
    d = m.delta_hist[-1] if m.delta_hist else None
    g = m.eye_hist[-1]

    delta = None if d is None else (d.x, d.y)
    return format_control1_sample(
        timestamp=g.ts,
        xy_px=(xy.x, xy.y),
        gaze_norm=(g.gaze.x, g.gaze.y),
        delta=delta,
    )


def _on_gaze(*_args) -> None:
    if not _control1_gaze_logger_armed:
        return
    if not actions.tracking.control1_enabled():
        return
    print(_control1_sample_line())


def _register_gaze() -> None:
    global _control1_gaze_subscribed
    if _control1_gaze_subscribed:
        return
    tracking_system.register("gaze", _on_gaze)
    _control1_gaze_subscribed = True


def _unregister_gaze() -> None:
    global _control1_gaze_subscribed
    if not _control1_gaze_subscribed:
        return
    tracking_system.unregister("gaze", _on_gaze)
    _control1_gaze_subscribed = False


def _sync_gaze_logging() -> None:
    if not _control1_gaze_logger_armed:
        _unregister_gaze()
        return

    if not actions.tracking.control1_enabled():
        _unregister_gaze()
        return

    _register_gaze()


@ctx.action_class("user")
class UserActions:
    @staticmethod
    def control1_started() -> None:
        actions.next()
        _sync_gaze_logging()

    @staticmethod
    def control1_stopped() -> None:
        actions.next()
        _sync_gaze_logging()


@mod.action_class
class Actions:
    @staticmethod
    def control1_gaze_logger_start() -> None:
        """Enable control1 gaze logger (gaze-event driven)."""
        global _control1_gaze_logger_armed
        _control1_gaze_logger_armed = True
        _sync_gaze_logging()
        print(
            "control1_gaze_logger started mode=gaze "
            f"enabled={actions.tracking.control1_enabled()}"
        )

    @staticmethod
    def control1_gaze_logger_stop() -> None:
        """Disable control1 gaze logger."""
        global _control1_gaze_logger_armed
        _control1_gaze_logger_armed = False
        _unregister_gaze()
        print("control1_gaze_logger stopped")

    @staticmethod
    def control1_gaze_logger_once() -> None:
        """Log one control1 eye tracking sample."""
        print(_control1_sample_line())

    @staticmethod
    def control1_gaze_logger_running() -> bool:
        """Return whether control1 gaze logger is actively receiving gaze events."""
        return _control1_gaze_subscribed


def _on_ready() -> None:
    _sync_gaze_logging()


app.register("ready", _on_ready)
