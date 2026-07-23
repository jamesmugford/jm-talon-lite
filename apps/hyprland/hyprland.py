import os
import subprocess
import sys
from typing import Optional, Union

from talon import Context, Module, app, settings

mod = Module()
tag_ctx = Context()
ctx = Context()

mod.tag("hyprland", desc="Enable Hyprland voice command mappings.")
mod.setting(
    "hyprland_auto_enable",
    type=bool,
    default=True,
    desc="Automatically enable the Hyprland tag when Talon is running under Hyprland.",
)
mod.setting(
    "hyprland_launcher_command",
    type=str,
    default="omarchy-launch-walker",
    desc="Command Hyprland should run for the app launcher.",
)
mod.setting(
    "hyprland_terminal_command",
    type=str,
    default="xdg-terminal-exec",
    desc="Command Hyprland should run for a terminal.",
)
mod.setting(
    "hyprland_lock_command",
    type=str,
    default="hyprlock",
    desc="Command Hyprland should run to lock the session.",
)

tag_ctx.matches = r"""
os: linux
"""

ctx.matches = r"""
tag: user.hyprland
"""


def _is_hyprland() -> bool:
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return True

    desktop_values = (
        os.environ.get("XDG_CURRENT_DESKTOP", ""),
        os.environ.get("XDG_SESSION_DESKTOP", ""),
    )
    return any("hyprland" in value.lower() for value in desktop_values)


def _setting(name: str, default):
    try:
        return settings.get(name)
    except KeyError:
        return default


def _hyprctl(*args: str) -> None:
    try:
        result = subprocess.run(
            ["hyprctl", "--", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=1,
        )
    except Exception as exc:
        print(f"hyprland hyprctl error: {exc}", file=sys.stderr, flush=True)
        return

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        print(f"hyprland hyprctl error: {message}", file=sys.stderr, flush=True)


def _dispatch(dispatcher: str, arg: Optional[str] = None) -> None:
    if arg is None or arg == "":
        _hyprctl("dispatch", dispatcher)
        return
    _hyprctl("dispatch", dispatcher, arg)


def _direction(value: str) -> str:
    directions = {
        "left": "l",
        "right": "r",
        "up": "u",
        "down": "d",
    }
    return directions.get(value, value)


def _workspace_arg(which: Union[str, int]) -> str:
    return str(which)


@ctx.action_class("app")
class AppActions:
    def window_close():
        _dispatch("killactive")


@mod.action_class
class Actions:
    def hyprland_dispatch(dispatcher: str, arg: Optional[str] = None):
        """Run a Hyprland dispatcher."""
        _dispatch(dispatcher, arg)

    def hyprland_exec(command: str):
        """Run a command through Hyprland."""
        _dispatch("exec", command)

    def hyprland_reload():
        """Reload the Hyprland config."""
        _hyprctl("reload")

    def hyprland_focus(what: str):
        """Move focus."""
        _dispatch("movefocus", _direction(what))

    def hyprland_swap(direction: str):
        """Swap the active window in a direction."""
        _dispatch("swapwindow", _direction(direction))

    def hyprland_switch_to_workspace(which: Union[str, int]):
        """Focus the specified workspace."""
        _dispatch("workspace", _workspace_arg(which))

    def hyprland_move_to_workspace(which: Union[str, int]):
        """Move the active window to the specified workspace."""
        _dispatch("movetoworkspace", _workspace_arg(which))

    def hyprland_move_to_scratchpad():
        """Move the active window to the scratchpad."""
        _dispatch("movetoworkspacesilent", "special:scratchpad")

    def hyprland_show_scratchpad():
        """Toggle the scratchpad workspace."""
        _dispatch("togglespecialworkspace", "scratchpad")

    def hyprland_fullscreen():
        """Toggle fullscreen for the active window."""
        _dispatch("fullscreen", "0")

    def hyprland_full_width():
        """Toggle full-width mode for the active window."""
        _dispatch("fullscreen", "1")

    def hyprland_float():
        """Toggle floating for the active window."""
        _dispatch("togglefloating")

    def hyprland_center():
        """Center the active floating window."""
        _dispatch("centerwindow")

    def hyprland_toggle_split():
        """Toggle dwindle split direction."""
        _dispatch("layoutmsg", "togglesplit")

    def hyprland_preselect(direction: str):
        """Preselect where the next dwindle window should open."""
        _dispatch("layoutmsg", f"preselect {_direction(direction)}")

    def hyprland_resize(width_delta: int, height_delta: int):
        """Resize the active window."""
        _dispatch("resizeactive", f"{width_delta} {height_delta}")

    def hyprland_launch():
        """Launch the configured app launcher."""
        _dispatch("exec", _setting("user.hyprland_launcher_command", "omarchy-launch-walker"))

    def hyprland_shell():
        """Launch the configured terminal."""
        _dispatch("exec", _setting("user.hyprland_terminal_command", "xdg-terminal-exec"))

    def hyprland_lock():
        """Run the configured screen lock command."""
        _dispatch("exec", _setting("user.hyprland_lock_command", "hyprlock"))


def _on_ready() -> None:
    if _setting("user.hyprland_auto_enable", True) and _is_hyprland():
        tag_ctx.tags = ["user.hyprland"]
        return
    tag_ctx.tags = []


app.register("ready", _on_ready)
_on_ready()
