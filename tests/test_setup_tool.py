import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SETUP_DIR = ROOT / "setup"
SPEC = importlib.util.spec_from_file_location(
    "jm_talon_lite_setup_tool",
    SETUP_DIR / "setup_tool.py",
)
assert SPEC is not None and SPEC.loader is not None
setup_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup_tool)


class SetupFilesTest(unittest.TestCase):
    def test_scripts_are_extensionless_executable_shell_entry_points(self):
        for name, command in (
            ("install", "install"),
            ("uninstall", "uninstall"),
            ("doctor", "doctor"),
        ):
            path = SETUP_DIR / name
            self.assertEqual(path.suffix, "")
            self.assertTrue(path.stat().st_mode & stat.S_IXUSR)
            text = path.read_text(encoding="ascii")
            self.assertTrue(text.startswith("#!/bin/sh\n"))
            self.assertIn(f'"$SCRIPT_DIR/setup_tool.py" {command} "$@"', text)

    def test_requirement_is_version_and_hash_locked(self):
        text = (SETUP_DIR / "requirements.txt").read_text(encoding="ascii")
        self.assertIn("libevdev==0.13.1", text)
        self.assertIn(
            "sha256:1a15dc796ecb1cba679fc564686f9efab5124efae6e41dba8f4bf377d5a72f4a",
            text,
        )
        self.assertNotIn("typing_extensions", text)

    def test_rule_is_namespaced_active_seat_only_and_sorts_before_73(self):
        path = SETUP_DIR / setup_tool.RULE_NAME
        text = path.read_text(encoding="ascii")
        self.assertLess(path.name, "73-seat-late.rules")
        self.assertIn('KERNEL=="uinput"', text)
        self.assertIn('TAG+="uaccess"', text)
        self.assertNotRegex(text, r"(?i)GROUP|MODE")


class TargetAndStateTest(unittest.TestCase):
    def test_target_uses_xdg_data_home_or_home_fallback(self):
        with mock.patch.dict(
            os.environ,
            {"XDG_DATA_HOME": "/tmp/data", "HOME": "/tmp/home"},
            clear=True,
        ):
            self.assertEqual(
                setup_tool._target_path(),
                Path("/tmp/data/jm-talon-lite/python"),
            )
        with mock.patch.dict(os.environ, {"HOME": "/tmp/home"}, clear=True):
            self.assertEqual(
                setup_tool._target_path(),
                Path("/tmp/home/.local/share/jm-talon-lite/python"),
            )

    def test_relative_xdg_data_home_is_rejected(self):
        with mock.patch.dict(
            os.environ,
            {"XDG_DATA_HOME": "relative", "HOME": "/tmp/home"},
            clear=True,
        ):
            with self.assertRaises(setup_tool.SetupError):
                setup_tool._target_path()

    def test_existing_target_parent_must_be_user_owned_real_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "data" / "jm-talon-lite"
            parent.mkdir(parents=True)
            setup_tool._ensure_owned_directory(parent, "test parent")
            (parent / "child").mkdir()
            link = Path(temporary) / "link"
            link.symlink_to(parent, target_is_directory=True)
            with self.assertRaises(setup_tool.SetupError):
                setup_tool._ensure_owned_directory(link / "child", "test parent")

    def test_manifest_detects_content_mode_and_extra_directory_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "python"
            package = target / "libevdev"
            package.mkdir(parents=True)
            source = package / "__init__.py"
            source.write_text("VERSION = '0.13.1'\n", encoding="ascii")
            setup_tool._write_state(
                target,
                managed_target=target,
                rule_owned=True,
            )
            state = setup_tool._load_state(target)
            assert state is not None
            setup_tool._assert_unmodified_target(target, state)

            source.chmod(0o600)
            with self.assertRaises(setup_tool.SetupError):
                setup_tool._assert_unmodified_target(target, state)
            source.chmod(0o644)
            (target / "local").mkdir()
            with self.assertRaises(setup_tool.SetupError):
                setup_tool._assert_unmodified_target(target, state)

    def test_installed_package_directories_are_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "python"
            package = target / "libevdev" / "nested"
            package.mkdir(parents=True)
            setup_tool._lock_installed_directories(target)
            self.assertTrue(target.stat().st_mode & stat.S_IWUSR)
            self.assertFalse(package.parent.stat().st_mode & 0o222)
            self.assertFalse(package.stat().st_mode & 0o222)
            setup_tool._remove_owned_tree(target)
            self.assertFalse(target.exists())

    def test_state_rejects_unconstrained_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "python"
            target.mkdir()
            setup_tool._write_state(
                target,
                managed_target=target,
                rule_owned=False,
            )
            state_path = target / setup_tool.STATE_NAME
            state = json.loads(state_path.read_text(encoding="ascii"))
            state["unexpected"] = True
            state_path.write_text(json.dumps(state), encoding="ascii")
            state_path.chmod(0o600)
            with self.assertRaises(setup_tool.SetupError):
                setup_tool._load_state(target)


class InstallerPolicyTest(unittest.TestCase):
    def test_pip_is_hash_locked_binary_only_and_has_no_dependencies(self):
        commands = []
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            setup_tool.importlib.util,
            "find_spec",
            return_value=object(),
        ), mock.patch.object(setup_tool, "_run", side_effect=commands.append):
            setup_tool._pip_install(Path(temporary))
        command = commands[0]
        self.assertIn("--require-hashes", command)
        self.assertIn("--only-binary=:all:", command)
        self.assertIn("--no-deps", command)
        self.assertIn("--target", command)

    def test_privileged_helpers_are_constrained_to_rule_and_udev(self):
        commands = []
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            setup_tool,
            "RULE_DEST",
            Path(temporary) / setup_tool.RULE_NAME,
        ), mock.patch.object(
            setup_tool,
            "_run",
            side_effect=commands.append,
        ), mock.patch.object(
            setup_tool,
            "_rule_is_expected_file",
            return_value=True,
        ), mock.patch.object(
            setup_tool.Path,
            "exists",
            return_value=False,
        ), mock.patch.object(
            setup_tool.Path,
            "is_symlink",
            return_value=False,
        ), mock.patch.object(
            setup_tool.shutil,
            "which",
            return_value="/usr/bin/setfacl",
        ):
            self.assertTrue(setup_tool._copy_rule_if_needed())
            setup_tool._reload_uinput_rule()
            setup_tool._sudo_remove_rule()

        destination = str(Path(temporary) / setup_tool.RULE_NAME)
        self.assertEqual(commands[0][:3], ["sudo", "install", "-o"])
        self.assertEqual(commands[0][-1], destination)
        self.assertEqual(
            commands[1],
            ["sudo", "udevadm", "control", "--reload-rules"],
        )
        self.assertEqual(
            commands[2],
            [
                "sudo",
                "udevadm",
                "trigger",
                "--action=change",
                "--subsystem-match=misc",
                "--sysname-match=uinput",
            ],
        )
        self.assertEqual(commands[3], ["sudo", "rm", "-f", "--", destination])
        self.assertEqual(
            commands[-1],
            [
                "sudo",
                "/usr/bin/setfacl",
                "-x",
                f"u:{os.geteuid()}",
                "--",
                "/dev/uinput",
            ],
        )

    def test_failed_rule_state_update_rolls_back_new_rule(self):
        with mock.patch.object(
            setup_tool,
            "_sudo_remove_rule",
        ) as remove_rule:
            setup_tool._remove_new_rule_after_failed_state_update()
        remove_rule.assert_called_once_with()

    def test_preexisting_identical_rule_is_not_claimed(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            setup_tool,
            "RULE_DEST",
            Path(temporary) / setup_tool.RULE_NAME,
        ):
            setup_tool.RULE_DEST.write_bytes(setup_tool.RULE_SOURCE.read_bytes())
            with mock.patch.object(
                setup_tool,
                "_rule_is_expected_file",
                return_value=True,
            ):
                self.assertFalse(setup_tool._planned_rule_ownership(None))
                self.assertTrue(
                    setup_tool._planned_rule_ownership({"rule_owned": True})
                )

    def test_existing_managed_target_is_replaced_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "python"
            stage = root / ".python-stage"
            target.mkdir()
            (target / "old.py").write_text("old\n", encoding="ascii")
            setup_tool._write_state(
                target,
                managed_target=target,
                rule_owned=False,
            )
            stage.mkdir()
            (stage / "new.py").write_text("new\n", encoding="ascii")
            setup_tool._write_state(
                stage,
                managed_target=target,
                rule_owned=False,
            )

            setup_tool._activate_stage(stage, target)

            self.assertFalse(stage.exists())
            self.assertTrue((target / "new.py").exists())
            self.assertFalse((target / "old.py").exists())

    def test_unmarked_target_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "python"
            stage = root / ".python-stage"
            target.mkdir()
            stage.mkdir()
            with self.assertRaises(setup_tool.SetupError):
                setup_tool._activate_stage(stage, target)
            self.assertTrue(target.exists())
            self.assertTrue(stage.exists())

    def test_install_rejects_root_or_sudo(self):
        with mock.patch.object(setup_tool.os, "geteuid", return_value=0):
            with self.assertRaises(setup_tool.SetupError):
                setup_tool._reject_root_install()
        with mock.patch.object(
            setup_tool.os,
            "geteuid",
            return_value=1000,
        ), mock.patch.dict(os.environ, {"SUDO_USER": "alice"}, clear=True):
            with self.assertRaises(setup_tool.SetupError):
                setup_tool._reject_root_install()


class UninstallAndDoctorTest(unittest.TestCase):
    def test_uninstall_preserves_modified_target_and_rule_without_sudo(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "data" / "jm-talon-lite" / "python"
            target.mkdir(parents=True)
            package_file = target / "owned.py"
            package_file.write_text("original\n", encoding="ascii")
            rule = root / setup_tool.RULE_NAME
            rule.write_text("locally changed\n", encoding="ascii")
            with mock.patch.object(setup_tool, "RULE_DEST", rule):
                setup_tool._write_state(
                    target,
                    managed_target=target,
                    rule_owned=True,
                )
                package_file.write_text("locally changed\n", encoding="ascii")
                output = io.StringIO()
                with mock.patch.object(
                    setup_tool,
                    "_target_path",
                    return_value=target,
                ), mock.patch.dict(
                    os.environ,
                    {},
                    clear=True,
                ), mock.patch.object(
                    setup_tool,
                    "_sudo_remove_rule",
                ) as remove_rule, contextlib.redirect_stdout(output):
                    result = setup_tool.uninstall()

            self.assertEqual(result, 0)
            self.assertTrue(target.exists())
            self.assertTrue(rule.exists())
            remove_rule.assert_not_called()
            self.assertIn("preserving locally modified udev rule", output.getvalue())
            self.assertIn(
                "Preserved locally modified dependency target",
                output.getvalue(),
            )

    def test_uninstall_removes_only_unchanged_owned_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "data" / "jm-talon-lite" / "python"
            target.mkdir(parents=True)
            (target / "owned.py").write_text("owned\n", encoding="ascii")
            rule = root / setup_tool.RULE_NAME
            rule.write_bytes(setup_tool.RULE_SOURCE.read_bytes())
            with mock.patch.object(
                setup_tool,
                "RULE_DEST",
                rule,
            ), mock.patch.object(
                setup_tool,
                "_rule_matches",
                return_value=True,
            ):
                setup_tool._write_state(
                    target,
                    managed_target=target,
                    rule_owned=True,
                )

                def remove_rule():
                    rule.unlink()

                with mock.patch.object(
                    setup_tool,
                    "_target_path",
                    return_value=target,
                ), mock.patch.dict(
                    os.environ,
                    {},
                    clear=True,
                ), mock.patch.object(
                    setup_tool,
                    "_sudo_remove_rule",
                    side_effect=remove_rule,
                ), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(setup_tool.uninstall(), 0)

            self.assertFalse(target.exists())
            self.assertFalse(rule.exists())

    def test_uninstall_is_idempotent_when_resources_are_absent(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            setup_tool,
            "_target_path",
            return_value=Path(temporary) / "missing-python",
        ), mock.patch.object(
            setup_tool,
            "RULE_DEST",
            Path(temporary) / "missing.rules",
        ), mock.patch.object(
            setup_tool.os,
            "geteuid",
            return_value=1000,
        ), mock.patch.dict(
            os.environ,
            {},
            clear=True,
        ), mock.patch.object(
            setup_tool,
            "_sudo_remove_rule",
        ) as remove_rule, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(setup_tool.uninstall(), 0)
            self.assertEqual(setup_tool.uninstall(), 0)
        remove_rule.assert_not_called()

    def test_doctor_warns_for_broad_uinput_rule(self):
        with tempfile.TemporaryDirectory() as temporary:
            rule = Path(temporary) / "80-uinput.rules"
            rule.write_text(
                'KERNEL=="uinput", GROUP="input", MODE="0660"\n',
                encoding="ascii",
            )
            report = setup_tool.Doctor()
            with mock.patch.object(
                setup_tool,
                "_iter_rule_files",
                return_value=[rule],
            ), contextlib.redirect_stdout(io.StringIO()):
                setup_tool._doctor_uinput_rules(report)
            self.assertEqual(report.warnings, 1)
            self.assertEqual(report.failures, 0)

    def test_session_check_requires_active_and_not_remote(self):
        completed = types.SimpleNamespace(
            returncode=0,
            stdout="Active=yes\nRemote=yes\n",
            stderr="",
        )
        report = setup_tool.Doctor()
        with mock.patch.object(
            setup_tool.shutil,
            "which",
            return_value="/usr/bin/loginctl",
        ), mock.patch.object(
            setup_tool.subprocess,
            "run",
            return_value=completed,
        ), mock.patch.dict(
            os.environ,
            {"XDG_SESSION_ID": "7"},
            clear=True,
        ), contextlib.redirect_stdout(io.StringIO()):
            setup_tool._doctor_session(report)
        self.assertEqual(report.failures, 1)

    def test_doctor_requires_one_explicit_xkb_layout(self):
        report = setup_tool.Doctor()
        with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(
            io.StringIO()
        ):
            setup_tool._doctor_xkb(report)
        self.assertEqual(report.failures, 1)

        report = setup_tool.Doctor()
        with mock.patch.dict(
            os.environ,
            {"XKB_DEFAULT_LAYOUT": "us"},
            clear=True,
        ), contextlib.redirect_stdout(io.StringIO()):
            setup_tool._doctor_xkb(report)
        self.assertEqual(report.failures, 0)

    def test_doctor_requires_setfacl_for_safe_uninstall(self):
        report = setup_tool.Doctor()
        with mock.patch.object(
            setup_tool.shutil,
            "which",
            return_value=None,
        ), contextlib.redirect_stdout(io.StringIO()):
            setup_tool._doctor_acl_tool(report)
        self.assertEqual(report.failures, 1)


if __name__ == "__main__":
    unittest.main()
