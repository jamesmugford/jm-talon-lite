"""Route Talon's Linux key action through uinput."""

import sys

from talon import Context, app
from talon.lib.keys import parse_keys

try:
    from ..input_backend.backend import InputError
    from ..input_backend.talon_input import get_input
except ImportError:  # Pure tests import this package from plugins/.
    from input_backend.backend import InputError
    from input_backend.talon_input import get_input


ctx = Context()
ctx.matches = "os: linux"

_last_error: str | None = None


def _report_error(error: Exception) -> None:
    global _last_error
    message = str(error)
    if message == _last_error:
        return
    _last_error = message
    print(f"native keyboard error: {message}", file=sys.stderr, flush=True)
    app.notify(message)


@ctx.action_class("main")
class MainActions:
    @staticmethod
    def key(key: str):
        """Send a Talon key specification through uinput."""
        global _last_error
        try:
            get_input().key(parse_keys(key))
        except (InputError, RuntimeError, ValueError) as exc:
            _report_error(exc)
        else:
            _last_error = None
