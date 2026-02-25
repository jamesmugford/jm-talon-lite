# Talon Lite

A lightweight shim to forward Talon input to Wayland backends. 

This is a drop in config, that you can drop in alongside the community or any other custom config. 

This takes a progressive enhancement approach to adding features, minimally adding features that are possible to
add without writing compositor specific code.

It is entirely event driven, so it will introduce virtually no latency.

Current features
===
* Raw keyboard input
* Eye tracking input: Control Mouse (Legacy) fully supported. (Includes custom "Hiss Mouse" mouse mode)
* Mouse button commands input. (Touch, Righty, Drag, Wheel Up etc) *Beta: Scrolling support* 

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

## Dev tests

Run minimal pure-function tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```


Physical keyboard input recipes
===
Niri: use F2 to toggle Talon's speech

```
F2 repeat=false allow-inhibiting=false hotkey-overlay-title="Talon Toggle Listen" {
    spawn-sh "printf 'from talon import actions; actions.speech.toggle()\\n' | \"$HOME/.talon/bin/repl\" >/dev/null";
}
```
