from talon import Context, Module, actions, app
from talon.plugins import eye_mouse_2

ctx = Context()
mod = Module()


def _emit_legacy_state(enabled: bool) -> None:
    print(f"eye_legacy enabled={enabled}")
    actions.user.eye_legacy_state_changed(enabled)
    if enabled:
        actions.user.eye_legacy_started()
        return
    actions.user.eye_legacy_stopped()


def _install_menu_hook() -> bool:
    item = getattr(eye_mouse_2, "control1_item", None)
    if item is None:
        return False

    attrs = getattr(item, "attrs", None)
    if attrs is None:
        return False

    if attrs.get("_eye_legacy_menu_wrapper", False):
        return True

    cb = attrs.get("cb")
    if cb is None:
        return False

    def wrapped(menu_item, orig_cb=cb):
        before = actions.tracking.control1_enabled()
        result = orig_cb(menu_item)
        after = actions.tracking.control1_enabled()
        if after != before:
            _emit_legacy_state(after)
        return result

    attrs["cb"] = wrapped
    attrs["_eye_legacy_menu_wrapper"] = True
    return True


@ctx.action_class("tracking")
class TrackingActions:
    @staticmethod
    def control1_toggle(state=None) -> None:
        """Wrap legacy control toggle and emit state hooks."""
        before = actions.tracking.control1_enabled()
        actions.next(state)
        after = actions.tracking.control1_enabled()
        if after == before:
            return
        _emit_legacy_state(after)


@mod.action_class
class Actions:
    @staticmethod
    def eye_legacy_started() -> None:
        """Hook called when legacy control mouse starts."""
        _ = 0

    @staticmethod
    def eye_legacy_stopped() -> None:
        """Hook called when legacy control mouse stops."""
        _ = 0

    @staticmethod
    def eye_legacy_state_changed(enabled: bool) -> None:
        """Hook called when legacy control mouse state changes."""
        _ = enabled

    @staticmethod
    def eye_legacy_state_watch_start(interval: str = "100ms") -> None:
        """Enable legacy control mouse events (event-driven, no polling)."""
        hooked = _install_menu_hook()
        print(
            f"eye_legacy state watcher started mode=events "
            f"hooked={hooked}"
        )

    @staticmethod
    def eye_legacy_state_watch_stop() -> None:
        """No-op: event watcher is always on once loaded."""
        print("eye_legacy state watcher stopped (no-op in event mode)")

    @staticmethod
    def eye_legacy_state_watch_running() -> bool:
        """Return whether event hooks are active."""
        return True

    @staticmethod
    def eye_legacy_state_emit_now() -> None:
        """Emit current legacy control mouse state through hook actions."""
        _emit_legacy_state(actions.tracking.control1_enabled())


def _on_ready() -> None:
    _install_menu_hook()


app.register("ready", _on_ready)
