import subprocess
import sys

from talon import Context, actions

ctx = Context()


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
        _forward_left_click()
