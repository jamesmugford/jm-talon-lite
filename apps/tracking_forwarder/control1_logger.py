from talon import Context, Module, actions, app, tracking_system
from talon.plugins import eye_mouse

ctx = Context()
mod = Module()

_eye_legacy_log_armed = True
_eye_legacy_gaze_registered = False


def _legacy_sample_line() -> str:
    m = eye_mouse.mouse
    if not m.xy_hist or not m.eye_hist:
        return "eye_legacy no samples"

    xy = m.xy_hist[-1]
    d = m.delta_hist[-1] if m.delta_hist else None
    g = m.eye_hist[-1]

    if d is None:
        return (
            f"eye_legacy ts={g.ts:.3f} "
            f"xy_px=({xy.x:.1f},{xy.y:.1f}) "
            f"gaze_norm=({g.gaze.x:.3f},{g.gaze.y:.3f})"
        )

    return (
        f"eye_legacy ts={g.ts:.3f} "
        f"xy_px=({xy.x:.1f},{xy.y:.1f}) "
        f"delta=({d.x:.2f},{d.y:.2f}) "
        f"gaze_norm=({g.gaze.x:.3f},{g.gaze.y:.3f})"
    )


def _on_gaze(*_args) -> None:
    if not _eye_legacy_log_armed:
        return
    if not actions.tracking.control1_enabled():
        return
    print(_legacy_sample_line())


def _register_gaze() -> None:
    global _eye_legacy_gaze_registered
    if _eye_legacy_gaze_registered:
        return
    tracking_system.register("gaze", _on_gaze)
    _eye_legacy_gaze_registered = True


def _unregister_gaze() -> None:
    global _eye_legacy_gaze_registered
    if not _eye_legacy_gaze_registered:
        return
    tracking_system.unregister("gaze", _on_gaze)
    _eye_legacy_gaze_registered = False


def _sync_gaze_logging() -> None:
    if not _eye_legacy_log_armed:
        _unregister_gaze()
        return

    if not actions.tracking.control1_enabled():
        _unregister_gaze()
        return

    _register_gaze()


@ctx.action_class("user")
class UserActions:
    @staticmethod
    def eye_legacy_started() -> None:
        actions.next()
        _sync_gaze_logging()

    @staticmethod
    def eye_legacy_stopped() -> None:
        actions.next()
        _sync_gaze_logging()


@mod.action_class
class Actions:
    @staticmethod
    def eye_legacy_log_start(interval: str = "100ms") -> None:
        """Enable legacy eye logger (gaze-event driven)."""
        global _eye_legacy_log_armed
        _eye_legacy_log_armed = True
        _sync_gaze_logging()
        print(
            "eye_legacy logger started mode=gaze "
            f"interval_ignored={interval} "
            f"enabled={actions.tracking.control1_enabled()}"
        )

    @staticmethod
    def eye_legacy_log_stop() -> None:
        """Disable legacy eye logger."""
        global _eye_legacy_log_armed
        _eye_legacy_log_armed = False
        _unregister_gaze()
        print("eye_legacy logger stopped")

    @staticmethod
    def eye_legacy_log_once() -> None:
        """Log one legacy eye tracking sample."""
        print(_legacy_sample_line())

    @staticmethod
    def eye_legacy_log_running() -> bool:
        """Return whether legacy eye logger is actively receiving gaze events."""
        return _eye_legacy_gaze_registered


def _on_ready() -> None:
    _sync_gaze_logging()


app.register("ready", _on_ready)
