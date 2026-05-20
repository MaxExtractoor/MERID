"""Tests for merid.metrics — Brier calibration, realized edge, outcome resolver.

Sprint A test suite: 45+ tests across 6 classes.
"""

from __future__ import annotations

import asyncio
import math
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.metrics.calibration import (
    BrierStats,
    CalibrationStore,
    ForecastRecord,
    DEFAULT_WEIGHT,
    EWMA_ALPHA,
    MAX_WEIGHT,
    MIN_FORECASTS_FOR_WEIGHT,
    MIN_WEIGHT,
    WEIGHT_EPSILON,
    WEIGHT_SCALE_FACTOR,
)
from merid.metrics.realized_edge import (
    EdgeStats,
    RealizedEdgeStore,
    TradeEdgeRecord,
)
from merid.metrics.outcome_resolver import (
    OutcomeResolver,
    ResolutionResult,
)


# ══════════════════════════════════════════════════════════════════════════
# §1 CalibrationStore
# ══════════════════════════════════════════════════════════════════════════


class TestCalibrationStore(unittest.TestCase):
    """Tests for the Brier score calibration store."""

    def setUp(self):
        self.store = CalibrationStore(db_path=":memory:")

    def test_record_and_count(self):
        """Recording a forecast increments the count."""
        self.store.record_forecast("model_a", "crypto", "MKT1", 0.6)
        stats = self.store.get_stats("model_a", "crypto")
        self.assertEqual(stats.count, 1)
        self.assertEqual(stats.resolved_count, 0)

    def test_record_multiple_forecasts(self):
        """Multiple forecasts for different markets are tracked."""
        self.store.record_forecast("model_a", "crypto", "MKT1", 0.6)
        self.store.record_forecast("model_a", "crypto", "MKT2", 0.7)
        self.store.record_forecast("model_a", "macro", "MKT3", 0.4)
        stats_crypto = self.store.get_stats("model_a", "crypto")
        stats_macro = self.store.get_stats("model_a", "macro")
        self.assertEqual(stats_crypto.count, 2)
        self.assertEqual(stats_macro.count, 1)

    def test_resolve_outcome_yes(self):
        """Resolving a YES outcome computes correct Brier score."""
        self.store.record_forecast("model_a", "crypto", "MKT1", 0.8)
        resolved = self.store.resolve_outcome("MKT1", outcome=1)
        self.assertEqual(resolved, 1)
        stats = self.store.get_stats("model_a", "crypto")
        self.assertEqual(stats.resolved_count, 1)
        # Brier = (0.8 - 1)^2 = 0.04
        self.assertAlmostEqual(stats.sum_brier, 0.04, places=6)

    def test_resolve_outcome_no(self):
        """Resolving a NO outcome computes correct Brier score."""
        self.store.record_forecast("model_a", "crypto", "MKT1", 0.8)
        resolved = self.store.resolve_outcome("MKT1", outcome=0)
        self.assertEqual(resolved, 1)
        stats = self.store.get_stats("model_a", "crypto")
        # Brier = (0.8 - 0)^2 = 0.64
        self.assertAlmostEqual(stats.sum_brier, 0.64, places=6)

    def test_resolve_multiple_forecasters_same_market(self):
        """Multiple forecasters on the same market are all resolved."""
        self.store.record_forecast("model_a", "crypto", "MKT1", 0.8)
        self.store.record_forecast("model_b", "crypto", "MKT1", 0.3)
        resolved = self.store.resolve_outcome("MKT1", outcome=1)
        self.assertEqual(resolved, 2)
        # model_a: (0.8-1)^2 = 0.04 (good)
        # model_b: (0.3-1)^2 = 0.49 (bad)
        stats_a = self.store.get_stats("model_a", "crypto")
        stats_b = self.store.get_stats("model_b", "crypto")
        self.assertAlmostEqual(stats_a.sum_brier, 0.04, places=6)
        self.assertAlmostEqual(stats_b.sum_brier, 0.49, places=6)

    def test_resolve_no_forecasts(self):
        """Resolving a market with no forecasts returns 0."""
        resolved = self.store.resolve_outcome("NONEXISTENT", outcome=1)
        self.assertEqual(resolved, 0)

    def test_resolve_idempotent(self):
        """Resolving the same market twice doesn't double-count."""
        self.store.record_forecast("model_a", "crypto", "MKT1", 0.6)
        self.store.resolve_outcome("MKT1", outcome=1)
        resolved = self.store.resolve_outcome("MKT1", outcome=1)
        self.assertEqual(resolved, 0)  # Already resolved
        stats = self.store.get_stats("model_a", "crypto")
        self.assertEqual(stats.resolved_count, 1)

    def test_invalid_outcome_raises(self):
        """Invalid outcome (not 0 or 1) raises ValueError."""
        with self.assertRaises(ValueError):
            self.store.resolve_outcome("MKT1", outcome=2)

    def test_get_brier_default(self):
        """Default Brier for unknown forecaster is 0.25 (coin-flip)."""
        brier = self.store.get_brier("unknown", "crypto")
        self.assertEqual(brier, 0.25)

    def test_ewma_brier_updates(self):
        """EWMA Brier updates with each resolution."""
        self.store.record_forecast("m", "c", "MKT1", 0.9)
        self.store.resolve_outcome("MKT1", outcome=1)
        stats = self.store.get_stats("m", "c")
        # First resolution: EWMA starts from 0.25, then shifts toward 0.01
        # EWMA = (1 - 0.05) * 0.25 + 0.05 * 0.01 = 0.2375 + 0.0005 = 0.238
        expected = (1 - EWMA_ALPHA) * 0.25 + EWMA_ALPHA * 0.01
        self.assertAlmostEqual(stats.ewma_brier, expected, places=6)

    def test_get_weight_insufficient_history(self):
        """Weight returns DEFAULT_WEIGHT when insufficient history."""
        self.store.record_forecast("m", "c", "MKT1", 0.5)
        self.store.resolve_outcome("MKT1", outcome=1)
        weight = self.store.get_weight("m", "c")
        self.assertEqual(weight, DEFAULT_WEIGHT)

    def test_get_weight_with_history(self):
        """Weight inversely proportional to Brier after enough forecasts."""
        # Seed enough resolved forecasts
        for i in range(MIN_FORECASTS_FOR_WEIGHT + 5):
            self.store.record_forecast("m", "c", f"MKT{i}", 0.9)
            self.store.resolve_outcome(f"MKT{i}", outcome=1)

        weight = self.store.get_weight("m", "c")
        # Good forecaster (BS near 0) should have high weight
        self.assertGreater(weight, DEFAULT_WEIGHT)
        self.assertLessEqual(weight, MAX_WEIGHT)

    def test_bad_forecaster_low_weight(self):
        """A bad forecaster gets low weight."""
        for i in range(MIN_FORECASTS_FOR_WEIGHT + 5):
            # Predict 0.9 but outcome is always NO
            self.store.record_forecast("bad", "c", f"MKT{i}", 0.9)
            self.store.resolve_outcome(f"MKT{i}", outcome=0)

        weight = self.store.get_weight("bad", "c")
        self.assertLess(weight, DEFAULT_WEIGHT)

    def test_p_model_clamped(self):
        """p_model is clamped to [0, 1]."""
        self.store.record_forecast("m", "c", "MKT1", 1.5)  # Over 1
        self.store.record_forecast("m", "c", "MKT2", -0.3)  # Under 0
        forecasts = self.store.get_forecasts_for_market("MKT1")
        self.assertEqual(len(forecasts), 1)
        self.assertLessEqual(forecasts[0].p_model, 1.0)
        forecasts2 = self.store.get_forecasts_for_market("MKT2")
        self.assertGreaterEqual(forecasts2[0].p_model, 0.0)

    def test_list_forecasters(self):
        """list_forecasters returns distinct forecaster IDs."""
        self.store.record_forecast("alpha", "crypto", "MKT1", 0.5)
        self.store.record_forecast("beta", "macro", "MKT2", 0.6)
        self.store.record_forecast("alpha", "macro", "MKT3", 0.7)
        ids = self.store.list_forecasters()
        self.assertEqual(sorted(ids), ["alpha", "beta"])

    def test_get_unresolved_markets(self):
        """Unresolved markets list is correct."""
        self.store.record_forecast("m", "c", "MKT1", 0.5)
        self.store.record_forecast("m", "c", "MKT2", 0.6)
        self.store.resolve_outcome("MKT1", outcome=1)
        unresolved = self.store.get_unresolved_markets()
        self.assertEqual(unresolved, ["MKT2"])

    def test_get_forecaster_summary(self):
        """Forecaster summary aggregates across buckets."""
        self.store.record_forecast("m", "crypto", "MKT1", 0.8)
        self.store.record_forecast("m", "macro", "MKT2", 0.4)
        self.store.resolve_outcome("MKT1", outcome=1)
        summary = self.store.get_forecaster_summary("m")
        self.assertEqual(summary["forecaster_id"], "m")
        self.assertEqual(summary["total_forecasts"], 2)
        self.assertEqual(summary["total_resolved"], 1)
        self.assertIn("crypto", summary["buckets"])

    def test_reset_clears_all(self):
        """reset() clears all data."""
        self.store.record_forecast("m", "c", "MKT1", 0.5)
        self.store.reset()
        self.assertEqual(self.store.list_forecasters(), [])
        self.assertEqual(self.store.get_unresolved_markets(), [])

    def test_brier_stats_dataclass(self):
        """BrierStats properties compute correctly."""
        bs = BrierStats(
            forecaster_id="m", bucket="c",
            resolved_count=4,
            sum_brier=0.8,
            sum_brier_sq=0.2,
        )
        self.assertAlmostEqual(bs.mean_brier, 0.2, places=6)
        self.assertGreater(bs.std_brier, 0.0)
        d = bs.to_dict()
        self.assertIn("mean_brier", d)

    def test_forecast_record_dataclass(self):
        """ForecastRecord serializes correctly."""
        fr = ForecastRecord(
            forecaster_id="m", bucket="c", market_id="MKT1",
            p_model=0.75, timestamp=1000.0,
        )
        d = fr.to_dict()
        self.assertEqual(d["p_model"], 0.75)
        self.assertFalse(d["resolved"])


# ══════════════════════════════════════════════════════════════════════════
# §2 RealizedEdgeStore
# ══════════════════════════════════════════════════════════════════════════


class TestRealizedEdgeStore(unittest.TestCase):
    """Tests for the realized edge tracking store."""

    def setUp(self):
        self.store = RealizedEdgeStore(db_path=":memory:")

    def test_record_trade_entry(self):
        """Recording a trade increments trade count."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="yes", action="buy", price_cents=55,
            p_model=0.62, p_implied=0.55, contracts=10, fee_cents=31,
        )
        stats = self.store.get_edge_stats("m", "crypto")
        self.assertEqual(stats.trade_count, 1)
        self.assertEqual(stats.resolved_count, 0)

    def test_resolve_trade_yes_wins(self):
        """YES buyer wins: correct PnL and realized edge."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="yes", action="buy", price_cents=55,
            p_model=0.62, p_implied=0.55, contracts=10, fee_cents=31,
        )
        ok = self.store.resolve_trade("T1", outcome=1)
        self.assertTrue(ok)

        trade = self.store.get_trade("T1")
        self.assertTrue(trade.resolved)
        self.assertEqual(trade.outcome, 1)
        # PnL = (100-55)*10 - 31 = 450 - 31 = 419
        self.assertEqual(trade.realized_pnl_cents, 419)
        # Realized edge = 419 / (55*10) = 419/550 ≈ 0.7618
        self.assertAlmostEqual(trade.realized_edge, 419 / 550, places=4)

    def test_resolve_trade_yes_loses(self):
        """YES buyer loses: PnL = -price * contracts."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="yes", action="buy", price_cents=55,
            p_model=0.62, p_implied=0.55, contracts=10, fee_cents=31,
        )
        ok = self.store.resolve_trade("T1", outcome=0)
        self.assertTrue(ok)

        trade = self.store.get_trade("T1")
        # PnL = -55 * 10 = -550
        self.assertEqual(trade.realized_pnl_cents, -550)

    def test_resolve_trade_yes_sell_wins(self):
        """YES seller wins (NO wins): receive price, pay 0."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="yes", action="sell", price_cents=55,
            p_model=0.62, p_implied=0.55, contracts=10, fee_cents=31,
        )
        ok = self.store.resolve_trade("T1", outcome=0)
        self.assertTrue(ok)

        trade = self.store.get_trade("T1")
        # YES seller wins: received 55*10 = 550, pay 0, fee 31
        # PnL = 550 - 0 - 31 = 519
        self.assertEqual(trade.realized_pnl_cents, 519)

    def test_resolve_trade_yes_sell_loses(self):
        """YES seller loses (YES wins): receive price, pay 100."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="yes", action="sell", price_cents=55,
            p_model=0.62, p_implied=0.55, contracts=10, fee_cents=31,
        )
        ok = self.store.resolve_trade("T1", outcome=1)
        self.assertTrue(ok)

        trade = self.store.get_trade("T1")
        # YES seller loses: received 55*10 = 550, pay 100*10 = 1000, fee 31
        # PnL = 550 - 1000 - 31 = -481
        self.assertEqual(trade.realized_pnl_cents, -481)

    def test_resolve_trade_no_sell_wins(self):
        """NO seller wins (YES wins): receive price, pay 100."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="no", action="sell", price_cents=45,
            p_model=0.38, p_implied=0.45, contracts=10, fee_cents=31,
        )
        ok = self.store.resolve_trade("T1", outcome=1)
        self.assertTrue(ok)

        trade = self.store.get_trade("T1")
        # NO seller wins: received 45*10 = 450, pay 100*10 = 1000, fee 31
        # PnL = 450 - 1000 - 31 = -581
        self.assertEqual(trade.realized_pnl_cents, -581)

    def test_resolve_trade_no_sell_loses(self):
        """NO seller loses (NO wins): receive price, pay 0."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="no", action="sell", price_cents=45,
            p_model=0.38, p_implied=0.45, contracts=10, fee_cents=31,
        )
        ok = self.store.resolve_trade("T1", outcome=0)
        self.assertTrue(ok)

        trade = self.store.get_trade("T1")
        # NO seller loses: received 45*10 = 450, pay 0, fee 31
        # PnL = 450 - 0 - 31 = 419
        self.assertEqual(trade.realized_pnl_cents, 419)

    def test_resolve_trade_no_wins(self):
        """NO buyer wins when outcome=0."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="no", action="buy", price_cents=45,
            p_model=0.38, p_implied=0.45, contracts=10, fee_cents=31,
        )
        ok = self.store.resolve_trade("T1", outcome=0)
        self.assertTrue(ok)

        trade = self.store.get_trade("T1")
        # NO buyer wins: PnL = price * contracts - fees = 45*10 - 31 = 419
        self.assertEqual(trade.realized_pnl_cents, 419)

    def test_resolve_trade_no_loses(self):
        """NO buyer loses when outcome=1."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="no", action="buy", price_cents=45,
            p_model=0.38, p_implied=0.45, contracts=10, fee_cents=31,
        )
        ok = self.store.resolve_trade("T1", outcome=1)
        self.assertTrue(ok)

        trade = self.store.get_trade("T1")
        # NO buyer loses: PnL = -(100-45)*10 = -550
        self.assertEqual(trade.realized_pnl_cents, -550)

    def test_resolve_trade_idempotent(self):
        """Resolving the same trade twice returns False."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="yes", action="buy", price_cents=50,
            p_model=0.6, p_implied=0.5, contracts=5, fee_cents=17,
        )
        self.store.resolve_trade("T1", outcome=1)
        ok = self.store.resolve_trade("T1", outcome=1)
        self.assertFalse(ok)

    def test_resolve_nonexistent_trade(self):
        """Resolving a non-existent trade returns False."""
        ok = self.store.resolve_trade("NOPE", outcome=1)
        self.assertFalse(ok)

    def test_resolve_market_batch(self):
        """resolve_market resolves all trades for a market."""
        for i in range(5):
            self.store.record_trade_entry(
                trade_id=f"T{i}", forecaster_id="m", bucket="crypto",
                market_id="MKT1", side="yes", action="buy", price_cents=50,
                p_model=0.6, p_implied=0.5, contracts=5, fee_cents=17,
            )
        resolved = self.store.resolve_market("MKT1", outcome=1)
        self.assertEqual(resolved, 5)

    def test_edge_stats_aggregation(self):
        """Edge stats aggregate across multiple trades."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="crypto",
            market_id="MKT1", side="yes", action="buy", price_cents=50,
            p_model=0.6, p_implied=0.5, contracts=10, fee_cents=35,
        )
        self.store.record_trade_entry(
            trade_id="T2", forecaster_id="m", bucket="crypto",
            market_id="MKT2", side="yes", action="buy", price_cents=60,
            p_model=0.7, p_implied=0.6, contracts=5, fee_cents=14,
        )
        self.store.resolve_trade("T1", outcome=1)
        self.store.resolve_trade("T2", outcome=0)

        stats = self.store.get_edge_stats("m", "crypto")
        self.assertEqual(stats.resolved_count, 2)
        self.assertEqual(stats.winning_trades, 1)
        self.assertEqual(stats.losing_trades, 1)
        self.assertNotEqual(stats.sum_pnl_cents, 0)

    def test_edge_stats_properties(self):
        """EdgeStats computed properties."""
        es = EdgeStats(
            forecaster_id="m", bucket="c",
            resolved_count=10,
            sum_est_edge=1.0,
            sum_realized_edge=0.8,
            winning_trades=6,
            losing_trades=4,
        )
        self.assertAlmostEqual(es.mean_est_edge, 0.1, places=6)
        self.assertAlmostEqual(es.mean_realized_edge, 0.08, places=6)
        self.assertAlmostEqual(es.edge_ratio, 0.8, places=4)
        self.assertAlmostEqual(es.mean_slippage, 0.02, places=6)
        self.assertAlmostEqual(es.win_rate, 0.6, places=4)

    def test_get_unresolved_markets(self):
        """Unresolved markets list from edge store."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="c",
            market_id="MKT1", side="yes", action="buy", price_cents=50,
            p_model=0.6, p_implied=0.5, contracts=5, fee_cents=17,
        )
        self.store.record_trade_entry(
            trade_id="T2", forecaster_id="m", bucket="c",
            market_id="MKT2", side="yes", action="buy", price_cents=50,
            p_model=0.6, p_implied=0.5, contracts=5, fee_cents=17,
        )
        self.store.resolve_trade("T1", outcome=1)
        unresolved = self.store.get_unresolved_markets()
        self.assertEqual(unresolved, ["MKT2"])

    def test_trade_edge_record_dataclass(self):
        """TradeEdgeRecord serializes correctly."""
        r = TradeEdgeRecord(
            trade_id="T1", forecaster_id="m", bucket="c",
            market_id="MKT1", side="yes", price_cents=50,
            p_model=0.6, p_implied=0.5, est_edge=0.1,
            contracts=5, fee_cents=17, timestamp=1000.0,
        )
        d = r.to_dict()
        self.assertEqual(d["trade_id"], "T1")
        self.assertEqual(d["est_edge"], 0.1)

    def test_reset_clears_all(self):
        """reset() clears edge data."""
        self.store.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="c",
            market_id="MKT1", side="yes", action="buy", price_cents=50,
            p_model=0.6, p_implied=0.5, contracts=5, fee_cents=17,
        )
        self.store.reset()
        self.assertEqual(self.store.get_unresolved_markets(), [])


# ══════════════════════════════════════════════════════════════════════════
# §3 OutcomeResolver
# ══════════════════════════════════════════════════════════════════════════


class TestOutcomeResolver(unittest.TestCase):
    """Tests for the outcome resolver."""

    def setUp(self):
        # Create stores in memory
        self.cal = CalibrationStore(db_path=":memory:")
        self.edge = RealizedEdgeStore(db_path=":memory:")
        self.resolver = OutcomeResolver()
        self.resolver._calibration_store = self.cal
        self.resolver._edge_store = self.edge

    def test_resolve_manual(self):
        """Manual resolution resolves both stores."""
        self.cal.record_forecast("m", "c", "MKT1", 0.7)
        self.edge.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="c",
            market_id="MKT1", side="yes", action="buy", price_cents=50,
            p_model=0.7, p_implied=0.5, contracts=5, fee_cents=17,
        )

        result = self.resolver.resolve_manual("MKT1", outcome=1)
        self.assertTrue(result.resolved)
        self.assertEqual(result.forecasts_resolved, 1)
        self.assertEqual(result.trades_resolved, 1)
        self.assertEqual(result.outcome, 1)

    def test_resolve_manual_invalid_outcome(self):
        """Manual resolve with invalid outcome returns error."""
        result = self.resolver.resolve_manual("MKT1", outcome=5)
        self.assertFalse(result.resolved)
        self.assertIsNotNone(result.error)

    def test_resolve_all_empty(self):
        """resolve_all with nothing pending returns empty."""
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(self.resolver.resolve_all())
            self.assertEqual(results, [])
        finally:
            loop.close()

    def test_status(self):
        """Status returns correct pending counts."""
        self.cal.record_forecast("m", "c", "MKT1", 0.5)
        self.edge.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="c",
            market_id="MKT2", side="yes", action="buy", price_cents=50,
            p_model=0.6, p_implied=0.5, contracts=5, fee_cents=17,
        )
        status = self.resolver.status()
        self.assertEqual(status["pending_forecast_markets"], 1)
        self.assertEqual(status["pending_trade_markets"], 1)

    def test_resolution_result_dataclass(self):
        """ResolutionResult serializes correctly."""
        r = ResolutionResult(
            market_id="MKT1", resolved=True, outcome=1,
            forecasts_resolved=3, trades_resolved=2,
        )
        d = r.to_dict()
        self.assertEqual(d["market_id"], "MKT1")
        self.assertTrue(d["resolved"])


# ══════════════════════════════════════════════════════════════════════════
# §4 Integration — Brier + Edge end-to-end
# ══════════════════════════════════════════════════════════════════════════


class TestIntegrationBrierAndEdge(unittest.TestCase):
    """End-to-end: forecasts → trades → resolution → metrics."""

    def setUp(self):
        self.cal = CalibrationStore(db_path=":memory:")
        self.edge = RealizedEdgeStore(db_path=":memory:")
        self.resolver = OutcomeResolver()
        self.resolver._calibration_store = self.cal
        self.resolver._edge_store = self.edge

    def test_full_lifecycle(self):
        """Full lifecycle: forecast → trade → resolve → check stats."""
        # 1. Agent forecasts p=0.8 for MKT1 (crypto)
        self.cal.record_forecast("agent_btc_15m", "crypto", "MKT1", 0.80)

        # 2. Trade is placed: buy YES at 55c, 10 contracts
        self.edge.record_trade_entry(
            trade_id="ORD_001",
            forecaster_id="agent_btc_15m",
            bucket="crypto",
            market_id="MKT1",
            side="yes",
            action="buy",
            price_cents=55,
            p_model=0.80,
            p_implied=0.55,
            contracts=10,
            fee_cents=31,
        )

        # 3. Market settles YES
        result = self.resolver.resolve_manual("MKT1", outcome=1)
        self.assertTrue(result.resolved)
        self.assertEqual(result.forecasts_resolved, 1)
        self.assertEqual(result.trades_resolved, 1)

        # 4. Check Brier — should be low (good forecast)
        brier = self.cal.get_brier("agent_btc_15m", "crypto")
        # First EWMA update from 0.25 toward 0.04 (=(0.8-1)^2)
        expected_ewma = (1 - EWMA_ALPHA) * 0.25 + EWMA_ALPHA * 0.04
        self.assertAlmostEqual(brier, expected_ewma, places=6)

        # 5. Check realized edge — should be positive
        es = self.edge.get_edge_stats("agent_btc_15m", "crypto")
        self.assertEqual(es.winning_trades, 1)
        self.assertEqual(es.losing_trades, 0)
        self.assertGreater(es.sum_pnl_cents, 0)

    def test_good_vs_bad_forecaster(self):
        """Good forecaster has lower Brier and higher weight than bad one."""
        # 10 markets, good forecaster predicts well, bad one is random
        for i in range(MIN_FORECASTS_FOR_WEIGHT + 2):
            outcome = i % 2  # alternating YES/NO
            good_p = 0.85 if outcome == 1 else 0.15
            bad_p = 0.5  # coin flip

            self.cal.record_forecast("good", "c", f"M{i}", good_p)
            self.cal.record_forecast("bad", "c", f"M{i}", bad_p)
            self.cal.resolve_outcome(f"M{i}", outcome=outcome)

        good_brier = self.cal.get_brier("good", "c")
        bad_brier = self.cal.get_brier("bad", "c")
        self.assertLess(good_brier, bad_brier)

        good_weight = self.cal.get_weight("good", "c")
        bad_weight = self.cal.get_weight("bad", "c")
        self.assertGreater(good_weight, bad_weight)

    def test_edge_leakage_detection(self):
        """Detect when estimated edge exceeds realized edge (leakage)."""
        # Place trade with estimated 10% edge
        self.edge.record_trade_entry(
            trade_id="T1", forecaster_id="m", bucket="c",
            market_id="M1", side="yes", action="buy", price_cents=50,
            p_model=0.60, p_implied=0.50, contracts=10, fee_cents=35,
        )
        # Market resolves NO — we lose
        self.edge.resolve_trade("T1", outcome=0)

        stats = self.edge.get_edge_stats("m", "c")
        # We estimated positive edge but realized negative
        self.assertGreater(stats.mean_est_edge, 0)
        self.assertLess(stats.mean_realized_edge, 0)
        self.assertGreater(stats.mean_slippage, 0)  # Positive = leaking

    def test_multiple_buckets_independent(self):
        """Stats are tracked independently per bucket."""
        self.cal.record_forecast("m", "crypto", "M1", 0.9)
        self.cal.record_forecast("m", "politics", "M2", 0.1)
        self.cal.resolve_outcome("M1", outcome=1)  # Good crypto forecast
        self.cal.resolve_outcome("M2", outcome=1)  # Bad politics forecast

        crypto_stats = self.cal.get_stats("m", "crypto")
        politics_stats = self.cal.get_stats("m", "politics")

        # Crypto: (0.9-1)^2 = 0.01 (excellent)
        # Politics: (0.1-1)^2 = 0.81 (terrible)
        self.assertAlmostEqual(crypto_stats.sum_brier, 0.01, places=6)
        self.assertAlmostEqual(politics_stats.sum_brier, 0.81, places=6)


# ══════════════════════════════════════════════════════════════════════════
# §5 CalibrationStore — Weight computation edge cases
# ══════════════════════════════════════════════════════════════════════════


class TestCalibrationWeights(unittest.TestCase):
    """Edge cases for weight computation."""

    def setUp(self):
        self.store = CalibrationStore(db_path=":memory:")

    def test_perfect_forecaster_high_weight(self):
        """Perfect forecaster (all correct at 1.0) gets weight > DEFAULT."""
        for i in range(MIN_FORECASTS_FOR_WEIGHT + 5):
            self.store.record_forecast("perfect", "c", f"M{i}", 1.0)
            self.store.resolve_outcome(f"M{i}", outcome=1)
        weight = self.store.get_weight("perfect", "c")
        # EWMA decays slowly (alpha=0.05), so after 15 updates the EWMA
        # is still well above 0. But weight should be above DEFAULT_WEIGHT.
        self.assertGreater(weight, DEFAULT_WEIGHT)

    def test_worst_forecaster_min_weight(self):
        """Worst forecaster (always wrong) gets near-minimum weight."""
        for i in range(MIN_FORECASTS_FOR_WEIGHT + 5):
            # Predict 1.0 but outcome is always 0
            self.store.record_forecast("worst", "c", f"M{i}", 1.0)
            self.store.resolve_outcome(f"M{i}", outcome=0)
        weight = self.store.get_weight("worst", "c")
        # Brier near 1.0, weight should be low
        self.assertLess(weight, DEFAULT_WEIGHT)

    def test_weight_clamps_to_range(self):
        """Weight never exceeds MAX_WEIGHT or goes below MIN_WEIGHT."""
        # Many perfect predictions
        for i in range(30):
            self.store.record_forecast("m", "c", f"M{i}", float(i % 2))
            self.store.resolve_outcome(f"M{i}", outcome=i % 2)
        weight = self.store.get_weight("m", "c")
        self.assertGreaterEqual(weight, MIN_WEIGHT)
        self.assertLessEqual(weight, MAX_WEIGHT)


# ══════════════════════════════════════════════════════════════════════════
# §6 API smoke tests (via TestClient if available)
# ══════════════════════════════════════════════════════════════════════════


class TestMetricsAPI(unittest.TestCase):
    """Smoke tests for the metrics API endpoints."""

    def test_forecasters_endpoint_importable(self):
        """The API module imports without error."""
        from web.api.kalshi_metrics_api import router
        self.assertEqual(router.prefix, "/api/v1/kalshi/metrics")

    def test_manual_resolve_model(self):
        """ManualResolveRequest model validates."""
        from web.api.kalshi_metrics_api import ManualResolveRequest
        req = ManualResolveRequest(market_id="MKT1", outcome=1)
        self.assertEqual(req.market_id, "MKT1")
        self.assertEqual(req.outcome, 1)


if __name__ == "__main__":
    unittest.main()
