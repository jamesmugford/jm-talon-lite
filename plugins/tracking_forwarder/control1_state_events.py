"""Event-driven hooks for Control Mouse enabled-state transitions."""

from talon import Context, Module, actions, app
from talon.plugins import eye_mouse_2

ctx = Context()
mod = Module()


def _emit_control1_state(enabled: bool) -> None:
    """Publish one changed Control Mouse state through user hooks."""
    print(f"control1 enabled={enabled}")
    actions.user.control1_state_changed(enabled)
    if enabled:
        actions.user.control1_started()
        return
    actions.user.control1_stopped()


def _install_menu_hook() -> bool:
    """Wrap Talon's Control Mouse menu callback exactly once."""
    item = getattr(eye_mouse_2, "control1_item", None)
    if item is None:
        return False

    attrs = getattr(item, "attrs", None)
    if attrs is None:
        return False

    cb = attrs.get("cb")
    if cb is None:
        return False

    original = attrs.get("_control1_state_menu_original")
    if original is None and attrs.get("_control1_state_menu_wrapper", False):
        defaults = getattr(cb, "__defaults__", ())
        original = defaults[0] if defaults else cb
    elif original is None:
        original = cb

    def wrapped(menu_item, orig_cb=original):
        """Run Talon's callback and publish a resulting state change."""
        before = actions.tracking.control1_enabled()
        result = orig_cb(menu_item)
        after = actions.tracking.control1_enabled()
        if before == after:
            return result
        _emit_control1_state(after)
        return result

    attrs["cb"] = wrapped
    attrs["_control1_state_menu_wrapper"] = True
    attrs["_control1_state_menu_original"] = original
    return True


@ctx.action_class("tracking")
class TrackingActions:
    @staticmethod
    def control1_toggle(state=None) -> None:
        """Wrap control1 toggle and emit state hooks."""
        before = actions.tracking.control1_enabled()
        actions.next(state)
        after = actions.tracking.control1_enabled()
        if before == after:
            return
        _emit_control1_state(after)


@mod.action_class
class Actions:
    @staticmethod
    def control1_started() -> None:
        """Hook called when control1 mouse starts."""
        pass

    @staticmethod
    def control1_stopped() -> None:
        """Hook called when control1 mouse stops."""
        pass

    @staticmethod
    def control1_state_changed(enabled: bool) -> None:
        """Hook called when control1 state changes."""
        pass

    @staticmethod
    def control1_state_events_start() -> None:
        """Enable control1 state events (event-driven, no poll loop)."""
        hooked = _install_menu_hook()
        print(f"control1_state_events started mode=events hooked={hooked}")

    @staticmethod
    def control1_state_events_stop() -> None:
        """No-op: state events are always on once loaded."""
        print("control1_state_events stopped (no-op in event mode)")

    @staticmethod
    def control1_state_events_running() -> bool:
        """Return whether event hooks are active."""
        return True

    @staticmethod
    def control1_state_emit_now() -> None:
        """Emit current control1 state through hook actions."""
        _emit_control1_state(actions.tracking.control1_enabled())


def _on_ready() -> None:
    """Install the Control Mouse menu hook after Talon initialization."""
    _install_menu_hook()


app.register("ready", _on_ready)
