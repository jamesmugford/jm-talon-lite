tag: user.wayland_mouse_forwarder
-
touch: mouse_click(0)

righty: mouse_click(1)

mid click: mouse_click(2)

<user.modifiers> touch:
    key("{modifiers}:down")
    mouse_click(0)
    key("{modifiers}:up")

<user.modifiers> righty:
    key("{modifiers}:down")
    mouse_click(1)
    key("{modifiers}:up")

(dub click | duke):
    mouse_click(0)
    mouse_click(0)

(trip click | trip lick):
    mouse_click(0)
    mouse_click(0)
    mouse_click(0)

left drag | drag | drag start: user.mouse_drag(0)

right drag | righty drag: user.mouse_drag(1)

end drag | drag end: user.mouse_drag_end()
