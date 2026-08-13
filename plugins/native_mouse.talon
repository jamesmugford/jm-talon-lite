os: linux
-
touch: mouse_click(0)
righty: mouse_click(1)
mid click: mouse_click(2)

<user.talon_lite_modifiers> touch:
    user.native_modified_click(talon_lite_modifiers, 0)
<user.talon_lite_modifiers> righty:
    user.native_modified_click(talon_lite_modifiers, 1)

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

wheel down: user.native_scroll(1)
wheel down here:
    user.mouse_move_center_active_window()
    user.native_scroll(1)
wheel tiny [down]: user.native_scroll(0.2)
wheel tiny [down] here:
    user.mouse_move_center_active_window()
    user.native_scroll(0.2)

wheel up: user.native_scroll(-1)
wheel up here:
    user.mouse_move_center_active_window()
    user.native_scroll(-1)
wheel tiny up: user.native_scroll(-0.2)
wheel tiny up here:
    user.mouse_move_center_active_window()
    user.native_scroll(-0.2)

wheel left: user.native_scroll(0, -1)
wheel left here:
    user.mouse_move_center_active_window()
    user.native_scroll(0, -1)
wheel tiny left: user.native_scroll(0, -0.5)
wheel tiny left here:
    user.mouse_move_center_active_window()
    user.native_scroll(0, -0.5)

wheel right: user.native_scroll(0, 1)
wheel right here:
    user.mouse_move_center_active_window()
    user.native_scroll(0, 1)
wheel tiny right: user.native_scroll(0, 0.5)
wheel tiny right here:
    user.mouse_move_center_active_window()
    user.native_scroll(0, 0.5)
