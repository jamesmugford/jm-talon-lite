# Hyprland commands auto-enable when Talon starts under Hyprland.
# Shared resize forms mirror Talon Community's i3 vocabulary where practical.
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
(win | window) default: user.hyprland_toggle_split()
(win | window) split: user.hyprland_toggle_split()

reload (hyper land | hypr land) config: user.hyprland_reload()

(full screen | scuba): user.hyprland_fullscreen()
full width: user.hyprland_full_width()
toggle floating: user.hyprland_float()
center window: user.hyprland_center()

grow column: user.hyprland_resize_column(0.1)
shrink column: user.hyprland_resize_column(-0.1)
grow window: user.hyprland_resize_window(1)
shrink window: user.hyprland_resize_window(-1)

horizontal (shell | terminal):
    user.hyprland_preselect("right")
    user.hyprland_shell()

vertical (shell | terminal):
    user.hyprland_preselect("down")
    user.hyprland_shell()

(shuffle | move (win | window) [to] port) <number_small>:
    user.hyprland_move_to_workspace(number_small)
(shuffle | move (win | window) [to] last port):
    user.hyprland_move_to_workspace("previous")
(shuffle | move) flipper: user.hyprland_move_to_workspace("previous")
(shuffle | move (win | window) left): user.hyprland_swap("left")
(shuffle | move (win | window) right): user.hyprland_swap("right")
(shuffle | move (win | window) up): user.hyprland_swap("up")
(shuffle | move (win | window) down): user.hyprland_swap("down")

(win | window) horizontal: user.hyprland_preselect("right")
(win | window) vertical: user.hyprland_preselect("down")

make scratch: user.hyprland_move_to_scratchpad()
[(show | hide)] scratch: user.hyprland_show_scratchpad()

lock screen: user.hyprland_lock()

(launch shell | koopa): user.hyprland_shell()

new scratch (shell | window): user.hyprland_new_scratch_terminal()
