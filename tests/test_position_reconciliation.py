"""
Position reconciliation after restart tests (S6-04 hardening).

Validates:
- Position state persists to disk via StateManager
- Positions survive simulated restart (save → new instance → load)
- Corrupted state triggers recovery
- Recovery point restores last-known-good positions
- Empty state on fresh start (no prior persistence)
- Checksum validates state integrity
- Multiple position updates maintain consistency
"""

import asyncio
import json
import os
import shutil
import tempfile
import unittest

from core.state_recovery import StateManager, StateStatus


def _run(coro):
    """Run async coroutine in sync test."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestPositionPersistence(unittest.TestCase):
    """Position state persists to disk and survives restart."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = StateManager("positions", persistence_dir=self.tmpdir)
        _run(self.sm.initialize())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fresh_start_empty(self):
        state = _run(self.sm.get_state())
        self.assertEqual(state, {})

    def test_save_and_load_positions(self):
        positions = {
            "BTC/USDT": {"qty": 0.5, "entry_price": 48000, "venue": "binanceus"},
            "ETH/USDT": {"qty": 2.0, "entry_price": 3200, "venue": "coinbase"},
        }
        _run(self.sm.update_state(positions))
        _run(self.sm._save_state())

        # Simulate restart: new StateManager instance
        sm2 = StateManager("positions", persistence_dir=self.tmpdir)
        _run(sm2.initialize())
        loaded = _run(sm2.get_state())

        self.assertEqual(loaded["BTC/USDT"]["qty"], 0.5)
        self.assertEqual(loaded["ETH/USDT"]["entry_price"], 3200)

    def test_position_update_persists(self):
        _run(self.sm.update_state({"BTC/USDT": {"qty": 1.0, "entry_price": 50000}}))
        _run(self.sm._save_state())

        # Update position
        _run(self.sm.update_state({"BTC/USDT": {"qty": 0.5, "entry_price": 50000}}))
        _run(self.sm._save_state())

        # Restart
        sm2 = StateManager("positions", persistence_dir=self.tmpdir)
        _run(sm2.initialize())
        loaded = _run(sm2.get_state())
        self.assertEqual(loaded["BTC/USDT"]["qty"], 0.5)

    def test_multiple_positions_roundtrip(self):
        positions = {
            f"SYM-{i}": {"qty": float(i), "entry_price": 100.0 * i}
            for i in range(10)
        }
        _run(self.sm.update_state(positions))
        _run(self.sm._save_state())

        sm2 = StateManager("positions", persistence_dir=self.tmpdir)
        _run(sm2.initialize())
        loaded = _run(sm2.get_state())
        self.assertEqual(len(loaded), 10)
        self.assertEqual(loaded["SYM-5"]["qty"], 5.0)


class TestRecoveryPoint(unittest.TestCase):
    """Recovery points restore last-known-good state."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = StateManager("positions", persistence_dir=self.tmpdir)
        _run(self.sm.initialize())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_recovery_point_created(self):
        _run(self.sm.update_state(
            {"BTC/USDT": {"qty": 1.0}},
            create_recovery_point=True,
        ))
        self.assertEqual(len(self.sm.recovery_points), 1)

    def test_recovery_restores_state(self):
        # Save good state with recovery point
        good_state = {"BTC/USDT": {"qty": 1.0, "entry_price": 50000}}
        _run(self.sm.update_state(good_state, create_recovery_point=True))

        # Corrupt state
        self.sm.current_state = "corrupted"
        self.sm.state_status = StateStatus.CORRUPTED

        # Attempt recovery
        result = _run(self.sm._attempt_recovery())
        self.assertTrue(result)
        self.assertEqual(self.sm.state_status, StateStatus.HEALTHY)

        recovered = _run(self.sm.get_state())
        self.assertEqual(recovered["BTC/USDT"]["qty"], 1.0)

    def test_multiple_recovery_points_uses_newest(self):
        _run(self.sm.update_state(
            {"BTC/USDT": {"qty": 1.0}},
            create_recovery_point=True,
        ))
        _run(self.sm.update_state(
            {"BTC/USDT": {"qty": 2.0}},
            create_recovery_point=True,
        ))
        self.assertEqual(len(self.sm.recovery_points), 2)

        # Corrupt and recover
        self.sm.current_state = {}
        self.sm.state_status = StateStatus.CORRUPTED
        _run(self.sm._attempt_recovery())

        recovered = _run(self.sm.get_state())
        self.assertEqual(recovered["BTC/USDT"]["qty"], 2.0)


class TestCorruptedState(unittest.TestCase):
    """Corrupted persisted state is handled gracefully."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_corrupted_json_triggers_recovery(self):
        # Write corrupted state file
        state_file = os.path.join(self.tmpdir, "positions_state.json")
        with open(state_file, "w") as f:
            f.write("{invalid json!!!")

        sm = StateManager("positions", persistence_dir=self.tmpdir)
        # initialize should handle the error gracefully
        _run(sm.initialize())
        # Should be in degraded state after failed load + recovery
        self.assertIn(sm.state_status, {StateStatus.DEGRADED, StateStatus.RECOVERING})

    def test_missing_state_file_is_clean_start(self):
        sm = StateManager("positions", persistence_dir=self.tmpdir)
        _run(sm.initialize())
        self.assertEqual(sm.state_status, StateStatus.HEALTHY)
        state = _run(sm.get_state())
        self.assertEqual(state, {})


class TestChecksumIntegrity(unittest.TestCase):
    """State checksum validates integrity."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = StateManager("positions", persistence_dir=self.tmpdir)
        _run(self.sm.initialize())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_checksum_computed(self):
        _run(self.sm.update_state({"BTC/USDT": {"qty": 1.0}}))
        self.assertGreater(len(self.sm.state_history), 0)
        self.assertTrue(len(self.sm.state_history[-1].checksum) > 0)

    def test_different_states_different_checksums(self):
        _run(self.sm.update_state({"BTC/USDT": {"qty": 1.0}}))
        cs1 = self.sm.state_history[-1].checksum
        _run(self.sm.update_state({"BTC/USDT": {"qty": 2.0}}))
        cs2 = self.sm.state_history[-1].checksum
        self.assertNotEqual(cs1, cs2)

    def test_same_state_same_checksum(self):
        cs1 = self.sm._calculate_checksum({"a": 1})
        cs2 = self.sm._calculate_checksum({"a": 1})
        self.assertEqual(cs1, cs2)


class TestStateManagerStatus(unittest.TestCase):
    """StateManager status reporting."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = StateManager("positions", persistence_dir=self.tmpdir)
        _run(self.sm.initialize())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_status_report(self):
        _run(self.sm.update_state({"BTC/USDT": {"qty": 1.0}}))
        status = self.sm.get_status()
        self.assertEqual(status["component"], "positions")
        self.assertEqual(status["status"], "healthy")
        self.assertGreater(status["history_count"], 0)

    def test_initial_status_healthy(self):
        status = self.sm.get_status()
        self.assertEqual(status["status"], "healthy")
        self.assertEqual(status["recovery_points"], 0)


if __name__ == "__main__":
    unittest.main()
