import subprocess
import sys

from talon import Context, actions

ctx = Context()


def _dotool_left_click() -> None:
    try:
        subprocess.run(
            ["dotoolc"],
            input="click left\n",
            text=True,
            check=False,
            timeout=0.5,
        )
    except Exception as exc:
        print(f"dotool click error: {exc}", file=sys.stderr, flush=True)


@ctx.action_class("user")
class UserActions:
    @staticmethod
    def noise_trigger_hiss(active: bool):
        if active:
            actions.tracking.control1_toggle(True)
            return
        actions.tracking.control1_toggle(False)

    @staticmethod
    def noise_trigger_pop():
        _dotool_left_click()
