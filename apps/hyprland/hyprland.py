import json
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


def _run_hyprctl(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["hyprctl", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
    except Exception as exc:
        print(f"hyprland hyprctl error: {exc}", file=sys.stderr, flush=True)
        return None


def _hyprctl(*args: str) -> None:
    result = _run_hyprctl("--", *args)
    if result is None:
        return

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        print(f"hyprland hyprctl error: {message}", file=sys.stderr, flush=True)
        return

    output = result.stdout.strip()
    if output and any(line.strip().lower() != "ok" for line in output.splitlines()):
        print(f"hyprland hyprctl error: {output}", file=sys.stderr, flush=True)


def _hyprctl_json(command: str) -> dict | list | None:
    result = _run_hyprctl("-j", command)
    if result is None:
        return None
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        print(f"hyprland hyprctl error: {message}", file=sys.stderr, flush=True)
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"hyprland hyprctl JSON error: {exc}", file=sys.stderr, flush=True)
        return None
    return value if isinstance(value, (dict, list)) else None


def _dispatch(dispatcher: str, arg: Optional[str] = None) -> None:
    if arg is None or arg == "":
        _hyprctl("dispatch", dispatcher)
        return
    _hyprctl("dispatch", dispatcher, arg)


def _exec(command: str) -> None:
    command = command.strip()
    if not command:
        app.notify("Hyprland command cannot be empty.")
        return
    _dispatch("exec", command)


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


def _launch_scratch_terminal() -> None:
    command = _setting("user.hyprland_terminal_command", "xdg-terminal-exec").strip()
    if not command:
        app.notify("Terminal command cannot be empty.")
        return
    _dispatch("exec", f"[workspace special:scratchpad] {command}")


def _resolve_window_tiled_layout(window: dict, workspaces: list) -> str | None:
    """Purely resolve a window's tiled layout from Hyprland metadata.

    Args:
        window: Metadata from ``hyprctl -j activewindow``.
        workspaces: Metadata from ``hyprctl -j workspaces``.

    Returns:
        The tiled layout name, or ``None`` when it cannot be resolved.
    """
    window_workspace = window.get("workspace")
    if not isinstance(window_workspace, dict):
        return None

    # Match the focused window's workspace, including special workspaces.
    workspace_id = window_workspace.get("id")
    for workspace in workspaces:
        if not isinstance(workspace, dict) or workspace.get("id") != workspace_id:
            continue
        layout = workspace.get("tiledLayout")
        return layout if isinstance(layout, str) else None
    return None


def _resize_active_window_by_pixels(direction: int) -> None:
    pixels = direction * 100
    _dispatch("resizeactive", f"{pixels} {pixels}")


def _resize_active_window(direction: int) -> None:
    direction = 1 if direction > 0 else -1
    window = _hyprctl_json("activewindow")

    if not isinstance(window, dict):
        _resize_active_window_by_pixels(direction)
        return

    # Floating windows resize directly, then recenter like Community i3.
    if window.get("floating", False):
        _resize_active_window_by_pixels(direction)
        _dispatch("centerwindow")
        return

    workspaces = _hyprctl_json("workspaces")
    if not isinstance(workspaces, list):
        _resize_active_window_by_pixels(direction)
        return

    # Scrolling tiles resize by column rather than generic window pixels.
    if _resolve_window_tiled_layout(window, workspaces) == "scrolling":
        _dispatch("layoutmsg", f"colresize {direction * 0.1:+g}")
        return

    # Other tiled layouts use Hyprland's generic pixel resize fallback.
    _resize_active_window_by_pixels(direction)


@ctx.action_class("app")
class AppActions:
    def window_close():
        _dispatch("killactive")


@mod.action_class
class Actions:
    def hyprland_dispatch(dispatcher: str, arg: Optional[str] = None):
        """Run a legacy Hyprland dispatcher."""
        _dispatch(dispatcher, arg)

    def hyprland_exec(command: str):
        """Run a command through Hyprland."""
        _exec(command)

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
        """Toggle maximized mode for the active window."""
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

    def hyprland_resize_column(delta: float):
        """Resize the active scrolling-layout column."""
        _dispatch("layoutmsg", f"colresize {delta:+g}")

    def hyprland_resize_window(direction: int):
        """Grow or shrink using behavior appropriate for the active layout."""
        _resize_active_window(direction)

    def hyprland_shell():
        """Launch the configured terminal."""
        _exec(_setting("user.hyprland_terminal_command", "xdg-terminal-exec"))

    def hyprland_lock():
        """Run the configured screen lock command."""
        _exec(_setting("user.hyprland_lock_command", "hyprlock"))

    def hyprland_new_scratch_terminal():
        """Launch a terminal directly on the scratchpad workspace."""
        _launch_scratch_terminal()


def _on_ready() -> None:
    if _setting("user.hyprland_auto_enable", True) and _is_hyprland():
        tag_ctx.tags = ["user.hyprland"]
        return
    tag_ctx.tags = []


app.register("ready", _on_ready)
_on_ready()
