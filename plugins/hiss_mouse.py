import subprocess
import sys

from talon import Context, Module, actions, app, settings

from .shared.pure_utils import resolve_toggle_state

ctx = Context()
mod = Module()

mod.setting(
    "hiss_mouse_autostart",
    type=bool,
    default=False,
    desc="Enable hiss mouse on Talon startup.",
)

_hiss_mouse_enabled = False


def _dotool_click_payload(button: str) -> str:
    """Return dotool click payload for a mouse button name."""
    return f"click {button}\n"


def _forward_left_click() -> None:
    try:
        subprocess.run(
            ["dotoolc"],
            input=_dotool_click_payload("left"),
            text=True,
            check=False,
            timeout=0.5,
        )
    except Exception as exc:
        print(f"dotool click error: {exc}", file=sys.stderr, flush=True)


def _enable_hiss_mouse() -> None:
    global _hiss_mouse_enabled
    _hiss_mouse_enabled = True


def _disable_hiss_mouse() -> None:
    global _hiss_mouse_enabled
    _hiss_mouse_enabled = False
    if not actions.tracking.control1_enabled():
        return
    actions.tracking.control1_toggle(False)


def _set_hiss_mouse_enabled(enabled: bool) -> None:
    if enabled:
        _enable_hiss_mouse()
        return
    _disable_hiss_mouse()


@ctx.action_class("user")
class UserActions:
    @staticmethod
    def noise_trigger_hiss(active: bool):
        if not _hiss_mouse_enabled:
            return
        if active:
            actions.tracking.control1_toggle(True)
            return
        actions.tracking.control1_toggle(False)

    @staticmethod
    def noise_trigger_pop():
        if not _hiss_mouse_enabled:
            return
        _forward_left_click()


@mod.action_class
class Actions:
    @staticmethod
    def hiss_mouse_enable() -> None:
        """Enable hiss mouse behavior."""
        _set_hiss_mouse_enabled(True)

    @staticmethod
    def hiss_mouse_disable() -> None:
        """Disable hiss mouse behavior."""
        _set_hiss_mouse_enabled(False)

    @staticmethod
    def hiss_mouse_toggle(state: bool | None = None) -> None:
        """Toggle hiss mouse behavior."""
        target = resolve_toggle_state(_hiss_mouse_enabled, state)
        _set_hiss_mouse_enabled(target)

    @staticmethod
    def hiss_mouse_enabled() -> bool:
        """Return whether hiss mouse behavior is enabled."""
        return _hiss_mouse_enabled


def _on_ready() -> None:
    if not settings.get("user.hiss_mouse_autostart"):
        return
    actions.user.hiss_mouse_enable()


app.register("ready", _on_ready)
