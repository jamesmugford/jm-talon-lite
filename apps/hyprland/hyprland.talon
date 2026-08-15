# Hyprland commands auto-enable when Talon starts under Hyprland.
# Spoken forms mirror Talon Community's i3 vocabulary where Hyprland has an equivalent.
os: linux
tag: user.hyprland
-
port <number_small>: user.hyprland_switch_to_workspace(number_small)
(port flip | flipper): user.hyprland_switch_to_workspace("previous")
port right: user.hyprland_switch_to_workspace("e+1")
port left: user.hyprland_switch_to_workspace("e-1")

(win | window) left: user.hyprland_focus("left")
(win | window) right: user.hyprland_focus("right")
(win | window) up: user.hyprland_focus("up")
(win | window) down: user.hyprland_focus("down")
(win | window) kill: app.window_close()

reload (hyper land | hypr land) config: user.hyprland_reload()

(full screen | scuba): user.hyprland_fullscreen()
toggle floating: user.hyprland_float()
focus floating: user.hyprland_focus_mode_toggle()
center window: user.hyprland_center()

grow window: user.hyprland_resize_window(1)
shrink window: user.hyprland_resize_window(-1)

(shuffle | move (win | window) [to] port) <number_small>:
    user.hyprland_move_to_workspace(number_small)
(shuffle | move (win | window) [to] last port):
    user.hyprland_move_to_workspace("previous")
(shuffle | move) flipper: user.hyprland_move_to_workspace("previous")
(shuffle | move (win | window) left): user.hyprland_move("left")
(shuffle | move (win | window) right): user.hyprland_move("right")
(shuffle | move (win | window) up): user.hyprland_move("up")
(shuffle | move (win | window) down): user.hyprland_move("down")

make scratch: user.hyprland_move_to_scratchpad()
[(show | hide)] scratch: user.hyprland_show_scratchpad()
