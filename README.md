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
* Raw keyboard input
* Eye tracking input: Control Mouse (Legacy) fully supported. (Includes custom "Hiss Mouse" mouse mode)
* Mouse button commands input. (Touch, Righty, Drag, Wheel Up etc) *Beta: Scrolling support* 
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
* Dotool
* _More can be added (Ideas and pull requests are welcome)_


## Instuctions

```sh
git clone https://github.com/jamesmugford/jm-talon-lite $HOME/.talon/user/jm-talon-lite
```

Install Wayland compatible input backend:

* Currently supported: **Dotool:** https://git.sr.ht/~geb/dotool

dotoold will need to be run in the background, which can be started with e.g. systemd.

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

Run minimal pure-function tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```


Physical keyboard input recipes
===
Niri: use F8 to toggle Talon's speech

```
F8 repeat=false allow-inhibiting=false hotkey-overlay-title="Talon Toggle Listen" {
    spawn-sh "printf 'from talon import actions; actions.speech.toggle()\\n' | \"$HOME/.talon/bin/repl\" >/dev/null";
}
```

Hyprland: the current app layer targets the `hyprlang` config provider;
Lua-config sessions are not supported. Add this to
`~/.config/hypr/hyprland.conf` (or a sourced `.conf` file) to use F8 to toggle
Talon's speech.

```ini
bind = , F8, exec, sh -c 'printf "%s\n" "from talon import actions; actions.speech.toggle()" | "$HOME/.talon/bin/repl" >/dev/null'
```

Other projects
===
This project was inspired by: [Numen Voice](https://numenvoice.org/). It's open source, Wayland friendly and has a very friendly community
