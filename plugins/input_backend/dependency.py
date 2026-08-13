"""Load the pinned libevdev package from jm-talon-lite's private target."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
from pathlib import Path
import sys


PACKAGE_NAME = "libevdev"
PACKAGE_VERSION = "0.13.1"


class DependencyError(RuntimeError):
    pass


def dependency_target(environ=None) -> Path:
    """Return the explicit XDG dependency target used by setup/install."""
    if environ is None:
        environ = os.environ
    data_home = environ.get("XDG_DATA_HOME")
    if data_home:
        base = Path(data_home).expanduser()
        source = "XDG_DATA_HOME"
    else:
        home = environ.get("HOME")
        if not home:
            raise DependencyError(
                "HOME is not set and XDG_DATA_HOME was not provided."
            )
        base = Path(home).expanduser() / ".local" / "share"
        source = "HOME"
    if not base.is_absolute():
        raise DependencyError(f"{source} must resolve to an absolute path.")
    return base / "jm-talon-lite" / "python"


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _installed_version(target: Path) -> str:
    try:
        matches = [
            distribution
            for distribution in importlib.metadata.distributions(
                path=[str(target)]
            )
            if (distribution.metadata["Name"] or "").lower() == PACKAGE_NAME
        ]
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise DependencyError(
            f"Could not inspect the native dependency target: {target}"
        ) from exc
    if len(matches) != 1:
        raise DependencyError(
            f"Run setup/install: expected one {PACKAGE_NAME} distribution in {target}."
        )
    return matches[0].version


def load_libevdev(target: Path | None = None):
    """Import exactly libevdev 0.13.1 from the managed project target."""
    if target is None:
        target = dependency_target()
    if not target.is_dir() or target.is_symlink():
        raise DependencyError(f"Run setup/install: dependency target is missing: {target}")

    version = _installed_version(target)
    if version != PACKAGE_VERSION:
        raise DependencyError(
            f"Run setup/install: found {PACKAGE_NAME} {version}; expected {PACKAGE_VERSION}."
        )

    existing = sys.modules.get(PACKAGE_NAME)
    if existing is not None:
        origin = getattr(existing, "__file__", None)
        if not origin or not _within(Path(origin), target):
            raise DependencyError(
                "A libevdev module outside jm-talon-lite's managed target is already loaded."
            )
        return existing

    target_string = str(target)
    if target_string not in sys.path:
        sys.path.insert(0, target_string)
    try:
        module = importlib.import_module(PACKAGE_NAME)
    except Exception as exc:
        raise DependencyError(
            f"Could not import {PACKAGE_NAME} from {target}."
        ) from exc

    origin = getattr(module, "__file__", None)
    if not origin or not _within(Path(origin), target):
        sys.modules.pop(PACKAGE_NAME, None)
        raise DependencyError(
            f"Imported {PACKAGE_NAME} from outside the managed target."
        )
    return module
