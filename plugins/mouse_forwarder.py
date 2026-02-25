import os
import subprocess
import sys

from talon import Context, Module, actions, app, ui

from .shared.pure_utils import desktop_bounds_from_rects, normalize_point

mod = Module()
mod.tag(
    "wayland_mouse_forwarder",
    desc="Enable Wayland mouse forwarder command overrides.",
)

ctx = Context()
ctx.matches = r"""
os: linux
"""

_dotoolc_proc = None
_pressed_buttons: set[int] = set()


def _is_wayland() -> bool:
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    if os.environ.get("SWAYSOCK"):
        return True
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def _button_name(button: int) -> str | None:
    if button == 0:
        return "left"
    if button == 1:
        return "right"
    if button == 2:
        return "middle"
    return None


def _close_dotoolc_proc() -> None:
    global _dotoolc_proc
    if _dotoolc_proc is None:
        return

    proc = _dotoolc_proc
    _dotoolc_proc = None

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


def _ensure_dotoolc_proc() -> bool:
    global _dotoolc_proc
    if _dotoolc_proc is not None and _dotoolc_proc.poll() is None and _dotoolc_proc.stdin:
        return True

    _close_dotoolc_proc()
    try:
        _dotoolc_proc = subprocess.Popen(
            ["dotoolc"],
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        print(f"mouse_forwarder dotoolc error: {exc}", file=sys.stderr, flush=True)
        _dotoolc_proc = None
        return False

    if _dotoolc_proc.stdin is None:
        _close_dotoolc_proc()
        return False
    return True


def _send_dotool_line(line: str) -> None:
    if not _ensure_dotoolc_proc():
        return

    assert _dotoolc_proc is not None
    assert _dotoolc_proc.stdin is not None
    try:
        _dotoolc_proc.stdin.write(f"{line}\n")
        _dotoolc_proc.stdin.flush()
        return
    except Exception:
        _close_dotoolc_proc()

    if not _ensure_dotoolc_proc():
        return

    assert _dotoolc_proc is not None
    assert _dotoolc_proc.stdin is not None
    try:
        _dotoolc_proc.stdin.write(f"{line}\n")
        _dotoolc_proc.stdin.flush()
    except Exception as exc:
        print(f"mouse_forwarder write error: {exc}", file=sys.stderr, flush=True)
        _close_dotoolc_proc()


def _release_all_buttons() -> bool:
    had_buttons = bool(_pressed_buttons)
    _send_dotool_line("buttonup left")
    _send_dotool_line("buttonup right")
    _send_dotool_line("buttonup middle")
    _pressed_buttons.clear()
    return had_buttons


@ctx.action_class("main")
class MainActions:
    @staticmethod
    def mouse_click(button: int = 0):
        if not _is_wayland():
            actions.next(button)
            return

        button_name = _button_name(button)
        if button_name is None:
            actions.next(button)
            return
        _send_dotool_line(f"click {button_name}")

    @staticmethod
    def mouse_drag(button: int = 0):
        if not _is_wayland():
            actions.next(button)
            return

        button_name = _button_name(button)
        if button_name is None:
            actions.next(button)
            return
        _send_dotool_line(f"buttondown {button_name}")
        _pressed_buttons.add(button)

    @staticmethod
    def mouse_release(button: int = 0):
        if not _is_wayland():
            actions.next(button)
            return

        button_name = _button_name(button)
        if button_name is None:
            actions.next(button)
            return
        _send_dotool_line(f"buttonup {button_name}")
        _pressed_buttons.discard(button)

    @staticmethod
    def mouse_move(x: float, y: float):
        if not _is_wayland():
            actions.next(x, y)
            return

        rects = [
            (screen.rect.x, screen.rect.y, screen.rect.width, screen.rect.height)
            for screen in ui.screens()
        ]
        bounds = desktop_bounds_from_rects(rects)
        nx, ny = normalize_point(bounds, x, y)
        _send_dotool_line(f"mouseto {nx:.6f} {ny:.6f}")


@ctx.action_class("user")
class UserActions:
    @staticmethod
    def mouse_drag_end() -> bool:
        if not _is_wayland():
            return actions.next()
        return _release_all_buttons()

    @staticmethod
    def mouse_drag_toggle(button: int):
        if not _is_wayland():
            actions.next(button)
            return

        if button in _pressed_buttons:
            actions.mouse_release(button)
            return
        actions.mouse_drag(button)


def _on_ready() -> None:
    if not _is_wayland():
        ctx.tags = []
        return
    ctx.tags = ["user.wayland_mouse_forwarder"]


app.register("ready", _on_ready)
