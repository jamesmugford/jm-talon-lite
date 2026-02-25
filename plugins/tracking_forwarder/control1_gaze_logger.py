from talon import Module, actions, app, settings, tracking_system
from talon.plugins import eye_mouse

from ..shared.pure_utils import format_control1_sample

mod = Module()

mod.setting(
    "control1_gaze_logger_autostart",
    type=bool,
    default=False,
    desc="Auto-start control1 gaze logger at Talon startup.",
)

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
    if not actions.tracking.control1_enabled():
        return
    print(_control1_sample_line())


def _clear_gaze_subscriptions() -> None:
    for _ in range(16):
        tracking_system.unregister("gaze", _on_gaze)


def _register_gaze() -> None:
    _clear_gaze_subscriptions()
    tracking_system.register("gaze", _on_gaze)


def _unregister_gaze() -> None:
    _clear_gaze_subscriptions()


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
    if not settings.get("user.control1_gaze_logger_autostart"):
        return
    actions.user.control1_gaze_logger_start()


app.register("ready", _on_ready)
