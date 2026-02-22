from talon import Context, Module, actions, app, tracking_system, ui
from talon.canvas import Canvas
from talon.plugins import eye_mouse

ctx = Context()
mod = Module()

_overlay_enabled = False
_gaze_registered = False
_dot_pos = None
_canvas_entries = []


def _contains(rect, x: float, y: float) -> bool:
    return rect.x <= x <= rect.x + rect.width and rect.y <= y <= rect.y + rect.height


def _make_draw(rect):
    def _draw(c):
        if _dot_pos is None:
            return

        x, y = _dot_pos
        if not _contains(rect, x, y):
            return

        lx = x - rect.x
        ly = y - rect.y

        c.paint.style = c.paint.Style.STROKE
        c.paint.color = "00ff00cc"
        c.paint.stroke_width = 2
        c.draw_circle(lx, ly, 18)

        c.paint.style = c.paint.Style.FILL
        c.paint.color = "00ff00ff"
        c.draw_circle(lx, ly, 4)

    return _draw


def _close_canvases() -> None:
    global _canvas_entries
    for canvas, draw_cb in _canvas_entries:
        canvas.unregister("draw", draw_cb)
        canvas.close()
    _canvas_entries = []


def _create_canvases() -> None:
    global _canvas_entries
    _close_canvases()

    entries = []
    for screen in ui.screens():
        draw_cb = _make_draw(screen.rect)
        canvas = Canvas.from_screen(screen)
        canvas.register("draw", draw_cb)
        entries.append((canvas, draw_cb))

    _canvas_entries = entries


def _register_gaze() -> None:
    global _gaze_registered
    if _gaze_registered:
        return
    tracking_system.register("gaze", _on_gaze)
    _gaze_registered = True


def _clear_overlay() -> None:
    global _dot_pos
    _dot_pos = None
    for canvas, _draw_cb in _canvas_entries:
        canvas.freeze()


def _unregister_gaze() -> None:
    global _gaze_registered
    if not _gaze_registered:
        return
    tracking_system.unregister("gaze", _on_gaze)
    _gaze_registered = False


def _sync_overlay() -> None:
    if not _overlay_enabled:
        _unregister_gaze()
        _clear_overlay()
        return

    if not actions.tracking.control1_enabled():
        _unregister_gaze()
        _clear_overlay()
        return

    _register_gaze()


def _on_gaze(*_args) -> None:
    global _dot_pos
    if not _overlay_enabled:
        return

    if not actions.tracking.control1_enabled():
        return

    hist = eye_mouse.mouse.xy_hist
    if not hist:
        return

    point = hist[-1]
    _dot_pos = (point.x, point.y)

    for canvas, _draw_cb in _canvas_entries:
        canvas.freeze()


def _on_screen_change(_screens) -> None:
    if not _overlay_enabled:
        return
    _create_canvases()


@ctx.action_class("user")
class UserActions:
    @staticmethod
    def eye_legacy_started() -> None:
        actions.next()
        _sync_overlay()

    @staticmethod
    def eye_legacy_stopped() -> None:
        actions.next()
        _sync_overlay()


@mod.action_class
class Actions:
    @staticmethod
    def control1_debug_overlay_start() -> None:
        """Start control1 debug overlay."""
        global _overlay_enabled
        if _overlay_enabled:
            print("control1 debug overlay already running")
            return
        _overlay_enabled = True
        _create_canvases()
        _sync_overlay()
        print("control1 debug overlay started")

    @staticmethod
    def control1_debug_overlay_stop() -> None:
        """Stop control1 debug overlay."""
        global _overlay_enabled
        if not _overlay_enabled:
            print("control1 debug overlay stopped")
            return
        _overlay_enabled = False
        _unregister_gaze()
        _close_canvases()
        print("control1 debug overlay stopped")

    @staticmethod
    def control1_debug_overlay_toggle(state=None) -> None:
        """Toggle control1 debug overlay."""
        target = (not _overlay_enabled) if state is None else state
        if target:
            actions.user.control1_debug_overlay_start()
            return
        actions.user.control1_debug_overlay_stop()

    @staticmethod
    def control1_debug_overlay_running() -> bool:
        """Return whether control1 debug overlay is enabled."""
        return _overlay_enabled


def _on_ready() -> None:
    ui.register("screen_change", _on_screen_change)


app.register("ready", _on_ready)
