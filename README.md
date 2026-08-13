# Talon Lite

A lightweight Talon configuration that sends Linux input through `uinput`.

This is a drop in config, that you can drop in alongside the community or any other custom config. 

This takes a progressive enhancement approach to adding features, keeping the core features compositor-agnostic
while allowing optional compositor-specific app layers.

Shared compositor actions such as `grow window` and `shrink window` reuse Talon
Community's i3 vocabulary where practical; app layers are not intended as full
i3 ports. Hyprland is simply the first optional implementation, not a preferred
or exclusive compositor. Additional integrations are expected under `apps/` as
the project and its maintainers move between desktop environments.

The input backend is entirely event driven and compositor agnostic. Talon's
parsed key and pointer actions map directly to Linux input events in-process;
there is no helper daemon or compositor-specific input path.

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

Input backend
===
* Native Linux `uinput`


## Instructions

```sh
git clone https://github.com/jamesmugford/jm-talon-lite $HOME/.talon/user/jm-talon-lite
```

### Input setup

The input backend requires these system prerequisites. The setup scripts check
them but deliberately do not run a distribution package manager:

* `libevdev.so.2`
* `libxkbcommon.so.0`
* `/dev/uinput`, udev, and an active local login session for seat-based access
* A host Python 3.9 or newer with `pip`, used only by the explicit installer
* `setfacl`, used by uninstall to revoke the managed active-seat ACL

Run the installer as your regular desktop user, not with `sudo`:

```sh
cd "$HOME/.talon/user/jm-talon-lite"
./setup/install
```

This installs the hash-locked `libevdev==0.13.1` wheel into the project-specific
target `$XDG_DATA_HOME/jm-talon-lite/python/`, or
`$HOME/.local/share/jm-talon-lite/python/` when `XDG_DATA_HOME` is unset. It is
not a virtual environment, does not use Talon's shared environment, and is
never installed automatically during Talon startup. Talon uses Python 3.11 or
newer, so this target does not include the older-Python-only
`typing_extensions` dependency. The input backend loads this explicit target;
do not add it globally to `PYTHONPATH`.

Set one explicit XKB layout in the environment that launches Talon. The variant
is optional but requires a layout. Comma-separated layouts and runtime layout
switching are not supported yet:

```sh
export XKB_DEFAULT_LAYOUT=us
# export XKB_DEFAULT_VARIANT=intl
```

Reload Talon after installation, then check the complete setup:

```sh
./setup/doctor
```

If these variables are not already present in Talon's launch environment,
restart Talon from that environment rather than using only a config reload.

`doctor` is read-only. It reports `PASS`, `WARN`, and `FAIL` checks for the
managed Python target and import origin, exact native-library SONAMEs and key
symbols, effective `/dev/uinput` access, the installed udev rule, the active
local session, and conflicting broad `uinput` rules. A `FAIL` makes it
exit nonzero; warnings do not.

Remove only this setup's managed resources with:

```sh
./setup/uninstall
```

The installer asks for `sudo` only to install
`/etc/udev/rules.d/72-jm-talon-lite-uinput.rules`, reload udev rules, and issue
a targeted change trigger for the existing `uinput` device. The rule grants
`uaccess` to the active seat; it does not use the `input` group or world-write
permissions. The scripts do not change Talon settings, install system packages,
or start or stop Talon.

Uninstall removes the dependency target only when its constrained ownership
state still matches, and removes the udev rule only when setup recorded it as
owned and its content and metadata are unchanged. Locally modified or unowned
resources are preserved with a warning. Because access to `uinput` permits
synthetic keyboard and pointer input, investigate any broad `MODE=0666` or
`GROUP=input` rule reported by `doctor`.

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

Run the unit and system-library integration tests:

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
