import subprocess

from talon import Context, Module, actions, app, settings, tracking_system, ui
from talon.plugins import eye_mouse

from .core import desktop_bounds_from_rects, normalize_point

ctx = Context()
mod = Module()

mod.setting(
    "control1_pointer_forwarder_autostart",
    type=bool,
    default=False,
    desc="Auto-start control1 pointer forwarder on Talon startup.",
)
mod.setting(
    "control1_pointer_forwarder_autostart_log",
    type=bool,
    default=True,
    desc="Log when control1 pointer forwarder auto-starts.",
)

_pointer_armed = False
_gaze_registered = False
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


def _register_gaze() -> None:
    global _gaze_registered
    if _gaze_registered:
        return
    tracking_system.register("gaze", _on_gaze)
    _gaze_registered = True


def _unregister_gaze() -> None:
    global _gaze_registered
    if not _gaze_registered:
        return
    tracking_system.unregister("gaze", _on_gaze)
    _gaze_registered = False


def _sync_pointer_forwarding() -> None:
    if not _pointer_armed:
        _unregister_gaze()
        _close_dotool_proc()
        return

    if not actions.tracking.control1_enabled():
        _unregister_gaze()
        _close_dotool_proc()
        return

    _refresh_desktop_bounds()
    _register_gaze()


def _on_gaze(*_args) -> None:
    if not _pointer_armed:
        return

    if not actions.tracking.control1_enabled():
        return

    hist = eye_mouse.mouse.xy_hist
    if not hist:
        return

    point = hist[-1]
    x, y = normalize_point(_desktop_bounds, point.x, point.y)
    _send_dotool_line(f"mouseto {x:.6f} {y:.6f}")


def _on_screen_change(_screens) -> None:
    _refresh_desktop_bounds()


@ctx.action_class("user")
class UserActions:
    @staticmethod
    def control1_started() -> None:
        actions.next()
        _sync_pointer_forwarding()

    @staticmethod
    def control1_stopped() -> None:
        actions.next()
        _sync_pointer_forwarding()


@mod.action_class
class Actions:
    @staticmethod
    def control1_pointer_forwarder_start() -> None:
        """Start control1 pointer forwarding through dotool mouseto."""
        global _pointer_armed
        _pointer_armed = True
        _sync_pointer_forwarding()
        print(
            "control1 pointer forwarder started "
            f"enabled={actions.tracking.control1_enabled()}"
        )

    @staticmethod
    def control1_pointer_forwarder_stop() -> None:
        """Stop control1 pointer forwarding."""
        global _pointer_armed
        _pointer_armed = False
        _sync_pointer_forwarding()
        print("control1 pointer forwarder stopped")

    @staticmethod
    def control1_pointer_forwarder_toggle(state: bool | None = None) -> None:
        """Toggle control1 pointer forwarding."""
        target = (not _pointer_armed) if state is None else bool(state)
        if not target:
            actions.user.control1_pointer_forwarder_stop()
            return
        actions.user.control1_pointer_forwarder_start()

    @staticmethod
    def control1_pointer_forwarder_running() -> bool:
        """Return whether control1 pointer forwarding is armed."""
        return _pointer_armed


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
    _sync_pointer_forwarding()


app.register("ready", _on_ready)
