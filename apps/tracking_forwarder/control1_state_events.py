from talon import Context, Module, actions, app
from talon.plugins import eye_mouse_2

from .core import should_emit_state_change

ctx = Context()
mod = Module()


def _emit_control1_state(enabled: bool) -> None:
    print(f"control1 enabled={enabled}")
    actions.user.control1_state_changed(enabled)
    if enabled:
        actions.user.control1_started()
        return
    actions.user.control1_stopped()


def _install_menu_hook() -> bool:
    item = getattr(eye_mouse_2, "control1_item", None)
    if item is None:
        return False

    attrs = getattr(item, "attrs", None)
    if attrs is None:
        return False

    if attrs.get("_control1_state_menu_wrapper", False):
        return True

    cb = attrs.get("cb")
    if cb is None:
        return False

    def wrapped(menu_item, orig_cb=cb):
        before = actions.tracking.control1_enabled()
        result = orig_cb(menu_item)
        after = actions.tracking.control1_enabled()
        if not should_emit_state_change(before, after):
            return result
        _emit_control1_state(after)
        return result

    attrs["cb"] = wrapped
    attrs["_control1_state_menu_wrapper"] = True
    return True


@ctx.action_class("tracking")
class TrackingActions:
    @staticmethod
    def control1_toggle(state=None) -> None:
        """Wrap control1 toggle and emit state hooks."""
        before = actions.tracking.control1_enabled()
        actions.next(state)
        after = actions.tracking.control1_enabled()
        if not should_emit_state_change(before, after):
            return
        _emit_control1_state(after)


@mod.action_class
class Actions:
    @staticmethod
    def control1_started() -> None:
        """Hook called when control1 mouse starts."""
        _ = 0

    @staticmethod
    def control1_stopped() -> None:
        """Hook called when control1 mouse stops."""
        _ = 0

    @staticmethod
    def control1_state_changed(enabled: bool) -> None:
        """Hook called when control1 state changes."""
        _ = enabled

    @staticmethod
    def control1_state_events_start() -> None:
        """Enable control1 state events (event-driven, no polling)."""
        hooked = _install_menu_hook()
        print(
            f"control1 state events started mode=events "
            f"hooked={hooked}"
        )

    @staticmethod
    def control1_state_events_stop() -> None:
        """No-op: state events are always on once loaded."""
        print("control1 state events stopped (no-op in event mode)")

    @staticmethod
    def control1_state_events_running() -> bool:
        """Return whether event hooks are active."""
        return True

    @staticmethod
    def control1_state_emit_now() -> None:
        """Emit current control1 state through hook actions."""
        _emit_control1_state(actions.tracking.control1_enabled())


def _on_ready() -> None:
    _install_menu_hook()


app.register("ready", _on_ready)
