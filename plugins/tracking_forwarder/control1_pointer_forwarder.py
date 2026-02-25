import subprocess

from talon import Module, actions, app, settings, tracking_system, ui
from talon.plugins import eye_mouse

from .core import desktop_bounds_from_rects, normalize_point

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

_dotool_proc = None
_desktop_bounds = (0.0, 0.0, 1.0, 1.0)


def _refresh_desktop_bounds() -> None:
    global _desktop_bounds
    rects = [
        (screen.rect.x, screen.rect.y, screen.rect.width, screen.rect.height)
        for screen in ui.screens()
    ]
    _desktop_bounds = desktop_bounds_from_rects(rects)


def _close_dotool_proc() -> None:
    global _dotool_proc
    if _dotool_proc is None:
        return

    proc = _dotool_proc
    _dotool_proc = None

    try:
        if proc.stdin is not None:
            proc.stdin.close()
    except Exception:
        pass

    try:
        proc.terminate()
        proc.wait(timeout=0.1)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=0.1)
        except Exception:
            pass
    except Exception:
        pass


def _ensure_dotool_proc() -> bool:
    global _dotool_proc
    if _dotool_proc is not None and _dotool_proc.poll() is None and _dotool_proc.stdin:
        return True

    _close_dotool_proc()
    try:
        _dotool_proc = subprocess.Popen(
            ["dotoolc"],
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        print(f"control1 pointer forwarder dotoolc error: {exc}")
        _dotool_proc = None
        return False

    if _dotool_proc.stdin is None:
        _close_dotool_proc()
        return False
    return True


def _send_dotool_line(line: str) -> None:
    if not _ensure_dotool_proc():
        return

    assert _dotool_proc is not None
    assert _dotool_proc.stdin is not None
    try:
        _dotool_proc.stdin.write(f"{line}\n")
        _dotool_proc.stdin.flush()
        return
    except Exception:
        _close_dotool_proc()

    if not _ensure_dotool_proc():
        return

    assert _dotool_proc is not None
    assert _dotool_proc.stdin is not None
    try:
        _dotool_proc.stdin.write(f"{line}\n")
        _dotool_proc.stdin.flush()
    except Exception as exc:
        print(f"control1 pointer forwarder write error: {exc}")
        _close_dotool_proc()


def _clear_gaze_subscriptions() -> None:
    for _ in range(16):
        tracking_system.unregister("gaze", _on_gaze)


def _register_gaze() -> None:
    _clear_gaze_subscriptions()
    tracking_system.register("gaze", _on_gaze)


def _unregister_gaze() -> None:
    _clear_gaze_subscriptions()


def _on_gaze(*_args) -> None:
    if not actions.tracking.control1_enabled():
        _close_dotool_proc()
        return

    hist = eye_mouse.mouse.xy_hist
    if not hist:
        return

    point = hist[-1]
    x, y = normalize_point(_desktop_bounds, point.x, point.y)
    _send_dotool_line(f"mouseto {x:.6f} {y:.6f}")


def _on_screen_change(_screens) -> None:
    _refresh_desktop_bounds()


@mod.action_class
class Actions:
    @staticmethod
    def control1_pointer_forwarder_start() -> None:
        """Start control1 pointer forwarding through dotool mouseto."""
        _refresh_desktop_bounds()
        _register_gaze()
        print(
            "control1 pointer forwarder started "
            f"enabled={actions.tracking.control1_enabled()}"
        )

    @staticmethod
    def control1_pointer_forwarder_stop() -> None:
        """Stop control1 pointer forwarding."""
        _unregister_gaze()
        _close_dotool_proc()
        print("control1 pointer forwarder stopped")

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
                "control1 pointer forwarder autostarted "
                f"enabled={actions.tracking.control1_enabled()}"
            )
        return


app.register("ready", _on_ready)
