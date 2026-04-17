"""
Tests for risk API endpoints: halt/resume, staleness, summary.

Validates the new endpoints added to web/api/risk_metrics_api.py
and the wire_staleness_monitor integration in RiskControlCoordinator.
"""

import time
import json
import unittest
from unittest.mock import MagicMock, patch

from core.automated_risk_controls import RiskControlCoordinator
from core.feed_staleness_monitor import FeedStalenessMonitor, FeedConfig


class TestWireStalenessMonitor(unittest.TestCase):
    """RiskControlCoordinator.wire_staleness_monitor() integration."""

    def test_wire_registers_on_stale_callback(self):
        coord = RiskControlCoordinator()
        mon = FeedStalenessMonitor(default_max_age=10)

        coord.wire_staleness_monitor(mon)

        self.assertIs(coord.staleness_monitor, mon)
        # The monitor should have 1 on_stale callback from wiring
        self.assertEqual(len(mon._on_stale_callbacks), 1)

    def test_stale_feed_auto_halts_via_wiring(self):
        coord = RiskControlCoordinator()
        mon = FeedStalenessMonitor(default_max_age=10)
        coord.wire_staleness_monitor(mon)

        # Record stale data
        mon.record_update("binance", "BTC/USDT", ts=time.time() - 30)
        mon.check_feed("binance", "BTC/USDT")

        self.assertTrue(coord.halt_manager.is_halted)
        self.assertIn("Stale data", coord.halt_manager.halt_reason)
        self.assertFalse(coord.can_trade())

    def test_comprehensive_status_includes_staleness(self):
        coord = RiskControlCoordinator()
        mon = FeedStalenessMonitor(default_max_age=10)
        coord.wire_staleness_monitor(mon)

        mon.record_update("binance", "BTC/USDT", ts=time.time())
        status = coord.get_comprehensive_risk_status()

        self.assertIn("staleness", status)
        self.assertIn("total_feeds", status["staleness"])

    def test_no_staleness_monitor_returns_empty(self):
        coord = RiskControlCoordinator()
        status = coord.get_comprehensive_risk_status()
        self.assertEqual(status["staleness"], {})


class TestCheckAllRisksWithStaleness(unittest.TestCase):
    """_check_all_risks includes staleness check when monitor is wired."""

    def test_check_all_risks_calls_staleness(self):
        import asyncio

        coord = RiskControlCoordinator()
        mon = FeedStalenessMonitor(default_max_age=10)
        coord.wire_staleness_monitor(mon)

        # Record stale data
        mon.record_update("kraken", "ETH/USDT", ts=time.time() - 30)

        # Run _check_all_risks
        asyncio.get_event_loop().run_until_complete(coord._check_all_risks())

        # Should have halted due to stale feed
        self.assertTrue(coord.halt_manager.is_halted)


class TestHaltResumeEndpointLogic(unittest.TestCase):
    """Test the halt/resume logic that the API endpoints call."""

    def test_halt_changes_state(self):
        coord = RiskControlCoordinator()
        self.assertTrue(coord.can_trade())

        changed = coord.halt_manager.halt("operator_manual_halt")
        self.assertTrue(changed)
        self.assertFalse(coord.can_trade())
        self.assertEqual(coord.halt_manager.halt_reason, "operator_manual_halt")

    def test_resume_changes_state(self):
        coord = RiskControlCoordinator()
        coord.halt_manager.halt("test")
        self.assertFalse(coord.can_trade())

        changed = coord.halt_manager.resume("operator")
        self.assertTrue(changed)
        self.assertTrue(coord.can_trade())

    def test_double_halt_returns_false(self):
        coord = RiskControlCoordinator()
        coord.halt_manager.halt("first")
        changed = coord.halt_manager.halt("second")
        self.assertFalse(changed)

    def test_resume_when_not_halted_returns_false(self):
        coord = RiskControlCoordinator()
        changed = coord.halt_manager.resume("operator")
        self.assertFalse(changed)


class TestHaltStatusSerialization(unittest.TestCase):
    """Halt status output is JSON-serializable for API responses."""

    def test_halt_status_json(self):
        coord = RiskControlCoordinator()
        coord.halt_manager.halt("test_reason")
        status = coord.halt_manager.get_status()
        serialized = json.dumps(status)
        self.assertIn("test_reason", serialized)
        self.assertIn("halted", serialized)

    def test_comprehensive_status_json(self):
        coord = RiskControlCoordinator()
        mon = FeedStalenessMonitor(default_max_age=10)
        coord.wire_staleness_monitor(mon)
        mon.record_update("binance", "BTC/USDT", ts=time.time())

        status = coord.get_comprehensive_risk_status()
        serialized = json.dumps(status)
        self.assertIn("can_trade", serialized)
        self.assertIn("staleness", serialized)
        self.assertIn("trading_halt", serialized)


class TestStalenessEndpointLogic(unittest.TestCase):
    """Test the staleness summary that the API endpoint returns."""

    def test_staleness_summary_structure(self):
        mon = FeedStalenessMonitor(default_max_age=30)
        mon.record_update("binance", "BTC/USDT", ts=time.time())
        mon.record_update("kraken", "ETH/USDT", ts=time.time() - 60)

        summary = mon.get_summary()
        self.assertIn("total_feeds", summary)
        self.assertIn("stale_count", summary)
        self.assertIn("paused_instruments", summary)
        self.assertIn("feeds", summary)
        self.assertEqual(summary["total_feeds"], 2)

    def test_staleness_summary_json(self):
        mon = FeedStalenessMonitor(default_max_age=30)
        mon.record_update("binance", "BTC/USDT", ts=time.time())
        summary = mon.get_summary()
        serialized = json.dumps(summary)
        self.assertIn("total_feeds", serialized)


if __name__ == "__main__":
    unittest.main()
