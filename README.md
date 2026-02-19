# Talon Lite

A lightweight shim to forward Talon input to Wayland backends.

This is a drop in config, that you can drop in alongside the community or any other custom config.

This takes a progressive enhancement approach to adding features, minimally adding features that are possible to
add without writing compositor specific code.

Who is this for?
===
In it's current state, this is sufficient for the window manager uber nerds comfortable with:

* Tiling/scrolling WM
* Vim/Emacs key bindings all the things
* Use Keyboard friendly app selections.
* TUIs
* WIP: Optional eye tracking (for say design applications)


Please note
===
**This may not be the Talon you know and love**. If you are used to running Talon under a Linux X11, Mac or Windows
environment - it could be missing some features you are used to (example: application specific commands).


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

dotoold will need to be run in the background, which can be started with systemd.