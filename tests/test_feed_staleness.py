"""
Tests for FeedStalenessMonitor (Backlog #4).

Tests:
- Feed registration and update recording
- Staleness detection at threshold
- Critical staleness detection
- Auto-pause of instruments on stale data
- Recovery when fresh data arrives
- Callbacks (on_stale, on_critical, on_recovered)
- Summary/dashboard output
- Integration with TradingHaltManager
"""

import time
import unittest
from unittest.mock import MagicMock

from core.feed_staleness_monitor import (
    FeedStalenessMonitor,
    FeedConfig,
    FeedStatus,
)


class TestFeedRegistration(unittest.TestCase):
    """Feed registration and basic update recording."""

    def test_register_feed(self):
        mon = FeedStalenessMonitor()
        mon.register_feed(FeedConfig(
            feed_id="binance",
            max_age_seconds=30,
            instruments=["BTC/USD", "ETH/USD"],
        ))
        summary = mon.get_summary()
        self.assertEqual(summary["total_feeds"], 2)

    def test_record_update_creates_entry(self):
        mon = FeedStalenessMonitor()
        mon.record_update("binance", "BTC/USD")
        self.assertFalse(mon.is_instrument_paused("BTC/USD"))

    def test_unregistered_feed_uses_defaults(self):
        mon = FeedStalenessMonitor(default_max_age=10)
        mon.record_update("unknown_feed", "XYZ", ts=time.time())
        status = mon.check_feed("unknown_feed", "XYZ")
        self.assertFalse(status.stale)


class TestStalenessDetection(unittest.TestCase):
    """Staleness detection at threshold."""

    def test_fresh_data_not_stale(self):
        mon = FeedStalenessMonitor(default_max_age=60)
        mon.record_update("binance", "BTC/USD", ts=time.time())
        status = mon.check_feed("binance", "BTC/USD")
        self.assertFalse(status.stale)
        self.assertFalse(status.paused)

    def test_old_data_is_stale(self):
        mon = FeedStalenessMonitor(default_max_age=60)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 120)
        status = mon.check_feed("binance", "BTC/USD")
        self.assertTrue(status.stale)
        self.assertTrue(status.paused)

    def test_never_updated_is_stale(self):
        mon = FeedStalenessMonitor(default_max_age=10)
        mon.register_feed(FeedConfig(
            feed_id="kraken",
            max_age_seconds=10,
            instruments=["SOL/USD"],
        ))
        status = mon.check_feed("kraken", "SOL/USD")
        self.assertTrue(status.stale)

    def test_custom_threshold_per_feed(self):
        mon = FeedStalenessMonitor(default_max_age=60)
        mon.register_feed(FeedConfig(
            feed_id="slow_feed",
            max_age_seconds=600,
            instruments=["BOND/USD"],
        ))
        mon.record_update("slow_feed", "BOND/USD", ts=time.time() - 300)
        status = mon.check_feed("slow_feed", "BOND/USD")
        self.assertFalse(status.stale)


class TestCriticalStaleness(unittest.TestCase):
    """Critical staleness detection."""

    def test_critical_threshold(self):
        mon = FeedStalenessMonitor(default_max_age=60, default_critical_age=300)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 400)
        status = mon.check_feed("binance", "BTC/USD")
        self.assertTrue(status.stale)
        self.assertTrue(status.critical)

    def test_stale_but_not_critical(self):
        mon = FeedStalenessMonitor(default_max_age=60, default_critical_age=300)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 120)
        status = mon.check_feed("binance", "BTC/USD")
        self.assertTrue(status.stale)
        self.assertFalse(status.critical)


class TestAutoPause(unittest.TestCase):
    """Auto-pause of instruments on stale data."""

    def test_stale_instrument_paused(self):
        mon = FeedStalenessMonitor(default_max_age=30)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 60)
        mon.check_feed("binance", "BTC/USD")
        self.assertTrue(mon.is_instrument_paused("BTC/USD"))

    def test_fresh_instrument_not_paused(self):
        mon = FeedStalenessMonitor(default_max_age=30)
        mon.record_update("binance", "BTC/USD", ts=time.time())
        mon.check_feed("binance", "BTC/USD")
        self.assertFalse(mon.is_instrument_paused("BTC/USD"))

    def test_paused_instruments_dict(self):
        mon = FeedStalenessMonitor(default_max_age=10)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 20)
        mon.record_update("binance", "ETH/USD", ts=time.time() - 20)
        mon.check_all()
        paused = mon.get_paused_instruments()
        self.assertIn("BTC/USD", paused)
        self.assertIn("ETH/USD", paused)

    def test_check_all_returns_stale_only(self):
        mon = FeedStalenessMonitor(default_max_age=30)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 60)
        mon.record_update("binance", "ETH/USD", ts=time.time())
        stale = mon.check_all()
        symbols = [s.instrument for s in stale]
        self.assertIn("BTC/USD", symbols)
        self.assertNotIn("ETH/USD", symbols)


class TestRecovery(unittest.TestCase):
    """Recovery when fresh data arrives."""

    def test_recovery_unpauses_instrument(self):
        mon = FeedStalenessMonitor(default_max_age=30)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 60)
        mon.check_feed("binance", "BTC/USD")
        self.assertTrue(mon.is_instrument_paused("BTC/USD"))

        # Fresh data arrives
        mon.record_update("binance", "BTC/USD", ts=time.time())
        self.assertFalse(mon.is_instrument_paused("BTC/USD"))

    def test_recovery_clears_stale_set(self):
        mon = FeedStalenessMonitor(default_max_age=30)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 60)
        mon.check_feed("binance", "BTC/USD")
        self.assertEqual(len(mon._stale_set), 1)

        mon.record_update("binance", "BTC/USD", ts=time.time())
        self.assertEqual(len(mon._stale_set), 0)


class TestCallbacks(unittest.TestCase):
    """Callback invocation on stale/critical/recovered events."""

    def test_on_stale_callback(self):
        cb = MagicMock()
        mon = FeedStalenessMonitor(default_max_age=10)
        mon.on_stale(cb)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 20)
        mon.check_feed("binance", "BTC/USD")
        cb.assert_called_once()
        args = cb.call_args[0]
        self.assertEqual(args[0], "binance")
        self.assertEqual(args[1], "BTC/USD")

    def test_on_critical_callback(self):
        cb = MagicMock()
        mon = FeedStalenessMonitor(default_max_age=10, default_critical_age=30)
        mon.on_critical(cb)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 60)
        mon.check_feed("binance", "BTC/USD")
        cb.assert_called_once()

    def test_on_recovered_callback(self):
        cb = MagicMock()
        mon = FeedStalenessMonitor(default_max_age=10)
        mon.on_recovered(cb)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 20)
        mon.check_feed("binance", "BTC/USD")

        # Recover
        mon.record_update("binance", "BTC/USD", ts=time.time())
        cb.assert_called_once_with("binance", "BTC/USD")

    def test_callback_error_does_not_crash(self):
        def bad_cb(*args):
            raise RuntimeError("boom")
        mon = FeedStalenessMonitor(default_max_age=10)
        mon.on_stale(bad_cb)
        mon.record_update("binance", "BTC/USD", ts=time.time() - 20)
        # Should not raise
        mon.check_feed("binance", "BTC/USD")
        self.assertTrue(mon.is_instrument_paused("BTC/USD"))


class TestSummary(unittest.TestCase):
    """Summary/dashboard output."""

    def test_summary_serializable(self):
        import json
        mon = FeedStalenessMonitor(default_max_age=30)
        mon.record_update("binance", "BTC/USD", ts=time.time())
        mon.record_update("kraken", "ETH/USD", ts=time.time() - 60)
        summary = mon.get_summary()
        serialized = json.dumps(summary)
        self.assertIn("total_feeds", serialized)
        self.assertIn("stale_count", serialized)

    def test_summary_sorted_worst_first(self):
        mon = FeedStalenessMonitor(default_max_age=30)
        mon.record_update("binance", "BTC/USD", ts=time.time())
        mon.record_update("kraken", "ETH/USD", ts=time.time() - 120)
        summary = mon.get_summary()
        feeds = summary["feeds"]
        self.assertEqual(len(feeds), 2)
        # Worst (oldest) first
        self.assertEqual(feeds[0]["instrument"], "ETH/USD")


class TestHaltManagerIntegration(unittest.TestCase):
    """Integration: staleness monitor wired to TradingHaltManager."""

    def test_stale_feed_triggers_halt_via_callback(self):
        from core.automated_risk_controls import TradingHaltManager

        halt_mgr = TradingHaltManager()
        mon = FeedStalenessMonitor(default_max_age=10)

        # Wire staleness → halt
        def on_stale(feed_id, instrument, age):
            halt_mgr.halt(f"Stale data: {feed_id}:{instrument} ({age:.0f}s)")

        mon.on_stale(on_stale)

        mon.record_update("binance", "BTC/USD", ts=time.time() - 30)
        mon.check_feed("binance", "BTC/USD")

        self.assertTrue(halt_mgr.is_halted)
        self.assertIn("Stale data", halt_mgr.halt_reason)

    def test_recovery_allows_resume(self):
        from core.automated_risk_controls import TradingHaltManager

        halt_mgr = TradingHaltManager()
        mon = FeedStalenessMonitor(default_max_age=10)

        def on_stale(feed_id, instrument, age):
            halt_mgr.halt(f"Stale: {feed_id}:{instrument}")

        def on_recovered(feed_id, instrument):
            halt_mgr.resume(f"feed_recovered:{feed_id}:{instrument}")

        mon.on_stale(on_stale)
        mon.on_recovered(on_recovered)

        # Go stale
        mon.record_update("binance", "BTC/USD", ts=time.time() - 30)
        mon.check_feed("binance", "BTC/USD")
        self.assertTrue(halt_mgr.is_halted)

        # Recover
        mon.record_update("binance", "BTC/USD", ts=time.time())
        self.assertFalse(halt_mgr.is_halted)


if __name__ == "__main__":
    unittest.main()
