#!/usr/bin/env python3
"""Explicit, reversible setup for jm-talon-lite's native Linux backend."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Dict, Iterable, List, Optional, Set, Tuple


PROJECT = "jm-talon-lite"
PACKAGE = "libevdev"
PACKAGE_VERSION = "0.13.1"
STATE_NAME = ".jm-talon-lite-state.json"
STATE_FORMAT = 1
STATE_MAX_BYTES = 1024 * 1024
RULE_NAME = "72-jm-talon-lite-uinput.rules"
RULE_DEST = Path("/etc/udev/rules.d") / RULE_NAME
RULE_MODE = 0o644
REQUIREMENTS_NAME = "requirements.txt"
SETUP_DIR = Path(__file__).resolve().parent
RULE_SOURCE = SETUP_DIR / RULE_NAME
REQUIREMENTS = SETUP_DIR / REQUIREMENTS_NAME

LIBRARIES = {
    "libevdev.so.2": (
        "libevdev_new",
        "libevdev_uinput_create_from_device",
        "libevdev_uinput_write_event",
    ),
    "libxkbcommon.so.0": (
        "xkb_context_new",
        "xkb_keymap_new_from_names",
        "xkb_keysym_get_name",
        "xkb_utf32_to_keysym",
    ),
}

_RENAME_EXCHANGE = 2
_AT_FDCWD = -100


class SetupError(RuntimeError):
    pass


def _effective_uid() -> int:
    return os.geteuid()


def _target_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        base = Path(data_home).expanduser()
        source = "XDG_DATA_HOME"
    else:
        home = os.environ.get("HOME")
        if not home:
            raise SetupError("HOME is not set and XDG_DATA_HOME was not provided.")
        base = Path(home).expanduser() / ".local" / "share"
        source = "HOME"
    if not base.is_absolute():
        raise SetupError(f"{source} must resolve to an absolute path.")
    return base / PROJECT / "python"


def _require_host_python() -> None:
    if sys.version_info < (3, 9):
        raise SetupError(
            f"host installer Python 3.9 or newer is required; found {sys.version.split()[0]}."
        )


def _reject_root_install() -> None:
    if os.geteuid() == 0 or os.environ.get("SUDO_USER"):
        raise SetupError(
            "do not run setup/install as root or through sudo; it requests sudo only for udev work."
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_manifest(
    root: Path,
) -> Tuple[Dict[str, str], List[str], Dict[str, int]]:
    try:
        root_status = root.lstat()
    except FileNotFoundError as exc:
        raise SetupError(f"dependency target does not exist: {root}") from exc
    if not stat.S_ISDIR(root_status.st_mode) or root.is_symlink():
        raise SetupError(f"dependency target is not a real directory: {root}")
    if root_status.st_uid != _effective_uid():
        raise SetupError(f"dependency target is not owned by the current user: {root}")

    files: Dict[str, str] = {}
    directories: List[str] = []
    modes = {".": stat.S_IMODE(root_status.st_mode)}
    for path in sorted(root.rglob("*")):
        status = path.lstat()
        relative = path.relative_to(root).as_posix()
        if stat.S_ISLNK(status.st_mode):
            raise SetupError(f"refusing unexpected symlink in dependency target: {path}")
        if status.st_uid != _effective_uid():
            raise SetupError(f"dependency target entry is not owned by the current user: {path}")
        if stat.S_ISDIR(status.st_mode):
            directories.append(relative)
            modes[relative] = stat.S_IMODE(status.st_mode)
        elif stat.S_ISREG(status.st_mode):
            if relative != STATE_NAME:
                files[relative] = _sha256(path)
                modes[relative] = stat.S_IMODE(status.st_mode)
        else:
            raise SetupError(f"refusing special file in dependency target: {path}")
    return files, directories, modes


def _ensure_owned_directory(path: Path, description: str) -> None:
    if not path.is_absolute():
        raise SetupError(f"{description} must be absolute: {path}")
    current = Path(path.anchor)
    deepest_existing = current
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise SetupError(f"unsafe symlink in {description}: {current}")
        if not current.exists():
            break
        status = current.lstat()
        if not stat.S_ISDIR(status.st_mode):
            raise SetupError(f"unsafe {description}: {current}")
        deepest_existing = current
    if deepest_existing.lstat().st_uid != _effective_uid():
        raise SetupError(
            f"nearest existing {description} is not user-owned: {deepest_existing}"
        )


def _valid_manifest_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and value != "."
        and not path.is_absolute()
        and path.as_posix() == value
        and all(part not in ("", ".", "..") for part in path.parts)
    )


def _load_state(target: Path) -> Optional[Dict[str, object]]:
    state_path = target / STATE_NAME
    try:
        status = state_path.lstat()
    except FileNotFoundError:
        return None
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != _effective_uid()
        or stat.S_IMODE(status.st_mode) != 0o600
        or status.st_size > STATE_MAX_BYTES
    ):
        raise SetupError(f"unsafe setup state file: {state_path}")
    raw = state_path.read_bytes()
    try:
        state = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SetupError(f"invalid setup state file: {state_path}") from exc
    expected_keys = {
        "format",
        "project",
        "target",
        "package",
        "version",
        "files",
        "directories",
        "modes",
        "rule_path",
        "rule_sha256",
        "rule_owned",
    }
    if not isinstance(state, dict) or set(state) != expected_keys:
        raise SetupError(f"unrecognized setup state fields in {state_path}")
    files = state.get("files")
    directories = state.get("directories")
    modes = state.get("modes")
    if (
        state.get("format") != STATE_FORMAT
        or state.get("project") != PROJECT
        or state.get("target") != str(target)
        or state.get("package") != PACKAGE
        or not isinstance(state.get("version"), str)
        or re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}", state["version"])
        is None
        or not isinstance(files, dict)
        or not all(
            isinstance(key, str)
            and _valid_manifest_path(key)
            and isinstance(value, str)
            and re.fullmatch(r"[0-9a-f]{64}", value)
            for key, value in files.items()
        )
        or not isinstance(directories, list)
        or not all(isinstance(item, str) and _valid_manifest_path(item) for item in directories)
        or len(set(directories)) != len(directories)
        or not isinstance(modes, dict)
        or set(modes) != {".", *files, *directories}
        or not all(
            isinstance(key, str)
            and (key == "." or _valid_manifest_path(key))
            and isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 0o7777
            for key, value in modes.items()
        )
        or state.get("rule_path") != str(RULE_DEST)
        or not isinstance(state.get("rule_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", state["rule_sha256"]) is None
        or not isinstance(state.get("rule_owned"), bool)
    ):
        raise SetupError(f"unrecognized setup state in {state_path}")
    return state


def _assert_unmodified_target(target: Path, state: Dict[str, object]) -> None:
    expected_files = state["files"]
    expected_directories = state["directories"]
    expected_modes = state["modes"]
    assert isinstance(expected_files, dict)
    assert isinstance(expected_directories, list)
    assert isinstance(expected_modes, dict)
    actual_files, actual_directories, actual_modes = _tree_manifest(target)
    if (
        actual_files != expected_files
        or actual_directories != expected_directories
        or actual_modes != expected_modes
    ):
        raise SetupError(
            f"dependency target differs from its setup manifest; preserving it: {target}"
        )


def _write_state(
    stage: Path,
    *,
    managed_target: Path,
    rule_owned: bool,
) -> None:
    files, directories, modes = _tree_manifest(stage)
    state = {
        "format": STATE_FORMAT,
        "project": PROJECT,
        "target": str(managed_target),
        "package": PACKAGE,
        "version": PACKAGE_VERSION,
        "files": files,
        "directories": directories,
        "modes": modes,
        "rule_path": str(RULE_DEST),
        "rule_sha256": _sha256(RULE_SOURCE),
        "rule_owned": rule_owned,
    }
    state_path = stage / STATE_NAME
    payload = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("ascii")
    if len(payload) > STATE_MAX_BYTES:
        raise SetupError("dependency target is too large for the constrained setup state.")
    state_path.write_bytes(payload)
    state_path.chmod(0o600)


def _validate_stage(stage: Path) -> None:
    matches = [
        distribution
        for distribution in importlib.metadata.distributions(path=[str(stage)])
        if (distribution.metadata["Name"] or "").lower() == PACKAGE
    ]
    if len(matches) != 1 or matches[0].version != PACKAGE_VERSION:
        raise SetupError(f"staged package is not {PACKAGE} {PACKAGE_VERSION}.")
    spec = importlib.machinery.PathFinder.find_spec(PACKAGE, [str(stage)])
    if spec is None or spec.loader is None:
        raise SetupError("could not inspect staged libevdev package.")
    if not spec.origin or not _within(Path(spec.origin), stage):
        raise SetupError("staged libevdev resolves outside its dependency target.")


def _lock_installed_directories(root: Path) -> None:
    """Prevent imports from adding bytecode outside the ownership manifest."""
    _tree_manifest(root)
    for path in root.rglob("*"):
        status = path.lstat()
        if stat.S_ISDIR(status.st_mode):
            path.chmod(stat.S_IMODE(status.st_mode) & ~0o222)


def _remove_owned_tree(root: Path) -> None:
    for path in root.rglob("*"):
        status = path.lstat()
        if stat.S_ISDIR(status.st_mode):
            path.chmod(stat.S_IMODE(status.st_mode) | 0o700)
    root.chmod(stat.S_IMODE(root.lstat().st_mode) | 0o700)
    shutil.rmtree(root)


def _run(command: List[str]) -> None:
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        raise SetupError(f"required command is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise SetupError(f"command failed with status {exc.returncode}: {' '.join(command)}") from exc


def _check_libraries(*, quiet: bool = False) -> None:
    errors: List[str] = []
    for soname, symbols in LIBRARIES.items():
        try:
            library = ctypes.CDLL(soname)
            missing = [symbol for symbol in symbols if not hasattr(library, symbol)]
        except OSError as exc:
            errors.append(f"{soname} could not be loaded: {exc}")
            continue
        if missing:
            errors.append(f"{soname} lacks required symbols: {', '.join(missing)}")
    if errors:
        raise SetupError("system prerequisites failed: " + "; ".join(errors))
    if not quiet:
        print("System library prerequisites are available.")


def _pip_install(stage: Path) -> None:
    if importlib.util.find_spec("pip") is None:
        raise SetupError(
            f"pip is unavailable for {sys.executable}; install pip for the host Python first."
        )
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-compile",
        "--no-deps",
        "--only-binary=:all:",
        "--require-hashes",
        "--target",
        str(stage),
        "--requirement",
        str(REQUIREMENTS),
    ]
    _run(command)


def _rename_exchange(first: Path, second: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise SetupError("atomic replacement requires renameat2 support on this Linux system.")
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(first),
        _AT_FDCWD,
        os.fsencode(second),
        _RENAME_EXCHANGE,
    )
    if result != 0:
        error = ctypes.get_errno()
        if error in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
            raise SetupError(
                "atomic replacement is not supported by this kernel/filesystem; "
                "the existing managed target was left unchanged."
            )
        raise SetupError(f"could not atomically replace {second}: {os.strerror(error)}")


def _existing_target_state(target: Path) -> Optional[Dict[str, object]]:
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise SetupError(f"refusing to replace non-directory dependency target: {target}")
        state = _load_state(target)
        if state is None:
            raise SetupError(f"refusing to replace unmarked dependency target: {target}")
        _assert_unmodified_target(target, state)
        return state
    return None


def _activate_stage(stage: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        _existing_target_state(target)
        _rename_exchange(stage, target)
        _remove_owned_tree(stage)
    else:
        os.rename(stage, target)


def _rule_matches(expected_hash: str) -> bool:
    try:
        status = RULE_DEST.lstat()
        return (
            stat.S_ISREG(status.st_mode)
            and status.st_uid == 0
            and status.st_gid == 0
            and stat.S_IMODE(status.st_mode) == RULE_MODE
            and _sha256(RULE_DEST) == expected_hash
        )
    except OSError:
        return False


def _rule_is_expected_file() -> bool:
    return _rule_matches(_sha256(RULE_SOURCE))


def _planned_rule_ownership(
    previous_state: Optional[Dict[str, object]],
) -> bool:
    if RULE_DEST.exists() or RULE_DEST.is_symlink():
        if not _rule_is_expected_file():
            raise SetupError(f"existing udev rule differs from the managed rule; preserving it: {RULE_DEST}")
        return bool(previous_state and previous_state["rule_owned"])
    return False


def _copy_rule_if_needed() -> bool:
    expected_hash = _sha256(RULE_SOURCE)
    if RULE_DEST.exists() or RULE_DEST.is_symlink():
        if not _rule_is_expected_file() or _sha256(RULE_DEST) != expected_hash:
            raise SetupError(f"existing udev rule has different content; preserving it: {RULE_DEST}")
        return False
    _run(
        [
            "sudo",
            "install",
            "-o",
            "root",
            "-g",
            "root",
            "-m",
            "0644",
            str(RULE_SOURCE),
            str(RULE_DEST),
        ]
    )
    if not _rule_is_expected_file():
        raise SetupError(f"installed udev rule failed validation: {RULE_DEST}")
    return True


def _reload_uinput_rule() -> None:
    _run(["sudo", "udevadm", "control", "--reload-rules"])
    _run(
        [
            "sudo",
            "udevadm",
            "trigger",
            "--action=change",
            "--subsystem-match=misc",
            "--sysname-match=uinput",
        ]
    )


def _record_rule_ownership(target: Path) -> None:
    state = _load_state(target)
    if state is None:
        raise SetupError(f"managed target lost its setup state: {target}")
    _assert_unmodified_target(target, state)
    state["rule_owned"] = True
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".python-state-",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        payload = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("ascii")
        if len(payload) > STATE_MAX_BYTES:
            raise SetupError("setup state is too large to update safely.")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target / STATE_NAME)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _remove_new_rule_after_failed_state_update() -> None:
    try:
        _sudo_remove_rule()
    except SetupError as exc:
        raise SetupError(
            f"udev rule was installed but ownership state could not be recorded; "
            f"automatic rollback also failed: {exc}"
        ) from exc


def install() -> int:
    _reject_root_install()
    _check_libraries()
    target = _target_path()
    parent = target.parent
    _ensure_owned_directory(parent, "dependency target parent")
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        raise SetupError(
            f"could not create dependency target parent {parent}: {exc}"
        ) from exc
    _ensure_owned_directory(parent, "dependency target parent")
    if parent.stat().st_uid != _effective_uid():
        raise SetupError(f"dependency target parent is not owned by the current user: {parent}")
    previous_state = _existing_target_state(target)
    rule_owned = _planned_rule_ownership(previous_state)

    stage = Path(tempfile.mkdtemp(prefix=".python-stage-", dir=parent))
    try:
        _pip_install(stage)
        _validate_stage(stage)
        _lock_installed_directories(stage)
        _write_state(
            stage,
            managed_target=target,
            rule_owned=rule_owned,
        )
        _activate_stage(stage, target)
    finally:
        if stage.exists():
            _remove_owned_tree(stage)

    print(f"Installed {PACKAGE} {PACKAGE_VERSION} into {target}")
    copied_rule = _copy_rule_if_needed()
    if copied_rule and not rule_owned:
        try:
            _record_rule_ownership(target)
        except Exception:
            _remove_new_rule_after_failed_state_update()
            raise
    _reload_uinput_rule()
    print(f"Installed udev rule: {RULE_DEST}")
    print("Reload Talon, then run setup/doctor.")
    return 0


def _sudo_remove_rule() -> None:
    setfacl = shutil.which("setfacl")
    if setfacl is None:
        raise SetupError(
            "setfacl is required to revoke the active-seat ACL during uninstall."
        )
    _run(["sudo", "rm", "-f", "--", str(RULE_DEST)])
    if RULE_DEST.exists() or RULE_DEST.is_symlink():
        raise SetupError(f"udev rule still exists after removal: {RULE_DEST}")
    _run(["sudo", "udevadm", "control", "--reload-rules"])
    _run(
        [
            "sudo",
            "udevadm",
            "trigger",
            "--action=change",
            "--subsystem-match=misc",
            "--sysname-match=uinput",
        ]
    )
    _run(
        [
            "sudo",
            setfacl,
            "-x",
            f"u:{os.geteuid()}",
            "--",
            "/dev/uinput",
        ]
    )


def uninstall() -> int:
    if os.geteuid() == 0 or os.environ.get("SUDO_USER"):
        raise SetupError(
            "do not run setup/uninstall as root or through sudo; it requests sudo only for udev work."
        )
    target = _target_path()
    _ensure_owned_directory(target.parent, "dependency target parent")
    state: Optional[Dict[str, object]] = None
    target_unmodified = False
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise SetupError(f"refusing to remove non-directory dependency target: {target}")
        state = _load_state(target)
        if state is None:
            raise SetupError(f"refusing to remove unmarked dependency target: {target}")
        try:
            _assert_unmodified_target(target, state)
        except SetupError as exc:
            print(f"WARN: {exc}")
        else:
            target_unmodified = True

    rule_exists = RULE_DEST.exists() or RULE_DEST.is_symlink()
    rule_status = "untracked" if rule_exists else "absent"
    if state is not None and state["rule_owned"] and not rule_exists:
        rule_status = "absent"
    elif state is not None and state["rule_owned"]:
        if RULE_DEST.is_symlink() or not RULE_DEST.is_file():
            rule_status = "modified"
        else:
            expected_hash = state["rule_sha256"]
            assert isinstance(expected_hash, str)
            if (
                _rule_matches(expected_hash)
            ):
                rule_status = "owned"
            else:
                rule_status = "modified"

    rule_tracked = bool(state and state["rule_owned"])
    if rule_status == "owned":
        _sudo_remove_rule()
        print(f"Removed unchanged owned udev rule: {RULE_DEST}")
    elif rule_status == "modified":
        print(f"WARN: preserving locally modified udev rule: {RULE_DEST}")
    elif rule_status == "absent" and rule_tracked:
        _sudo_remove_rule()
        print(f"Owned udev rule was already absent; reloaded udev rules: {RULE_DEST}")
    elif rule_status == "absent":
        print(f"Udev rule already absent: {RULE_DEST}")
    else:
        print(f"Udev rule is not tracked as setup-owned; preserving it: {RULE_DEST}")

    if target_unmodified:
        _remove_owned_tree(target)
        print(f"Removed owned dependency target: {target}")
    elif state is not None:
        print(f"Preserved locally modified dependency target: {target}")
    else:
        print(f"Dependency target already absent: {target}")
    return 0


class Doctor:
    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0

    def pass_(self, message: str) -> None:
        print(f"PASS: {message}")

    def warn(self, message: str) -> None:
        self.warnings += 1
        print(f"WARN: {message}")

    def fail(self, message: str) -> None:
        self.failures += 1
        print(f"FAIL: {message}")

    def exit_code(self) -> int:
        return 1 if self.failures else 0


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _doctor_target(report: Doctor, target: Path) -> None:
    try:
        valid_target = target.is_dir() and not target.is_symlink()
    except OSError as exc:
        report.fail(f"cannot inspect managed Python dependency target {target}: {exc}")
        return
    if not valid_target:
        report.fail(f"managed Python dependency target is not installed: {target}")
        return
    try:
        state = _load_state(target)
    except (OSError, SetupError) as exc:
        report.fail(str(exc))
        return
    if state is None:
        report.fail(f"managed Python dependency target is not installed: {target}")
        return
    try:
        _assert_unmodified_target(target, state)
    except (OSError, SetupError) as exc:
        report.fail(str(exc))
    else:
        report.pass_(f"managed target and state manifest are unchanged: {target}")

    try:
        distributions = list(importlib.metadata.distributions(path=[str(target)]))
        matches = [
            item
            for item in distributions
            if (item.metadata["Name"] or "").lower() == PACKAGE
        ]
    except (KeyError, OSError, TypeError, ValueError) as exc:
        report.fail(f"could not inspect target package metadata: {exc}")
        matches = []
    if len(matches) != 1 or matches[0].version != PACKAGE_VERSION:
        versions = ", ".join(item.version for item in matches) or "none"
        report.fail(f"target {PACKAGE} version is {versions}; expected {PACKAGE_VERSION}")
    else:
        report.pass_(f"target contains {PACKAGE} {PACKAGE_VERSION}")

    try:
        spec = importlib.machinery.PathFinder.find_spec(PACKAGE, [str(target)])
    except (ImportError, OSError, ValueError) as exc:
        report.fail(f"could not resolve {PACKAGE} import from the managed target: {exc}")
        return
    if spec is None or spec.loader is None:
        report.fail(f"could not resolve {PACKAGE} import from the managed target")
    elif not spec.origin or not _within(Path(spec.origin), target):
        report.fail(f"could not resolve {PACKAGE} import from the managed target")
    else:
        report.pass_(f"{PACKAGE} import origin is {spec.origin}")


def _doctor_libraries(report: Doctor) -> None:
    for soname, symbols in LIBRARIES.items():
        try:
            library = ctypes.CDLL(soname)
        except OSError as exc:
            report.fail(f"cannot load exact SONAME {soname}: {exc}")
            continue
        missing = [symbol for symbol in symbols if not hasattr(library, symbol)]
        if missing:
            report.fail(f"{soname} lacks required symbols: {', '.join(missing)}")
        else:
            report.pass_(f"loaded exact SONAME {soname} with required symbols")


def _doctor_uinput(report: Doctor) -> None:
    path = Path("/dev/uinput")
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        report.fail("/dev/uinput does not exist")
        return
    except OSError as exc:
        report.fail(f"cannot inspect /dev/uinput: {exc}")
        return
    if not stat.S_ISCHR(mode):
        report.fail("/dev/uinput is not a character device")
        return
    report.pass_("/dev/uinput is a character device")
    try:
        writable = os.access(path, os.W_OK, effective_ids=True)
    except (NotImplementedError, TypeError):
        writable = os.access(path, os.W_OK)
    if writable:
        report.pass_("current effective credentials can write /dev/uinput")
    else:
        report.fail("current effective credentials cannot write /dev/uinput")


def _doctor_rule(report: Doctor) -> None:
    try:
        expected = RULE_SOURCE.read_bytes()
    except OSError as exc:
        report.fail(f"cannot read project udev rule {RULE_SOURCE}: {exc}")
        return
    try:
        status = RULE_DEST.lstat()
        actual = RULE_DEST.read_bytes()
    except FileNotFoundError:
        report.fail(f"udev rule is not installed: {RULE_DEST}")
        return
    except OSError as exc:
        report.fail(f"cannot read udev rule {RULE_DEST}: {exc}")
        return
    if not stat.S_ISREG(status.st_mode) or RULE_DEST.is_symlink():
        report.fail(f"udev rule is not a regular file: {RULE_DEST}")
    elif actual != expected:
        report.fail(f"udev rule content differs from the project source: {RULE_DEST}")
    elif status.st_uid != 0 or status.st_gid != 0 or stat.S_IMODE(status.st_mode) != RULE_MODE:
        report.fail(f"udev rule must be root:root mode 0644: {RULE_DEST}")
    else:
        report.pass_(f"udev rule content and metadata match {RULE_SOURCE.name}")


def _doctor_session(report: Doctor) -> None:
    loginctl = shutil.which("loginctl")
    if loginctl is None:
        report.warn("loginctl is unavailable; active local session could not be checked")
        return
    session_id = os.environ.get("XDG_SESSION_ID") or "self"
    try:
        result = subprocess.run(
            [
                loginctl,
                "show-session",
                session_id,
                "--property=Active",
                "--property=Remote",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        report.warn(f"loginctl could not be executed: {exc}")
        return
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        report.warn(f"loginctl could not inspect session {session_id}: {detail}")
        return
    properties = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key.strip()] = value.strip().lower()
    if properties.get("Active") == "yes" and properties.get("Remote") == "no":
        report.pass_(f"loginctl reports session {session_id} is active and local")
    else:
        report.fail(f"loginctl does not report session {session_id} as active and local")


def _doctor_xkb(report: Doctor) -> None:
    layout = os.environ.get("XKB_DEFAULT_LAYOUT", "")
    variant = os.environ.get("XKB_DEFAULT_VARIANT", "")
    if not layout:
        report.fail(
            "XKB_DEFAULT_LAYOUT is not set in this environment; set one layout before launching Talon"
        )
        return
    if "," in layout or "," in variant:
        report.fail("only one XKB layout/variant is supported")
        return
    report.pass_(
        f"XKB layout is explicit: {layout}"
        + (f" variant={variant}" if variant else "")
    )


def _doctor_acl_tool(report: Doctor) -> None:
    if shutil.which("setfacl"):
        report.pass_("setfacl is available for uninstall ACL revocation")
    else:
        report.fail("setfacl is required for safe uninstall ACL revocation")


def _iter_rule_files() -> Iterable[Path]:
    seen: Set[Path] = set()
    for directory in (
        Path("/etc/udev/rules.d"),
        Path("/run/udev/rules.d"),
        Path("/usr/lib/udev/rules.d"),
        Path("/lib/udev/rules.d"),
    ):
        try:
            for path in directory.glob("*.rules"):
                try:
                    identity = path.resolve(strict=False)
                except (OSError, RuntimeError):
                    identity = path
                if identity not in seen:
                    seen.add(identity)
                    yield path
        except OSError:
            continue


def _doctor_uinput_rules(report: Doctor) -> None:
    conflicts: List[str] = []
    for path in _iter_rule_files():
        if path == RULE_DEST:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lowered = text.lower()
        if "uinput" not in lowered:
            continue
        broad_access = re.search(
            r"\bmode\s*:?=\s*[\"']?0?66[06][\"']?|\bgroup\s*:?=\s*[\"']?input[\"']?",
            lowered,
        )
        if broad_access:
            conflicts.append(str(path))
    if conflicts:
        report.warn("conflicting broad uinput rule(s): " + ", ".join(sorted(set(conflicts))))
    else:
        report.pass_("no conflicting broad uinput udev rule was found")


def doctor() -> int:
    report = Doctor()
    _doctor_target(report, _target_path())
    _doctor_libraries(report)
    _doctor_uinput(report)
    _doctor_rule(report)
    _doctor_session(report)
    _doctor_xkb(report)
    _doctor_acl_tool(report)
    _doctor_uinput_rules(report)
    print(f"Summary: {report.failures} FAIL, {report.warnings} WARN")
    return report.exit_code()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "uninstall", "doctor"))
    args = parser.parse_args(argv)
    try:
        _require_host_python()
        return {"install": install, "uninstall": uninstall, "doctor": doctor}[args.command]()
    except SetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
