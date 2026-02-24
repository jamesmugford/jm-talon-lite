"""Global Talon key forwarding via dotool."""

from talon import Context, Module, actions, settings
import subprocess
import sys

from .dotool_translate import (
    KeySpec,
    dotool_actions_to_input,
    talon_key_to_dotool_actions,
)

mod = Module()
mod.setting(
    "key_forwarding_enabled",
    type=bool,
    default=False,
    desc="Forward Talon key() through external backend (global).",
)

ctx = Context()


@ctx.action_class("main")
class MainActions:
    @staticmethod
    def key(key: KeySpec):
        """Log and forward Talon key specs through dotoolc.

        Args:
            key: Talon key spec string.
        """
        if not settings.get("user.key_forwarding_enabled"):
            actions.next(key)
            return
        print(f"dotool key: {key!r}", file=sys.stderr, flush=True)
        try:
            # TODO: pass log_unknown callback to surface unmapped keys.
            actions_list = talon_key_to_dotool_actions(key)
            if not actions_list:
                return
            # Send a small batch to dotoolc (dotoold should be running).
            subprocess.run(
                ["dotoolc"],
                input=dotool_actions_to_input(actions_list),
                text=True,
                check=False,
                timeout=0.5,
            )
        except Exception as exc:
            print(f"dotool error: {exc}", file=sys.stderr, flush=True)
