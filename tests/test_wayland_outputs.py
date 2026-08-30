import sys
import unittest
from pathlib import Path

if __package__:
    from .wayland_fakes import FakeRegistry, ImmediateConnection, interface
else:
    from wayland_fakes import FakeRegistry, ImmediateConnection, interface

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"
sys.path.insert(0, str(PLUGINS))
try:
    from wayland_backend.outputs import (
        OutputRegistry,
        OutputSnapshot,
        OutputTarget,
        choose_output,
    )
finally:
    sys.path.remove(str(PLUGINS))


def snapshot(
    output_id: int,
    name: str,
    *,
    make: str = "Wacom Tech",
    model: str = "CintiqPro24PT",
    physical_width: int = 530,
    physical_height: int = 300,
    mode_width: int = 3840,
    mode_height: int = 2160,
) -> OutputSnapshot:
    return OutputSnapshot(
        output_id,
        name,
        f"{make} {model}",
        make,
        model,
        physical_width,
        physical_height,
        mode_width,
        mode_height,
        60000,
        2,
        0,
    )


def target(name: str = "HDMI-A-1") -> OutputTarget:
    return OutputTarget(
        name,
        "Wacom Tech",
        "CintiqPro24PT",
        530.0,
        300.0,
        3840,
        2160,
        60000,
    )


def publish_output(
    registry: OutputRegistry,
    fake_registry: FakeRegistry,
    output_id: int,
    name: str,
    *,
    version: int = 4,
    make: str = "Wacom Tech",
    model: str = "CintiqPro24PT",
    physical_width: int = 530,
    physical_height: int = 300,
    mode_width: int = 3840,
    mode_height: int = 2160,
):
    registry.bind(fake_registry, output_id, version, interface(4))
    output = fake_registry.bound[-1][3]
    output.dispatcher["geometry"](
        output,
        0,
        0,
        physical_width,
        physical_height,
        0,
        make,
        model,
        0,
    )
    output.dispatcher["mode"](
        output,
        1,
        mode_width,
        mode_height,
        60000,
    )
    if version >= 2:
        output.dispatcher["scale"](output, 2)
    if version >= 4:
        output.dispatcher["name"](output, name)
        output.dispatcher["description"](output, f"{make} {model}")
    if version >= 2:
        output.dispatcher["done"](output)
    return output


class OutputSelectionTests(unittest.TestCase):
    def test_exact_runtime_name_wins_over_other_metadata(self):
        outputs = (
            snapshot(10, "HDMI-A-1", make="Different", model="Display"),
            snapshot(20, "DP-1"),
        )
        self.assertEqual(choose_output(target(), outputs), 10)

    def test_unique_physical_and_mode_match_handles_rotated_axes(self):
        unnamed = OutputTarget("", "", "", 300, 530, 2160, 3840, 60000)
        outputs = (
            snapshot(10, "HDMI-A-1"),
            snapshot(
                20,
                "DP-1",
                make="Other",
                model="Monitor",
                physical_width=150,
                physical_height=90,
                mode_width=2048,
                mode_height=1152,
            ),
        )
        self.assertEqual(choose_output(unnamed, outputs), 10)

    def test_ambiguous_metadata_does_not_guess_by_registry_order(self):
        unnamed = OutputTarget("", "", "", 530, 300, 3840, 2160, 60000)
        outputs = (snapshot(20, "DP-1"), snapshot(10, "HDMI-A-1"))
        self.assertIsNone(choose_output(unnamed, outputs))
        self.assertEqual(choose_output(unnamed, outputs[:1]), 20)

    def test_exact_names_remain_case_sensitive(self):
        outputs = (
            snapshot(10, "DP-1"),
            snapshot(20, "dp-1"),
        )
        self.assertEqual(choose_output(target("DP-1"), outputs), 10)

    def test_single_known_nonmatching_output_is_not_selected(self):
        other = snapshot(
            20,
            "DP-1",
            make="Other",
            model="Monitor",
            physical_width=150,
            physical_height=90,
            mode_width=2048,
            mode_height=1152,
        )
        self.assertIsNone(choose_output(target(), (other,)))


class OutputRegistryTests(unittest.TestCase):
    def setUp(self):
        self.connection = ImmediateConnection()
        self.outputs = OutputRegistry(self.connection)
        self.registry = FakeRegistry()

    def test_publishes_output_metadata_atomically_on_done(self):
        self.outputs.bind(self.registry, 10, 4, interface(4))
        output = self.registry.bound[-1][3]
        output.dispatcher["name"](output, "HDMI-A-1")
        self.assertEqual(self.outputs.snapshots(), ())

        output.dispatcher["geometry"](
            output, 0, 0, 530, 300, 0, "Wacom Tech", "CintiqPro24PT", 0
        )
        output.dispatcher["mode"](output, 1, 3840, 2160, 60000)
        output.dispatcher["scale"](output, 2)
        output.dispatcher["description"](output, "Wacom Tech CintiqPro24PT")
        output.dispatcher["done"](output)

        self.assertEqual(self.outputs.snapshots(), (snapshot(10, "HDMI-A-1"),))
        self.assertIs(self.outputs.match(target()).proxy, output)

    def test_notifies_before_releasing_removed_output(self):
        output = publish_output(self.outputs, self.registry, 10, "HDMI-A-1")
        observations = []
        self.outputs.subscribe(
            lambda: observations.append((self.outputs.snapshots(), output.destroyed))
        )

        self.outputs.remove(10)

        self.assertEqual(observations, [((), False)])
        self.assertTrue(output.destroyed)
        self.assertIn(("release",), output.calls)

    def test_old_output_versions_are_destroyed_without_release_request(self):
        output = publish_output(
            self.outputs,
            self.registry,
            10,
            "",
            version=2,
        )
        self.outputs.remove(10)
        self.assertIn(("_destroy",), output.calls)
        self.assertNotIn(("release",), output.calls)

    def test_version_one_publishes_without_done(self):
        output = publish_output(
            self.outputs,
            self.registry,
            10,
            "",
            version=1,
        )
        self.assertEqual(len(self.outputs.snapshots()), 1)
        self.assertIs(self.outputs.match(target("")).proxy, output)

    def test_version_three_uses_release_request(self):
        output = publish_output(
            self.outputs,
            self.registry,
            10,
            "",
            version=3,
        )
        self.outputs.remove(10)
        self.assertIn(("release",), output.calls)

    def test_close_is_idempotent(self):
        output = publish_output(self.outputs, self.registry, 10, "HDMI-A-1")
        self.outputs.close()
        self.outputs.close()
        self.assertEqual(output.calls.count(("release",)), 1)
        self.assertEqual(self.outputs.snapshots(), ())


if __name__ == "__main__":
    unittest.main()
