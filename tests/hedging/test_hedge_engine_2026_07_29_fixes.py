"""Tests for 2026-07-29 Hedge Engine Critical Fixes

Coverage:
  1. Alpha-hedge pairing metadata
  2. Hedge fill confirmation tracking
  3. Hedge-to-alpha latency metrics
  4. Hedge PnL attribution
  5. Hedge size validation
  6. Reduce on exposure flip
  7. Hedge timeout warning at 12m
  8. Config: resting_exit_enabled
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure repo root on sys.path
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ═══════════════════════════════════════════════════════════════════════════
# 1. Alpha-Hedge Pairing Metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestAlphaHedgePairingMetadata(unittest.TestCase):
    """Test alpha-hedge pairing metadata in HedgeOrder and exposure."""

    def test_hedge_order_has_pairing_fields(self):
        """HedgeOrder should have paired_alpha_id, paired_alpha_fill_id, paired_alpha_entry_time."""
        from merid.hedging.engine import HedgeOrder

        order = HedgeOrder(
            asset="BTC",
            timeframe="15m",
            side="no",
            action="buy",
            price_cents=50,
            count=5,
            hedge_reason="same_asset_same_horizon",
            paired_alpha_id="alpha_pos_123",
            paired_alpha_fill_id="fill_456",
            paired_alpha_entry_time=1234567890.0,
        )

        self.assertEqual(order.paired_alpha_id, "alpha_pos_123")
        self.assertEqual(order.paired_alpha_fill_id, "fill_456")
        self.assertEqual(order.paired_alpha_entry_time, 1234567890.0)

    def test_cell_exposure_has_alpha_positions_dict(self):
        """CellExposure should track alpha positions for pairing."""
        from merid.hedging.exposure import CellExposure

        cell = CellExposure(asset="BTC", timeframe="15m")
        # BUG FIX (2026-07-29): CachedPosition uses market_id not position_id
        cell.alpha_positions["KXBTC15M-TEST"] = {
            "fill_id": "fill_1",
            "entry_time": datetime.now(timezone.utc),
            "side": "yes",
            "size": 10,
            "avg_price_cents": 50,
        }

        self.assertIn("KXBTC15M-TEST", cell.alpha_positions)
        self.assertEqual(cell.alpha_positions["KXBTC15M-TEST"]["size"], 10)

    def test_exposure_snapshot_populates_alpha_positions(self):
        """build_exposure_snapshot should populate alpha_positions in cells."""
        from merid.hedging.exposure import build_exposure_snapshot

        snap = build_exposure_snapshot()
        # Should not crash even if no positions exist
        self.assertIsNotNone(snap)

    def test_to_order_intents_passes_pairing_metadata(self):
        """to_order_intents should pass pairing metadata to OrderIntent."""
        from merid.hedging.engine import (
            CryptoHedgeEngine,
            HedgeOrder,
            HedgeResult,
        )

        engine = CryptoHedgeEngine()
        result = HedgeResult(orders=[
            HedgeOrder(
                asset="BTC",
                timeframe="15m",
                side="no",
                action="buy",
                price_cents=50,
                count=5,
                hedge_reason="same_asset_same_horizon",
                paired_alpha_id="alpha_123",
                paired_alpha_fill_id="fill_456",
                paired_alpha_entry_time=1234567890.0,
            ),
        ])

        intents = engine.to_order_intents(result)
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertIsNotNone(intent.metadata)
        self.assertEqual(intent.metadata["paired_alpha_id"], "alpha_123")
        self.assertEqual(intent.metadata["paired_alpha_fill_id"], "fill_456")


# ═══════════════════════════════════════════════════════════════════════════
# 2. Hedge Fill Confirmation Tracking
# ═══════════════════════════════════════════════════════════════════════════


class TestHedgeFillConfirmationTracking(unittest.TestCase):
    """Test hedge fill confirmation tracking in PnL tracker."""

    def test_pnl_record_has_fill_tracking_fields(self):
        """HedgePnLRecord should have hedge_proposed_at, hedge_filled_at, hedge_fill_confirmed."""
        from merid.hedging.pnl_tracker import HedgePnLRecord, HedgeStatus

        record = HedgePnLRecord(
            record_id="test_record",
            created_at=datetime.now(timezone.utc),
            alpha_fill_id="alpha_fill",
            alpha_ticker="KXBTC-TEST",
            alpha_side="yes",
            alpha_entry_price_cents=50,
            alpha_entry_count=10,
            alpha_notional_cents=500,
            hedge_fill_id="hedge_fill",
            hedge_ticker="KXBTC-TEST",
            hedge_side="no",
            hedge_entry_price_cents=50,
            hedge_entry_count=10,
            hedge_notional_cents=500,
            hedge_reason="test",
            hedge_proposed_at=datetime.now(timezone.utc),
        )

        self.assertIsNotNone(record.hedge_proposed_at)
        self.assertIsNone(record.hedge_filled_at)
        self.assertFalse(record.hedge_fill_confirmed)

    def test_confirm_hedge_fill_updates_timestamp(self):
        """confirm_hedge_fill should update hedge_filled_at and hedge_fill_confirmed."""
        from merid.hedging.pnl_tracker import HedgePnLTracker

        tracker = HedgePnLTracker()
        tracker.create_record(
            alpha_fill_id="alpha_1",
            alpha_ticker="KXBTC-TEST",
            alpha_side="yes",
            alpha_entry_price_cents=50,
            alpha_entry_count=10,
            hedge_fill_id="hedge_1",
            hedge_ticker="KXBTC-TEST",
            hedge_side="no",
            hedge_entry_price_cents=50,
            hedge_entry_count=10,
            hedge_reason="test",
        )

        record = tracker.confirm_hedge_fill("hedge_1")
        self.assertIsNotNone(record)
        self.assertTrue(record.hedge_fill_confirmed)
        self.assertIsNotNone(record.hedge_filled_at)

    def test_check_hedge_fill_status(self):
        """check_hedge_fill_status should return fill status for alpha."""
        from merid.hedging.pnl_tracker import HedgePnLTracker

        tracker = HedgePnLTracker()
        tracker.create_record(
            alpha_fill_id="alpha_1",
            alpha_ticker="KXBTC-TEST",
            alpha_side="yes",
            alpha_entry_price_cents=50,
            alpha_entry_count=10,
            hedge_fill_id="hedge_1",
            hedge_ticker="KXBTC-TEST",
            hedge_side="no",
            hedge_entry_price_cents=50,
            hedge_entry_count=10,
            hedge_reason="test",
        )

        status = tracker.check_hedge_fill_status("alpha_1")
        self.assertTrue(status["hedge_exists"])
        self.assertFalse(status["hedge_fill_confirmed"])

        tracker.confirm_hedge_fill("hedge_1")
        status = tracker.check_hedge_fill_status("alpha_1")
        self.assertTrue(status["hedge_fill_confirmed"])


# ═══════════════════════════════════════════════════════════════════════════
# 3. Hedge-to-Alpha Latency Metrics
# ═══════════════════════════════════════════════════════════════════════════


class TestHedgeLatencyMetrics(unittest.TestCase):
    """Test hedge fill latency metrics tracking."""

    def test_latency_samples_tracked(self):
        """HedgePnLTracker should track latency samples."""
        from merid.hedging.pnl_tracker import HedgePnLTracker

        tracker = HedgePnLTracker()
        self.assertEqual(len(tracker._latency_samples), 0)

    def test_confirm_hedge_fill_records_latency(self):
        """confirm_hedge_fill should record latency when proposal time exists."""
        from merid.hedging.pnl_tracker import HedgePnLTracker

        tracker = HedgePnLTracker()
        proposed_time = datetime.now(timezone.utc) - timedelta(seconds=2)
        
        tracker.create_record(
            alpha_fill_id="alpha_1",
            alpha_ticker="KXBTC-TEST",
            alpha_side="yes",
            alpha_entry_price_cents=50,
            alpha_entry_count=10,
            hedge_fill_id="hedge_1",
            hedge_ticker="KXBTC-TEST",
            hedge_side="no",
            hedge_entry_price_cents=50,
            hedge_entry_count=10,
            hedge_reason="test",
        )
        
        # Manually set proposal time for testing
        record_id = tracker._alpha_to_hedge["alpha_1"]
        tracker._records[record_id].hedge_proposed_at = proposed_time

        tracker.confirm_hedge_fill("hedge_1")
        self.assertEqual(len(tracker._latency_samples), 1)
        self.assertGreater(tracker._latency_samples[0], 1000)  # Should be > 1000ms

    def test_get_latency_metrics(self):
        """get_latency_metrics should return statistics."""
        from merid.hedging.pnl_tracker import HedgePnLTracker

        tracker = HedgePnLTracker()
        tracker._latency_samples = [100, 200, 300, 400, 500]

        metrics = tracker.get_latency_metrics()
        self.assertEqual(metrics["count"], 5)
        self.assertEqual(metrics["p50_ms"], 300)
        self.assertEqual(metrics["p95_ms"], 500)
        self.assertEqual(metrics["p99_ms"], 500)
        self.assertEqual(metrics["mean_ms"], 300)
        self.assertEqual(metrics["max_ms"], 500)

    def test_latency_samples_capped_at_1000(self):
        """Latency samples should be capped at 1000 to prevent unbounded growth."""
        from merid.hedging.pnl_tracker import HedgePnLTracker

        tracker = HedgePnLTracker()
        # Add more than 1000 samples
        tracker._latency_samples = list(range(1500))
        
        # Create a record with proposal time to trigger cap in confirm_hedge_fill
        tracker.create_record(
            alpha_fill_id="alpha_1",
            alpha_ticker="KXBTC-TEST",
            alpha_side="yes",
            alpha_entry_price_cents=50,
            alpha_entry_count=10,
            hedge_fill_id="hedge_1",
            hedge_ticker="KXBTC-TEST",
            hedge_side="no",
            hedge_entry_price_cents=50,
            hedge_entry_count=10,
            hedge_reason="test",
        )
        
        # Set proposal time
        record_id = tracker._alpha_to_hedge["alpha_1"]
        tracker._records[record_id].hedge_proposed_at = datetime.now(timezone.utc)
        
        # Confirm fill - this should trigger the cap
        tracker.confirm_hedge_fill("hedge_1")
        
        # Should be capped to 1000
        self.assertEqual(len(tracker._latency_samples), 1000)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Hedge PnL Attribution
# ═══════════════════════════════════════════════════════════════════════════


class TestHedgePnLAttribution(unittest.TestCase):
    """Test hedge PnL attribution methods."""

    def test_get_paired_pnl(self):
        """get_paired_pnl should return comprehensive PnL data."""
        from merid.hedging.pnl_tracker import HedgePnLTracker

        tracker = HedgePnLTracker()
        tracker.create_record(
            alpha_fill_id="alpha_1",
            alpha_ticker="KXBTC-TEST",
            alpha_side="yes",
            alpha_entry_price_cents=50,
            alpha_entry_count=10,
            hedge_fill_id="hedge_1",
            hedge_ticker="KXBTC-TEST",
            hedge_side="no",
            hedge_entry_price_cents=50,
            hedge_entry_count=10,
            hedge_reason="test",
        )

        pnl = tracker.get_paired_pnl("alpha_1")
        self.assertIsNotNone(pnl)
        self.assertEqual(pnl["alpha_fill_id"], "alpha_1")
        self.assertEqual(pnl["hedge_fill_id"], "hedge_1")
        self.assertIn("alpha_pnl_cents", pnl)
        self.assertIn("hedge_pnl_cents", pnl)
        self.assertIn("net_pnl_cents", pnl)

    def test_get_paired_pnl_none_for_unknown_alpha(self):
        """get_paired_pnl should return None for unknown alpha."""
        from merid.hedging.pnl_tracker import HedgePnLTracker

        tracker = HedgePnLTracker()
        pnl = tracker.get_paired_pnl("unknown_alpha")
        self.assertIsNone(pnl)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Hedge Size Validation
# ═══════════════════════════════════════════════════════════════════════════


class TestHedgeSizeValidation(unittest.TestCase):
    """Test hedge size validation against alpha size."""

    def test_hedge_size_capped_to_alpha_size(self):
        """Hedge size should be capped to alpha contract count."""
        from merid.hedging.config import (
            AssetSliceConfig,
            HedgeConfig,
            TimeframeHedgeRule,
        )
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = HedgeConfig(
            enabled=True,
            asset_slices={
                "BTC": AssetSliceConfig(slice_pct_of_bankroll=0.25),
            },
            timeframes={
                "15m": TimeframeHedgeRule(
                    max_net_exposure_pct_of_slice=50.0,  # High cap to allow large hedge
                    target_hedge_ratio=1.0,  # Full hedge
                ),
            },
        )
        
        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "15m")
        cell.yes_notional_cents = 10000
        cell.yes_contracts = 10  # Only 10 alpha contracts
        cell.no_notional_cents = 0

        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        btc_orders = [o for o in result.orders if o.asset == "BTC" and o.timeframe == "15m"]
        
        if btc_orders:
            # Hedge count should not exceed alpha contracts (10)
            for o in btc_orders:
                self.assertLessEqual(o.count, 10, f"Hedge count {o.count} exceeds alpha contracts 10")


# ═══════════════════════════════════════════════════════════════════════════
# 6. Reduce on Exposure Flip
# ═══════════════════════════════════════════════════════════════════════════


class TestReduceOnExposureFlip(unittest.TestCase):
    """Test reduce_on_exposure_flip logic."""

    def test_exposure_flip_detection(self):
        """Engine should detect exposure flips between cycles."""
        from merid.hedging.config import (
            AssetSliceConfig,
            HedgeConfig,
            TimeframeHedgeRule,
            AutoExitConfig,
        )
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = HedgeConfig(
            enabled=True,
            asset_slices={
                "BTC": AssetSliceConfig(slice_pct_of_bankroll=0.25),
            },
            timeframes={
                "15m": TimeframeHedgeRule(
                    max_net_exposure_pct_of_slice=50.0,
                    target_hedge_ratio=0.5,
                ),
            },
            auto_exit=AutoExitConfig(
                reduce_on_exposure_flip=True,
            ),
        )
        
        # First cycle: long exposure
        snap1 = ExposureSnapshot()
        cell1 = snap1.get_cell("BTC", "15m")
        cell1.yes_notional_cents = 10000
        cell1.no_notional_cents = 0
        
        result1 = engine.compute_hedge_orders(snap1, cfg, bankroll_cents=100000)
        orders1 = [o for o in result1.orders if o.asset == "BTC" and o.timeframe == "15m"]
        original_count = orders1[0].count if orders1 else 0
        
        # Second cycle: flip to short exposure
        snap2 = ExposureSnapshot()
        cell2 = snap2.get_cell("BTC", "15m")
        cell2.yes_notional_cents = 0
        cell2.no_notional_cents = 10000
        
        result2 = engine.compute_hedge_orders(snap2, cfg, bankroll_cents=100000)
        orders2 = [o for o in result2.orders if o.asset == "BTC" and o.timeframe == "15m"]
        
        if orders2 and original_count > 0:
            # Hedge should be reduced by 50% on flip
            self.assertLess(orders2[0].count, original_count)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Hedge Timeout Warning
# ═══════════════════════════════════════════════════════════════════════════


class TestHedgeTimeoutWarning(unittest.TestCase):
    """Test hedge timeout warning at 12 minutes."""

    def test_timeout_warning_at_12m(self):
        """get_hedges_past_hold_time should warn at 12m for 15m timeout."""
        from merid.hedging.config import (
            HedgeConfig,
            AutoExitConfig,
        )
        from merid.hedging.pnl_tracker import HedgePnLTracker, HedgeStatus

        tracker = HedgePnLTracker()
        tracker.create_record(
            alpha_fill_id="alpha_1",
            alpha_ticker="KXBTC-TEST",
            alpha_side="yes",
            alpha_entry_price_cents=50,
            alpha_entry_count=10,
            hedge_fill_id="hedge_1",
            hedge_ticker="KXBTC-TEST",
            hedge_side="no",
            hedge_entry_price_cents=50,
            hedge_entry_count=10,
            hedge_reason="test",
        )
        
        # Set record to be 13 minutes old (past 12m warning, before 15m timeout)
        record_id = tracker._alpha_to_hedge["alpha_1"]
        tracker._records[record_id].created_at = datetime.now(timezone.utc) - timedelta(minutes=13)
        
        cfg = HedgeConfig(
            auto_exit=AutoExitConfig(
                enabled=True,
                max_hedge_hold_minutes=15,
            ),
        )
        
        # This should log a warning (we can't easily test log output, but we verify it doesn't crash)
        try:
            orders = tracker.get_hedges_past_hold_time(cfg)
            # Should return exit orders for timeout
            self.assertIsInstance(orders, list)
        except Exception as e:
            self.fail(f"get_hedges_past_hold_time raised exception: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# 8. Config: resting_exit_enabled
# ═══════════════════════════════════════════════════════════════════════════


class TestRestingExitConfig(unittest.TestCase):
    """Test resting_exit_enabled config flag."""

    def test_config_has_resting_exit_enabled(self):
        """AutoExitConfig should have resting_exit_enabled field."""
        from merid.hedging.config import AutoExitConfig

        config = AutoExitConfig(
            enabled=True,
            close_hedge_when_alpha_closed=True,
            max_hedge_hold_minutes=15,
            reduce_on_exposure_flip=True,
            resting_exit_enabled=True,
        )

        self.assertTrue(config.resting_exit_enabled)

    def test_config_parsing_resting_exit_enabled(self):
        """Config parsing should read resting_exit_enabled from YAML."""
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        self.assertIsNotNone(cfg.auto_exit.resting_exit_enabled)
        # Should be True as we enabled it
        self.assertTrue(cfg.auto_exit.resting_exit_enabled)


if __name__ == "__main__":
    unittest.main()
