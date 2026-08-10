# Global Talon Lite modifier grammar.
#
# Requires Talon Lite's existing <user.unmodified_key> capture.
#
# Examples:
#   walt left       -> super-alt-left
#   trash tab       -> ctrl-alt-shift-tab
#   squash space    -> ctrl-alt-shift-super-space
#
# Expanded combinations also work in either order:
#   win alt left
#   alt win left
#   troll shift tab

<user.talon_lite_modifiers> <user.unmodified_key>:
    user.talon_lite_key_chord("{talon_lite_modifiers}-{unmodified_key}")

crisp: user.talon_lite_key_chord("ctrl-space")

# Tap modifier keys without supplying another key.
press <user.talon_lite_modifiers>:
    user.talon_lite_key_chord(talon_lite_modifiers)
