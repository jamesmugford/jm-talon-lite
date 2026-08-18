# Talon Lite

A lightweight shim to forward Talon input to Wayland backends. 

This is a drop in config, that you can drop in alongside the community or any other custom config. 

This takes a progressive enhancement approach to adding features, keeping the core features compositor-agnostic
while allowing optional compositor-specific app layers.

Shared compositor actions such as `grow window` and `shrink window` reuse Talon
Community's i3 vocabulary where practical; app layers are not intended as full
i3 ports. Hyprland is simply the first optional implementation, not a preferred
or exclusive compositor. Additional integrations are expected under `apps/` as
the project and its maintainers move between desktop environments.

It is entirely event driven, so it will introduce virtually no latency.

Current features
===
* Layout-aware native keyboard input
* Eye tracking input: Control Mouse (Legacy) fully supported. (Includes custom "Hiss Mouse" mouse mode)
* Mouse button commands input. (Touch, Righty, Drag, Wheel Up etc) *Beta: Scrolling support* 
* Active Wayland application and window-title contexts
* Optional compositor voice-command app layers (currently Hyprland)

Who is this for
===
A tiling window manager/VIM user will feel right at home with this feature set.

It should, at the very least, also allow any Talon user to navigate freely Wayland environments on real hardware.

Please note
===
**This may not be the Talon you know and love**. If you are used to running Talon under a Linux X11, Mac or Windows
environment - this will be break a significant number of the features you are used to.

Current supported back ends
===
* In-process Wayland virtual keyboard
* In-process Wayland virtual pointer

Supported compositors
===
* Hyprland
* labwc
* Mir
* niri
* phoc
* river
* Sway
* Wayfire

The in-process runtime supports Talon's CPython 3.13 x86-64 build on Linux with
glibc 2.34 or newer and `libxkbcommon.so.0`. It starts automatically in Wayland
sessions and routes `actions.key()` through `zwp_virtual_keyboard_manager_v1`.
The runtime mirrors the selected seat's compositor-provided XKB keymap, so
letters and symbols follow that layout without a separate remapping table.
Talon key sequences, chords, `:down`, `:up`, and repeat suffixes are supported.
The virtual keyboard starts in keymap group 0 and follows later lock or layout
events when the compositor supplies them to the headless Talon connection.

The same runtime also exposes a virtual pointer for mouse, gaze, and hiss input.
It requires `zwlr_virtual_pointer_manager_v1`, clamps absolute coordinates to
the normalized desktop, and maps Talon buttons `0`, `1`, and `2` to left,
right, and middle.

Compositors that expose `zwlr_foreign_toplevel_manager_v1` also populate
Talon's `app.name` and `win.title` contexts from the active Wayland window.

## Instuctions

```sh
git clone https://github.com/jamesmugford/jmtalonlite $HOME/.talon/user/jmtalonlite
```

Pointer forwarding uses the in-process Wayland runtime and does not require a
separate input daemon.

> **Arch users:** Talon's Tobii udev rules use the `plugdev` group, which may not exist by default.
> If Talon detects your Tobii tracker but fails to open it with `EyeOpenErr: Eye Tracker open failed`,
> create the group and add your user to it:
>
> ```sh
> sudo groupadd -f plugdev
> sudo usermod -aG plugdev "$USER"
> ```
>
> Reboot afterward so your session and Talon inherit the new group membership, then reconnect the tracker.

## Dev tests

Run the unit and lightweight runtime tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

Rebuild the pinned PyWayland bundle and generated protocol bindings with:

```sh
python tools/build_pywayland_vendor.py
```

The build requires `~/.talon/bin/python`, GCC, binutils, Wayland development
headers, and network access. See `third_party/README.md` for source, patch, and
reconstruction details.


Physical keyboard input recipes
===
Niri: use F8 to toggle Talon's speech

```
F8 repeat=false allow-inhibiting=false hotkey-overlay-title="Talon Toggle Listen" {
    spawn-sh "printf 'from talon import actions; actions.speech.toggle()\\n' | \"$HOME/.talon/bin/repl\" >/dev/null";
}
```

Hyprland: add this to a loaded Lua config module to use F8 to toggle Talon's
speech. For example, Omarchy loads `~/.config/hypr/bindings.lua` from its main
Hyprland config.

```lua
hl.bind(
  "code:74",
  hl.dsp.exec_cmd(
    [[sh -c 'printf "%s\n" "from talon import actions; actions.speech.toggle()" | "$HOME/.talon/bin/repl" >/dev/null']]
  ),
  { description = "Talon toggle listen" }
)
```

Other projects
===
This project was inspired by: [Numen Voice](https://numenvoice.org/). It's open source, Wayland friendly and has a very friendly community
