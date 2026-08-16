# Vendored Wayland Components

The hidden `.vendor/pywayland/cp313-cp313-linux_x86_64/` tree contains
PyWayland 0.4.19 for Talon's CPython 3.13 x86-64 runtime. It is based on
PyWayland commit `7f48c575076b3e620a6ba3565dc877d3a9e665ff` and uses the shared
libraries bundled in the official manylinux wheel.

The CFFI declaration is patched to expose `wl_display_cancel_read()`. The
extension is relinked to the wheel's private Wayland libraries with an
`$ORIGIN/../pywayland.libs` runtime search path. Talon's CFFI installation is
used rather than vendoring `_cffi_backend`.

Generated bindings use these pinned protocol definitions:

- `wayland.xml`, Wayland 1.26.0 commit
  `87cc8a8728a923fc57938faa81ba0e74f34ecdc7`
- `wlr-virtual-pointer-unstable-v1.xml`, wlr-protocols commit
  `c11408942e2fb54d41dadb84cdf844331076ae11`
- `virtual-keyboard-unstable-v1.xml`, wlroots commit
  `91ef4ce2081fec77d060ce2e9879535697e23b91`
- `wlr-foreign-toplevel-management-unstable-v1.xml`, wlr-protocols commit
  `005d69d048ccceb2af3f5b86665821e8fa9a87b8`

Only `wayland.py` and the three extension bindings are retained in the protocol
package. The stale build source, unrelated stock bindings, and upstream wheel
metadata are removed. The scanner remains because PyWayland's runtime argument
types import it. The removed metadata describes the unmodified wheel and would
be inaccurate for this patched derivative; `manifest.json` and `VENDOR.json`
are the authoritative provenance records instead.

Run `tools/build_pywayland_vendor.py` to reconstruct the bundle. The script
requires Talon's Python at `~/.talon/bin/python`, GCC, binutils, Wayland
development headers, and network access. Source artifacts and protocol inputs
are hash-pinned, and the resulting ELF dependencies, RPATH, and maximum glibc
symbol version are validated. The host compiler and headers are intentionally
not container-pinned, so reconstruction is not guaranteed to be bit-for-bit.
