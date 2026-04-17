"""Unit tests for the platform-wide Fresh Start mode.

Covers:
1. Paper engine reset zeroes state but kill switch is preserved.
2. Execution blocked until first reconciliation completes on fresh start.
3. Consensus store is empty after fresh-start reset.
4. assert_safe_for_fresh_start() blocks LIVE mode.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


class TestFreshStartPaperResetPreservesKillSwitch(unittest.TestCase):
    """Paper engine state is wiped but kill-switch state survives."""

    def test_fresh_start_zeroes_paper_but_preserves_kill_switch(self):
        # ── Arrange: build a paper engine with some state ──
        from trading.paper_trading import PaperTradingEngine

        engine = PaperTradingEngine(starting_balance=50_000.0)
        # Simulate a portfolio with trades
        portfolio = engine.get_portfolio("test-user")
        portfolio.total_trades = 10
        portfolio.winning_trades = 6
        portfolio.losing_trades = 4
        portfolio.total_pnl = 123.45
        engine.order_counter = 42
        engine.position_counter = 7
        engine.total_fees_paid = 9.99

        with tempfile.TemporaryDirectory() as td:
            ks_file = str(Path(td) / "risk_kill_switch.json")
            with mock.patch.dict(os.environ, {"MERID_RISK_KS_FILE": ks_file}):
                # ── Arrange: trigger the kill switch (isolated file — never repo data/) ──
                from merid.risk.kill_switches import RiskController

                rc = RiskController(daily_loss_limit=500.0)
                rc.emergency_stop("unit-test trigger")
                self.assertTrue(rc._global_kill)

                # ── Act: reset the paper engine ──
                engine.reset_state()

                # ── Assert: paper state is zeroed ──
                self.assertEqual(len(engine.portfolios), 0)
                self.assertEqual(engine.order_counter, 0)
                self.assertEqual(engine.position_counter, 0)
                self.assertEqual(engine.total_fees_paid, 0.0)

                # ── Assert: kill switch is still triggered ──
                self.assertTrue(rc._global_kill, "Kill switch must survive a fresh start")

                # ── Act: reset daily counters (what fresh start does) ──
                rc.reset_daily_counters()

                # ── Assert: counters zeroed, kill switch still on ──
                self.assertEqual(rc._daily_pnl, 0.0)
                self.assertEqual(rc._error_count, 0)
                self.assertTrue(rc._global_kill, "Kill switch must survive reset_daily_counters()")


class TestExecutionBlockedUntilFirstReconciliation(unittest.TestCase):
    """Until venue reconciliation runs, has_critical_discrepancies() is fail-closed (True)."""

    def test_execution_blocked_until_first_reconciliation_on_fresh_start(self):
        import merid.reconciliation.venue_reconciler as vr
        from merid.reconciliation import has_critical_discrepancies
        from merid.reconciliation.venue_reconciler import VenuePositionDiscrepancy

        with vr._recon_lock:
            orig_run = vr._reconciliation_has_run
            orig_discs = list(vr._last_discrepancies)
            orig_ts = vr._last_reconciliation_ts

        try:
            with vr._recon_lock:
                vr._reconciliation_has_run = False
                vr._last_discrepancies = []

            with mock.patch("core.fresh_start.is_fresh_start", return_value=True):
                self.assertTrue(
                    has_critical_discrepancies(),
                    "Execution must be blocked before first reconciliation on fresh start",
                )

            with vr._recon_lock:
                vr._reconciliation_has_run = True
                vr._last_discrepancies = []

            with mock.patch("core.fresh_start.is_fresh_start", return_value=True):
                self.assertFalse(
                    has_critical_discrepancies(),
                    "Execution must be unblocked after first clean reconciliation",
                )

            crit = VenuePositionDiscrepancy(
                venue="kalshi",
                symbol="KXTEST-MOCK",
                merid_qty=0.0,
                venue_qty=10.0,
                merid_entry_price=0.0,
                venue_entry_price=0.5,
            )
            with vr._recon_lock:
                vr._last_discrepancies = [crit]

            with mock.patch("core.fresh_start.is_fresh_start", return_value=True):
                self.assertTrue(
                    has_critical_discrepancies(),
                    "Execution must be blocked when reconciliation has critical deltas",
                )
        finally:
            with vr._recon_lock:
                vr._reconciliation_has_run = orig_run
                vr._last_discrepancies = orig_discs
                vr._last_reconciliation_ts = orig_ts


class TestConsensusStoreEmptyOnFreshStart(unittest.TestCase):
    """Consensus store reset_all() empties both tables."""

    def test_consensus_store_empty_on_fresh_start(self):
        import sqlite3
        from core.consensus_store import ConsensusStore

        # Use an in-memory DB so we don't touch real data.
        # Patch _init_db to skip os.makedirs (no dirname for :memory:).
        store = ConsensusStore.__new__(ConsensusStore)
        store._db_path = ":memory:"
        store._lock = threading.Lock()
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        # Keep a persistent connection for the in-memory DB
        store._mem_conn = conn
        store._connect = lambda: conn
        conn.execute(
            "CREATE TABLE IF NOT EXISTS opinions "
            "(id TEXT PRIMARY KEY, agent_id TEXT, agent_name TEXT, role TEXT, "
            "symbol TEXT, stance TEXT, confidence REAL, reasoning TEXT, "
            "horizon TEXT DEFAULT 'short', created_at REAL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS plans "
            "(id TEXT PRIMARY KEY, symbol TEXT, title TEXT, direction TEXT, "
            "target_size_usd REAL, confidence REAL, consensus_score REAL DEFAULT 0, "
            "status TEXT, supporting_agents TEXT DEFAULT '[]', "
            "opposing_agents TEXT DEFAULT '[]', votes_for INTEGER DEFAULT 0, "
            "votes_against INTEGER DEFAULT 0, created_at REAL)"
        )

        # Seed some data
        from core.consensus_store import Opinion, TradePlan
        import time

        store.add_opinion(Opinion(
            agent_id="a1", agent_name="test", role="analyst",
            symbol="BTC-USD", stance="bullish", confidence=0.9,
            reasoning="test", horizon="short", created_at=time.time(),
        ))
        store.add_plan(TradePlan(
            symbol="BTC-USD", title="Buy BTC", direction="long",
            target_size_usd=1000.0, confidence=0.8,
            status="proposed", created_at=time.time(),
        ))

        self.assertGreater(store.opinion_count(), 0)
        self.assertGreater(store.plan_count(), 0)

        # Act
        store.reset_all()

        # Assert
        self.assertEqual(store.opinion_count(), 0, "Opinions must be empty after reset")
        self.assertEqual(store.plan_count(), 0, "Plans must be empty after reset")


class TestAssertSafeForFreshStartBlocksLive(unittest.TestCase):
    """assert_safe_for_fresh_start() raises in LIVE mode."""

    def test_blocks_live_mode(self):
        from core.fresh_start import assert_safe_for_fresh_start
        from trading.trade_mode import TradeMode

        with mock.patch("core.fresh_start.is_fresh_start", return_value=True), \
             mock.patch("trading.trade_mode.get_trade_mode", return_value=TradeMode.LIVE):
            with self.assertRaises(RuntimeError) as ctx:
                assert_safe_for_fresh_start()
            self.assertIn("LIVE", str(ctx.exception))

    def test_allows_paper_mode(self):
        from core.fresh_start import assert_safe_for_fresh_start
        from trading.trade_mode import TradeMode

        with mock.patch("core.fresh_start.is_fresh_start", return_value=True), \
             mock.patch("trading.trade_mode.get_trade_mode", return_value=TradeMode.PAPER):
            # Should not raise
            assert_safe_for_fresh_start()

    def test_allows_mock_mode(self):
        from core.fresh_start import assert_safe_for_fresh_start
        from trading.trade_mode import TradeMode

        with mock.patch("core.fresh_start.is_fresh_start", return_value=True), \
             mock.patch("trading.trade_mode.get_trade_mode", return_value=TradeMode.MOCK):
            # Should not raise
            assert_safe_for_fresh_start()

    def test_noop_when_not_fresh_start(self):
        from core.fresh_start import assert_safe_for_fresh_start

        with mock.patch("core.fresh_start.is_fresh_start", return_value=False):
            # Should not raise regardless of mode
            assert_safe_for_fresh_start()


if __name__ == "__main__":
    unittest.main()
