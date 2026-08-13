"""Initialize virtual input devices when Talon is ready."""

import sys

from talon import app

from .backend import InputError
from .talon_input import get_input


def _on_ready() -> None:
    try:
        get_input().initialize()
    except (InputError, RuntimeError) as exc:
        message = str(exc)
        print(f"native input error: {message}", file=sys.stderr, flush=True)
        app.notify(message)
    else:
        print("jm-talon-lite native input backend ready")


app.register("ready", _on_ready)
