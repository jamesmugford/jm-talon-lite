import os
import subprocess
import sys

from talon import Context, Module, actions, app, ui

from .tracking_forwarder.core import desktop_bounds_from_rects, normalize_point

mod = Module()
mod.tag(
    "wayland_mouse_forwarder",
    desc="Enable Wayland mouse forwarder command overrides.",
)

ctx = Context()
ctx.matches = r"""
os: linux
"""

_dotool_proc = None
_buttons_down: set[int] = set()


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
        print(f"mouse forwarder dotoolc error: {exc}", file=sys.stderr, flush=True)
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
        print(f"mouse forwarder write error: {exc}", file=sys.stderr, flush=True)
        _close_dotool_proc()


def _release_all_buttons() -> bool:
    had_buttons = bool(_buttons_down)
    _send_dotool_line("buttonup left")
    _send_dotool_line("buttonup right")
    _send_dotool_line("buttonup middle")
    _buttons_down.clear()
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
        _buttons_down.add(button)

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
        _buttons_down.discard(button)

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

        if button in _buttons_down:
            actions.mouse_release(button)
            return
        actions.mouse_drag(button)


def _on_ready() -> None:
    if not _is_wayland():
        ctx.tags = []
        return
    ctx.tags = ["user.wayland_mouse_forwarder"]


app.register("ready", _on_ready)
