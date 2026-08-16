"""Load the repository-local PyWayland build without user dependencies."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

_CACHE_TAG = "cpython-313"
_MACHINE = "x86_64"
_MINIMUM_GLIBC = (2, 34)
_SITE = (
    Path(__file__).resolve().parents[2]
    / ".vendor"
    / "pywayland"
    / "cp313-cp313-linux_x86_64"
)


def activate() -> Path:
    """Put the verified PyWayland bundle first on the import path."""
    cache_tag = sys.implementation.cache_tag
    machine = platform.machine()
    system = platform.system()
    libc_name, libc_version = platform.libc_ver()
    try:
        glibc_version = tuple(map(int, libc_version.split(".")))
    except ValueError:
        glibc_version = ()
    if (
        cache_tag != _CACHE_TAG
        or machine != _MACHINE
        or system != "Linux"
        or libc_name != "glibc"
        or glibc_version < _MINIMUM_GLIBC
    ):
        raise RuntimeError(
            "The bundled PyWayland build requires CPython 3.13, Linux x86-64, "
            "and glibc 2.34 or newer; got "
            f"{cache_tag}, {system} {machine}, {libc_name} {libc_version}"
        )

    loaded = sys.modules.get("pywayland")
    if loaded is not None:
        origin = Path(loaded.__file__).resolve()
        if not origin.is_relative_to(_SITE):
            raise RuntimeError(f"PyWayland is already loaded from {origin}")

    if not _SITE.is_dir():
        raise RuntimeError(f"Bundled PyWayland site is missing: {_SITE}")
    site = str(_SITE)
    if site in sys.path:
        sys.path.remove(site)
    sys.path.insert(0, site)
    return _SITE
