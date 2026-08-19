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
    from wayland_backend.seats import (
        SeatCapability,
        SeatRegistry,
        SeatSnapshot,
        choose_seat,
    )
finally:
    sys.path.remove(str(PLUGINS))


class SeatSelectionTests(unittest.TestCase):
    def test_choose_seat_prefers_seat0_then_lowest_registry_id(self):
        seats = (
            SeatSnapshot(20, "seat1", frozenset()),
            SeatSnapshot(30, "seat0", frozenset()),
            SeatSnapshot(10, "seat2", frozenset()),
        )
        self.assertEqual(choose_seat(seats), 30)
        self.assertEqual(choose_seat(seats[:1] + seats[2:]), 10)
        self.assertIsNone(choose_seat(()))


class SeatRegistryTests(unittest.TestCase):
    def setUp(self):
        self.connection = ImmediateConnection()
        self.seats = SeatRegistry(self.connection)
        self.registry = FakeRegistry()

    def test_publishes_immutable_selected_seat_state(self):
        changes = []
        unsubscribe = self.seats.subscribe(
            lambda: changes.append(self.seats.snapshots())
        )
        self.seats.bind(self.registry, 20, 11, interface(11))
        seat1 = self.registry.bound[0][3]
        seat1.dispatcher["name"](seat1, "seat1")
        seat1.dispatcher["capabilities"](seat1, 3)
        self.seats.bind(self.registry, 30, 11, interface(11))
        seat0 = self.registry.bound[1][3]
        seat0.dispatcher["name"](seat0, "seat0")
        seat0.dispatcher["capabilities"](seat0, 2)

        snapshots = self.seats.snapshots()
        self.assertEqual([seat.id for seat in snapshots], [20, 30])
        self.assertEqual([seat.selected for seat in snapshots], [False, True])
        self.assertEqual(
            snapshots[0].capabilities,
            frozenset((SeatCapability.POINTER, SeatCapability.KEYBOARD)),
        )
        self.assertIs(self.seats.selected().proxy, seat0)
        self.assertTrue(changes)

        unsubscribe()
        unsubscribe()
        count = len(changes)
        seat0.dispatcher["capabilities"](seat0, 3)
        self.assertEqual(len(changes), count)

    def test_notifies_consumers_before_releasing_removed_selected_seat(self):
        observations = []
        self.seats.bind(self.registry, 20, 11, interface(11))
        seat = self.registry.bound[0][3]
        self.seats.subscribe(
            lambda: observations.append((self.seats.selected(), seat.destroyed))
        )

        self.seats.remove(20)

        self.assertEqual(observations, [(None, False)])
        self.assertTrue(seat.destroyed)
        self.assertIn(("release",), seat.calls)

    def test_old_seat_versions_are_destroyed_without_release_request(self):
        self.seats.bind(self.registry, 20, 4, interface(11))
        seat = self.registry.bound[0][3]
        self.seats.remove(20)
        self.assertIn(("_destroy",), seat.calls)
        self.assertNotIn(("release",), seat.calls)

    def test_listener_failure_does_not_skip_other_listeners_or_seat_release(self):
        observed = []
        self.seats.bind(self.registry, 20, 11, interface(11))
        seat = self.registry.bound[0][3]

        def fail():
            raise RuntimeError("listener failed")

        self.seats.subscribe(fail)
        self.seats.subscribe(lambda: observed.append(self.seats.selected()))
        with self.assertRaisesRegex(RuntimeError, "listener failed"):
            self.seats.remove(20)

        self.assertEqual(observed, [None])
        self.assertTrue(seat.destroyed)
        self.assertIn(("release",), seat.calls)

    def test_close_is_idempotent(self):
        self.seats.bind(self.registry, 20, 11, interface(11))
        seat = self.registry.bound[0][3]
        self.seats.close()
        self.seats.close()
        self.assertEqual(seat.calls.count(("release",)), 1)
        self.assertEqual(self.seats.snapshots(), ())


if __name__ == "__main__":
    unittest.main()
