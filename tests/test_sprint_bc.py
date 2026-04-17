"""Sprint B+C invariant tests.

Tests cover every deliverable added in Sprint B and C:
  B2 – responsible_trading.py snapshot dataclass
  B3 – WS save_snapshot / load_snapshot round-trip
  B7 – StopLossConfig.profit_target_pct take-profit path
  B8 – _normalize_agent exposes brier_score + calibration_error
  B9 – social_broadcaster routes kalshi:consensus_decision
  C1 – naive_50_50_strategy / naive_momentum_strategy baseline helpers
  C2 – run_multi_category_backtest structure
  C4 – canary-trade endpoint guard (no live call) via kalshi_grid_api router
  C7 – ProbAccuracyTracker round-trip and family_report accuracy
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# B2 – Responsible Trading Snapshot
# ──────────────────────────────────────────────────────────────────────────────

class TestResponsibleTradingSnapshot(unittest.TestCase):
    """B2: ResponsibleTradingSnapshot.to_dict() returns expected keys."""

    def test_to_dict_all_keys_present(self):
        from merid.event_venues.kalshi.responsible_trading import ResponsibleTradingSnapshot
        snap = ResponsibleTradingSnapshot(
            balance_cents=10000,
            portfolio_value_cents=1000,
            available_funds_cents=9000,
            merid_daily_loss_limit_usd=50.0,
            merid_max_position_usd=500.0,
            merid_kill_switch_active=False,
            merid_current_daily_pnl_usd=-2.5,
        )
        d = snap.to_dict()
        for key in (
            "balance_usd",
            "portfolio_value_usd",
            "available_funds_usd",
            "merid_daily_loss_limit_usd",
            "merid_max_position_usd",
            "merid_kill_switch_active",
            "merid_current_daily_pnl_usd",
            "venue_loss_limit_set",
            "venue_deposit_limit_set",
            "venue_cool_off_active",
        ):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_balance_value_preserved(self):
        from merid.event_venues.kalshi.responsible_trading import ResponsibleTradingSnapshot
        snap = ResponsibleTradingSnapshot(balance_cents=12345)
        self.assertAlmostEqual(snap.to_dict()["balance_usd"], 123.45)


# ──────────────────────────────────────────────────────────────────────────────
# B3 – WS Orderbook Snapshot
# ──────────────────────────────────────────────────────────────────────────────

class TestWSOrderbookSnapshot(unittest.TestCase):
    """B3: save_snapshot/load_snapshot round-trip via temp file."""

    def _make_ws_client(self, tmp_path: str):
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        client = KalshiWebSocket.__new__(KalshiWebSocket)
        # Minimal attribute init
        client._ob_snapshots = {}
        client._ob_initialised = set()
        client._last_seq = {}
        client._SNAPSHOT_PATH = os.path.join(tmp_path, "ob_snapshot.json")
        return client

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._make_ws_client(tmp)
            ws._ob_snapshots = {"KXBTC-T": {"bids": [[50, 10]], "asks": [[51, 5]]}}
            ws._last_seq = {"KXBTC-T": 42}
            ws.save_snapshot()

            ws2 = self._make_ws_client(tmp)
            ws2._SNAPSHOT_PATH = ws._SNAPSHOT_PATH
            n = ws2.load_snapshot(max_age_seconds=300)
            self.assertEqual(n, 1)
            self.assertIn("KXBTC-T", ws2._ob_snapshots)

    def test_load_stale_returns_zero(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._make_ws_client(tmp)
            ws._ob_snapshots = {"STALE": {}}
            ws.save_snapshot()
            # Manually backdate the snapshot
            with open(ws._SNAPSHOT_PATH) as f:
                data = json.load(f)
            data["ts"] -= 9999
            with open(ws._SNAPSHOT_PATH, "w") as f:
                json.dump(data, f)

            ws2 = self._make_ws_client(tmp)
            ws2._SNAPSHOT_PATH = ws._SNAPSHOT_PATH
            n = ws2.load_snapshot(max_age_seconds=60)
            self.assertEqual(n, 0)

    def test_load_missing_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._make_ws_client(tmp)
            ws._SNAPSHOT_PATH = os.path.join(tmp, "nonexistent.json")
            self.assertEqual(ws.load_snapshot(), 0)

    def test_save_skips_empty_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._make_ws_client(tmp)
            ws._ob_snapshots = {}
            ws.save_snapshot()
            self.assertFalse(os.path.exists(ws._SNAPSHOT_PATH))


# ──────────────────────────────────────────────────────────────────────────────
# B7 – profit_target_pct take-profit
# ──────────────────────────────────────────────────────────────────────────────

class TestProfitTargetPct(unittest.TestCase):
    """B7: percentage-based take-profit fires before absolute-cents check."""

    def _make_pos(self, entry_cents: int, current_cents: int, contracts: int = 10):
        import time
        from merid.event_venues.kalshi.stop_loss import TrackedPosition
        return TrackedPosition(
            position_id="test-001",
            ticker="KXBTC-TEST",
            side="yes",
            entry_price_cents=entry_cents,
            contracts=contracts,
            entry_ts=time.time(),
            current_price_cents=current_cents,
        )

    def _make_rules(self, **cfg_kwargs):
        from merid.event_venues.kalshi.stop_loss import StopLossRules, StopLossConfig
        cfg = StopLossConfig(**cfg_kwargs)
        return StopLossRules(config=cfg)

    def test_profit_target_pct_fires(self):
        rules = self._make_rules(profit_target_pct=0.40)
        pos = self._make_pos(entry_cents=50, current_cents=75)  # +50% gain
        action = rules.check_position(pos)
        self.assertTrue(action.should_close)
        self.assertIn("Take-profit", action.reason)

    def test_profit_target_pct_no_fire_below_threshold(self):
        rules = self._make_rules(profit_target_pct=0.40)
        pos = self._make_pos(entry_cents=50, current_cents=55)  # +10% gain
        action = rules.check_position(pos)
        # should NOT close for take-profit (10% < 40% target)
        if action.should_close:
            self.assertNotIn("Take-profit", action.reason)

    def test_profit_target_pct_field_exists(self):
        from merid.event_venues.kalshi.stop_loss import StopLossConfig
        cfg = StopLossConfig()
        self.assertTrue(hasattr(cfg, "profit_target_pct"))
        self.assertEqual(cfg.profit_target_pct, 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# B8 – _normalize_agent exposes Brier + calibration error
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeAgentBrier(unittest.TestCase):
    """B8: _normalize_agent passes brier_score and calibration_error through."""

    def test_brier_fields_present(self):
        from web.api.kalshi_grid_api import _normalize_agent
        raw = {
            "name": "btc_1h",
            "enabled": True,
            "running": True,
            "performance": {
                "brier_score": 0.123,
                "calibration_error": 0.045,
            },
        }
        result = _normalize_agent(raw)
        self.assertIn("brier_score", result)
        self.assertIn("calibration_error", result)
        self.assertAlmostEqual(result["brier_score"], 0.123, places=3)
        self.assertAlmostEqual(result["calibration_error"], 0.045, places=3)

    def test_brier_defaults_to_zero(self):
        from web.api.kalshi_grid_api import _normalize_agent
        raw = {"name": "eth_4h", "performance": {}}
        result = _normalize_agent(raw)
        self.assertEqual(result["brier_score"], 0.0)
        self.assertEqual(result["calibration_error"], 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# B9 – social_broadcaster routes kalshi:consensus_decision
# ──────────────────────────────────────────────────────────────────────────────

class TestSocialBroadcasterConsensusEvent(unittest.TestCase):
    """B9: kalshi:consensus_decision is in WATCHED_EVENTS and dispatches."""

    def test_watched_events_contains_consensus(self):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster
        self.assertIn("kalshi:consensus_decision", KalshiSocialBroadcaster.WATCHED_EVENTS)

    def test_dispatch_calls_publish_consensus(self):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster
        broadcaster = KalshiSocialBroadcaster.__new__(KalshiSocialBroadcaster)
        broadcaster._telegram = None
        broadcaster._discord = None

        called = []
        async def fake_publish(payload):
            called.append(payload)

        broadcaster._publish_consensus_decision = fake_publish
        payload = {
            "ticker": "KXBTC-T",
            "stance": "YES",
            "edge": 0.12,
            "swarm_prob": 0.63,
            "confidence": 0.8,
            "n_agents": 3,
            "sentiment": "bullish",
        }
        asyncio.get_event_loop().run_until_complete(
            broadcaster._dispatch("kalshi:consensus_decision", payload)
        )
        self.assertEqual(len(called), 1)


# ──────────────────────────────────────────────────────────────────────────────
# C1 – Naive baseline strategies
# ──────────────────────────────────────────────────────────────────────────────

class TestNaiveBaselineStrategies(unittest.TestCase):
    """C1: naive_50_50 and naive_momentum produce float lists."""

    def _candles(self, n: int = 20) -> List[Dict[str, Any]]:
        return [{"close": 50 + i, "open": 49 + i, "high": 52 + i, "low": 48 + i} for i in range(n)]

    def test_naive_50_50_returns_list_of_floats(self):
        from merid.backtesting.kalshi_backtest import naive_50_50_strategy
        candles = self._candles(20)
        probs = naive_50_50_strategy(candles)
        self.assertEqual(len(probs), 20)
        # Each value is a return (close/open - 1), should be finite floats
        for p in probs:
            self.assertIsInstance(p, float)

    def test_naive_momentum_returns_list_in_range(self):
        from merid.backtesting.kalshi_backtest import naive_momentum_strategy
        candles = self._candles(20)
        probs = naive_momentum_strategy(candles)
        self.assertEqual(len(probs), 20)
        for p in probs:
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    def test_run_baseline_comparison_returns_dict(self):
        from merid.backtesting.kalshi_backtest import run_baseline_comparison
        from merid.risk.btc_promotion_config import BacktestReport
        candle_data = self._candles(30)
        with patch("merid.backtesting.kalshi_backtest.fetch_kalshi_history", new_callable=AsyncMock) as m:
            m.return_value = candle_data
            result = asyncio.get_event_loop().run_until_complete(
                run_baseline_comparison("TEST-TICKER", years=2)
            )
        self.assertIn("naive_50_50", result)
        self.assertIn("naive_momentum", result)


# ──────────────────────────────────────────────────────────────────────────────
# C2 – Multi-category batch backtest
# ──────────────────────────────────────────────────────────────────────────────

class TestMultiCategoryBacktest(unittest.TestCase):
    """C2: run_multi_category_backtest returns expected structure."""

    def test_summary_key_present(self):
        from merid.backtesting.kalshi_backtest import run_multi_category_backtest
        from merid.risk.btc_promotion_config import BacktestReport
        fake_report = BacktestReport(
            equity_curve=[1.0, 1.1], returns=[0.1],
            max_drawdown=0.05, sharpe=1.0, trades=5, years=2,
        )
        strategy_fn = MagicMock(return_value=[0.6] * 10)
        with patch("merid.backtesting.kalshi_backtest.run_backtest_2y", new_callable=AsyncMock) as m:
            m.return_value = fake_report
            result = asyncio.get_event_loop().run_until_complete(
                run_multi_category_backtest(
                    strategy_fn=strategy_fn,
                    tickers=["KXBTC-T1", "KXETH-T2"],
                    include_baselines=False,
                )
            )
        self.assertIn("__summary__", result)
        self.assertIn("KXBTC-T1", result)
        self.assertIn("KXETH-T2", result)
        self.assertEqual(result["__summary__"]["tickers_tested"], 2)

    def test_strategy_error_does_not_propagate(self):
        from merid.backtesting.kalshi_backtest import run_multi_category_backtest
        strategy_fn = MagicMock(return_value=[0.5] * 10)
        with patch("merid.backtesting.kalshi_backtest.run_backtest_2y", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("feed unavailable")
            result = asyncio.get_event_loop().run_until_complete(
                run_multi_category_backtest(
                    strategy_fn=strategy_fn,
                    tickers=["FAIL-TICKER"],
                    include_baselines=False,
                )
            )
        self.assertIn("error", result.get("FAIL-TICKER", {}).get("strategy", {}))


# ──────────────────────────────────────────────────────────────────────────────
# C4 – Canary trade endpoint exists
# ──────────────────────────────────────────────────────────────────────────────

class TestCanaryTradeEndpoint(unittest.TestCase):
    """C4: /canary-trade endpoint is registered and returns expected shape."""

    def test_endpoint_registered(self):
        from web.api.kalshi_grid_api import router
        paths = [route.path for route in router.routes]
        canary_paths = [p for p in paths if "canary" in p]
        self.assertTrue(len(canary_paths) > 0, f"No canary route found in {paths}")

    def test_endpoint_returns_error_gracefully(self):
        from web.api.kalshi_grid_api import run_canary_trade
        result = asyncio.get_event_loop().run_until_complete(run_canary_trade())
        # Must always return a dict with 'ok' key
        self.assertIn("ok", result)


# ──────────────────────────────────────────────────────────────────────────────
# C7 – ProbAccuracyTracker
# ──────────────────────────────────────────────────────────────────────────────

class TestProbAccuracyTracker(unittest.TestCase):
    """C7: ProbAccuracyTracker records predictions + outcomes and computes accuracy."""

    def _tracker(self) -> "ProbAccuracyTracker":
        from merid.prediction.prob_accuracy_tracker import ProbAccuracyTracker
        td = tempfile.mkdtemp()
        from pathlib import Path
        return ProbAccuracyTracker(db_path=Path(td) / "test.db")

    def test_empty_report_is_list(self):
        tracker = self._tracker()
        report = tracker.family_report()
        self.assertIsInstance(report, list)

    def test_record_and_resolve_roundtrip(self):
        tracker = self._tracker()
        tracker.record_prediction("KXBTC-T1", model_prob=0.7, market_family="KXBTC")
        tracker.record_outcome("KXBTC-T1", resolved_yes=True, market_family="KXBTC")
        report = tracker.family_report()
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0].family, "KXBTC")
        self.assertAlmostEqual(report[0].mean_abs_error, abs(0.7 - 1.0), places=4)

    def test_brier_score_formula(self):
        tracker = self._tracker()
        tracker.record_prediction("T1", model_prob=0.5)
        tracker.record_outcome("T1", resolved_yes=False)
        report = tracker.family_report()
        # Brier = (0.5 - 0)^2 = 0.25
        self.assertAlmostEqual(report[0].mean_brier, 0.25, places=4)

    def test_to_dict_has_families_key(self):
        tracker = self._tracker()
        d = tracker.to_dict()
        self.assertIn("families", d)
        self.assertIsInstance(d["families"], list)

    def test_well_calibrated_threshold(self):
        tracker = self._tracker()
        # Perfect prediction: prob=1.0, outcome=yes → MAE=0.0
        tracker.record_prediction("PERFECT", model_prob=1.0)
        tracker.record_outcome("PERFECT", resolved_yes=True)
        report = tracker.family_report()
        self.assertTrue(report[0].well_calibrated)

    def test_family_defaults_from_ticker(self):
        tracker = self._tracker()
        tracker.record_prediction("KXETH-24DEC31-B2500", model_prob=0.4)
        tracker.record_outcome("KXETH-24DEC31-B2500", resolved_yes=False)
        report = tracker.family_report()
        self.assertEqual(report[0].family, "KXETH")

    def test_ticker_detail_returns_structure(self):
        tracker = self._tracker()
        tracker.record_prediction("DETAIL-T", model_prob=0.6)
        tracker.record_outcome("DETAIL-T", resolved_yes=True)
        detail = tracker.ticker_detail("DETAIL-T")
        self.assertEqual(detail["ticker"], "DETAIL-T")
        self.assertIsNotNone(detail["outcome"])
        self.assertEqual(len(detail["predictions"]), 1)


# ──────────────────────────────────────────────────────────────────────────────
# C3 – Live-replay mode
# ──────────────────────────────────────────────────────────────────────────────

class TestReplaySession(unittest.TestCase):
    """C3: scripts/replay_session.py — ReplayReport round-trip."""

    def _candles(self, n: int = 20) -> List[Dict[str, Any]]:
        return [
            {"open": 50 + i, "close": 51 + i, "high": 53 + i, "low": 48 + i, "ts": i * 3600.0}
            for i in range(n)
        ]

    def test_run_replay_returns_report(self):
        from scripts.replay_session import run_replay
        candles = self._candles(20)
        report = asyncio.get_event_loop().run_until_complete(
            run_replay("KXBTC-TEST", candles, resolution="1h")
        )
        self.assertEqual(report.ticker, "KXBTC-TEST")
        self.assertEqual(report.bars_replayed, 20)
        self.assertIsInstance(report.signals, list)
        self.assertGreater(len(report.signals), 0)

    def test_replay_report_to_dict(self):
        from scripts.replay_session import run_replay
        candles = self._candles(10)
        report = asyncio.get_event_loop().run_until_complete(
            run_replay("KXETH-TEST", candles)
        )
        d = report.to_dict()
        for key in ("ticker", "bars_replayed", "total_entries", "signals", "elapsed_s"):
            self.assertIn(key, d)

    def test_replay_signal_fields(self):
        from scripts.replay_session import run_replay
        candles = self._candles(5)
        report = asyncio.get_event_loop().run_until_complete(
            run_replay("KXBTC-T", candles)
        )
        if report.signals:
            sig = report.signals[0]
            for attr in ("bar_index", "model_prob", "confidence", "edge", "decision"):
                self.assertTrue(hasattr(sig, attr), f"Missing attr: {attr}")
            self.assertIn(sig.decision, ("enter_yes", "enter_no", "hold"))

    def test_empty_candles_returns_zero_bars(self):
        from scripts.replay_session import run_replay
        report = asyncio.get_event_loop().run_until_complete(
            run_replay("EMPTY", [])
        )
        self.assertEqual(report.bars_replayed, 0)
        self.assertEqual(len(report.signals), 0)


# ──────────────────────────────────────────────────────────────────────────────
# C6 – Perp context snapshot
# ──────────────────────────────────────────────────────────────────────────────

class TestPerpContext(unittest.TestCase):
    """C6: PerpContextSnapshot.to_dict() and to_edge_features() are well-formed."""

    def _stub_snap(self):
        from merid.prediction.perp_context import PerpContextSnapshot, AssetPerpData
        return PerpContextSnapshot(
            btc=AssetPerpData("BTCUSDT", funding_rate=0.0001, mark_price=60000.0, iv_30d=0.55),
            eth=AssetPerpData("ETHUSDT", funding_rate=-0.0002, mark_price=3000.0, iv_30d=0.65),
            source="stub",
        )

    def test_to_dict_keys(self):
        snap = self._stub_snap()
        d = snap.to_dict()
        self.assertIn("btc", d)
        self.assertIn("eth", d)
        self.assertIn("funding_rate", d["btc"])
        self.assertIn("iv_30d", d["eth"])

    def test_to_edge_features_keys(self):
        snap = self._stub_snap()
        feats = snap.to_edge_features()
        for key in (
            "btc_funding_rate", "eth_funding_rate",
            "btc_mark_price", "eth_mark_price",
            "btc_iv_30d", "eth_iv_30d",
        ):
            self.assertIn(key, feats, f"Missing feature: {key}")

    def test_funding_rate_preserved(self):
        snap = self._stub_snap()
        feats = snap.to_edge_features()
        self.assertAlmostEqual(feats["btc_funding_rate"], 0.0001)
        self.assertAlmostEqual(feats["eth_funding_rate"], -0.0002)

    def test_realized_vol_formula(self):
        from merid.prediction.perp_context import _realized_vol_annualised
        # Flat prices → zero vol
        closes = [100.0] * 30
        self.assertAlmostEqual(_realized_vol_annualised(closes), 0.0)

    def test_realized_vol_nonempty(self):
        from merid.prediction.perp_context import _realized_vol_annualised
        closes = [100.0 * (1 + 0.02 * i) for i in range(30)]
        vol = _realized_vol_annualised(closes)
        self.assertGreater(vol, 0.0)

    def test_get_snapshot_returns_stub_on_network_fail(self):
        from merid.prediction.perp_context import PerpContextService
        svc = PerpContextService()
        with patch("merid.prediction.perp_context._fetch_json", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("network down")
            snap = asyncio.get_event_loop().run_until_complete(svc.get_snapshot())
        self.assertEqual(snap.source, "stub")
        self.assertEqual(snap.btc.funding_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
