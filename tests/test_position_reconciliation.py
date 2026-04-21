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
            "BTC/USD": {"qty": 0.5, "entry_price": 48000, "venue": "binanceus"},
            "ETH/USD": {"qty": 2.0, "entry_price": 3200, "venue": "coinbase"},
        }
        _run(self.sm.update_state(positions))
        _run(self.sm._save_state())

        # Simulate restart: new StateManager instance
        sm2 = StateManager("positions", persistence_dir=self.tmpdir)
        _run(sm2.initialize())
        loaded = _run(sm2.get_state())

        self.assertEqual(loaded["BTC/USD"]["qty"], 0.5)
        self.assertEqual(loaded["ETH/USD"]["entry_price"], 3200)

    def test_position_update_persists(self):
        _run(self.sm.update_state({"BTC/USD": {"qty": 1.0, "entry_price": 50000}}))
        _run(self.sm._save_state())

        # Update position
        _run(self.sm.update_state({"BTC/USD": {"qty": 0.5, "entry_price": 50000}}))
        _run(self.sm._save_state())

        # Restart
        sm2 = StateManager("positions", persistence_dir=self.tmpdir)
        _run(sm2.initialize())
        loaded = _run(sm2.get_state())
        self.assertEqual(loaded["BTC/USD"]["qty"], 0.5)

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
            {"BTC/USD": {"qty": 1.0}},
            create_recovery_point=True,
        ))
        self.assertEqual(len(self.sm.recovery_points), 1)

    def test_recovery_restores_state(self):
        # Save good state with recovery point
        good_state = {"BTC/USD": {"qty": 1.0, "entry_price": 50000}}
        _run(self.sm.update_state(good_state, create_recovery_point=True))

        # Corrupt state
        self.sm.current_state = "corrupted"
        self.sm.state_status = StateStatus.CORRUPTED

        # Attempt recovery
        result = _run(self.sm._attempt_recovery())
        self.assertTrue(result)
        self.assertEqual(self.sm.state_status, StateStatus.HEALTHY)

        recovered = _run(self.sm.get_state())
        self.assertEqual(recovered["BTC/USD"]["qty"], 1.0)

    def test_multiple_recovery_points_uses_newest(self):
        _run(self.sm.update_state(
            {"BTC/USD": {"qty": 1.0}},
            create_recovery_point=True,
        ))
        _run(self.sm.update_state(
            {"BTC/USD": {"qty": 2.0}},
            create_recovery_point=True,
        ))
        self.assertEqual(len(self.sm.recovery_points), 2)

        # Corrupt and recover
        self.sm.current_state = {}
        self.sm.state_status = StateStatus.CORRUPTED
        _run(self.sm._attempt_recovery())

        recovered = _run(self.sm.get_state())
        self.assertEqual(recovered["BTC/USD"]["qty"], 2.0)


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
        _run(self.sm.update_state({"BTC/USD": {"qty": 1.0}}))
        self.assertGreater(len(self.sm.state_history), 0)
        self.assertTrue(len(self.sm.state_history[-1].checksum) > 0)

    def test_different_states_different_checksums(self):
        _run(self.sm.update_state({"BTC/USD": {"qty": 1.0}}))
        cs1 = self.sm.state_history[-1].checksum
        _run(self.sm.update_state({"BTC/USD": {"qty": 2.0}}))
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
        _run(self.sm.update_state({"BTC/USD": {"qty": 1.0}}))
        status = self.sm.get_status()
        self.assertEqual(status["component"], "positions")
        self.assertEqual(status["status"], "healthy")
        self.assertGreater(status["history_count"], 0)

    def test_initial_status_healthy(self):
        status = self.sm.get_status()
        self.assertEqual(status["status"], "healthy")
        self.assertEqual(status["recovery_points"], 0)


class TestPositionReconciliationUnderLoad(unittest.TestCase):
    """Position reconciliation under simulated load (S6-04 soak)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sm = StateManager("positions", persistence_dir=self.tmpdir)
        _run(self.sm.initialize())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rapid_updates_1000_cycles(self):
        """1000 rapid position updates with periodic saves."""
        for i in range(1000):
            positions = {
                f"SYM-{i % 20}": {
                    "qty": float(i % 50) * 0.1,
                    "entry_price": 100.0 + (i % 100),
                    "venue": ["binanceus", "coinbase", "alpaca"][i % 3],
                },
            }
            _run(self.sm.update_state(positions))
            if i % 100 == 0:
                _run(self.sm._save_state())

        _run(self.sm._save_state())
        state = _run(self.sm.get_state())
        self.assertGreater(len(state), 0)
        self.assertEqual(self.sm.state_status, StateStatus.HEALTHY)

    def test_save_load_cycle_under_load(self):
        """Repeated save → new instance → load cycle under load."""
        for cycle in range(50):
            positions = {
                f"POS-{j}": {"qty": float(cycle + j), "entry_price": 1000.0 * (j + 1)}
                for j in range(10)
            }
            _run(self.sm.update_state(positions))
            _run(self.sm._save_state())

            # Simulate restart
            sm2 = StateManager("positions", persistence_dir=self.tmpdir)
            _run(sm2.initialize())
            loaded = _run(sm2.get_state())
            self.assertEqual(len(loaded), 10, f"Cycle {cycle}: expected 10 positions")
            self.sm = sm2  # continue with reloaded instance

        self.assertEqual(self.sm.state_status, StateStatus.HEALTHY)

    def test_recovery_point_under_load(self):
        """Recovery points remain valid after many updates."""
        # Create recovery point with known-good state
        good_state = {"BTC/USD": {"qty": 1.0, "entry_price": 50000}}
        _run(self.sm.update_state(good_state, create_recovery_point=True))

        # Hammer with 500 updates
        for i in range(500):
            _run(self.sm.update_state({
                f"LOAD-{i}": {"qty": float(i), "entry_price": float(i * 10)},
            }))

        # Corrupt and recover
        self.sm.current_state = "corrupted"
        self.sm.state_status = StateStatus.CORRUPTED
        result = _run(self.sm._attempt_recovery())
        self.assertTrue(result)
        recovered = _run(self.sm.get_state())
        self.assertIn("BTC/USD", recovered)

    def test_large_position_book_persistence(self):
        """100-position book persists and reloads correctly."""
        positions = {
            f"INST-{i:03d}": {
                "qty": round(0.01 * (i + 1), 4),
                "entry_price": round(100.0 + i * 10.5, 2),
                "venue": ["binanceus", "coinbase", "alpaca", "kalshi"][i % 4],
                "side": "long" if i % 2 == 0 else "short",
            }
            for i in range(100)
        }
        _run(self.sm.update_state(positions))
        _run(self.sm._save_state())

        sm2 = StateManager("positions", persistence_dir=self.tmpdir)
        _run(sm2.initialize())
        loaded = _run(sm2.get_state())
        self.assertEqual(len(loaded), 100)
        self.assertEqual(loaded["INST-050"]["venue"], "alpaca")

    def test_checksum_stable_under_load(self):
        """Checksum is deterministic even after many updates."""
        state = {"BTC/USD": {"qty": 1.0, "entry_price": 50000}}
        cs1 = self.sm._calculate_checksum(state)

        # Do 200 unrelated updates
        for i in range(200):
            _run(self.sm.update_state({f"TMP-{i}": {"qty": float(i)}}))

        cs2 = self.sm._calculate_checksum(state)
        self.assertEqual(cs1, cs2, "Checksum should be deterministic for same input")


if __name__ == "__main__":
    unittest.main()
