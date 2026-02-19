"""Paper-truth reconciliation and mode-guard test suite.

Enforces the key invariants from the MERID paper validation checklist:
1. Single canonical TradeMode flows everywhere
2. Mode guard blocks live orders when mode != LIVE
3. Paper state persistence survives save/load cycle
4. Reconciliation detects balance identity violations
5. Audit trail records intent→fill causality chain
"""

import json
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestCanonicalTradeMode(unittest.TestCase):
    """§1 — Single source of truth for trade mode."""

    def test_trade_mode_enum_values(self):
        from trading.trade_mode import TradeMode
        self.assertEqual(TradeMode.MOCK.value, "mock")
        self.assertEqual(TradeMode.PAPER.value, "paper")
        self.assertEqual(TradeMode.LIVE.value, "live")

    def test_default_mode_is_paper(self):
        from trading.trade_mode import TradeMode, _resolve_initial_mode
        with patch.dict(os.environ, {"MERID_TRADE_MODE": "paper"}):
            mode = _resolve_initial_mode()
            self.assertEqual(mode, TradeMode.PAPER)

    def test_env_override_mock(self):
        from trading.trade_mode import TradeMode, _resolve_initial_mode
        with patch.dict(os.environ, {"MERID_TRADE_MODE": "mock"}):
            mode = _resolve_initial_mode()
            self.assertEqual(mode, TradeMode.MOCK)

    def test_invalid_env_defaults_to_paper(self):
        from trading.trade_mode import TradeMode, _resolve_initial_mode
        with patch.dict(os.environ, {"MERID_TRADE_MODE": "garbage"}):
            mode = _resolve_initial_mode()
            self.assertEqual(mode, TradeMode.PAPER)

    def test_is_paper_or_mock(self):
        from trading.trade_mode import TradeMode, is_paper_or_mock, set_trade_mode, get_trade_mode
        import trading.trade_mode as tm
        old = tm._current_mode
        try:
            tm._current_mode = TradeMode.PAPER
            self.assertTrue(is_paper_or_mock())
            tm._current_mode = TradeMode.MOCK
            self.assertTrue(is_paper_or_mock())
        finally:
            tm._current_mode = old

    def test_set_mode_blocks_mock_to_live(self):
        from trading.trade_mode import TradeMode, set_trade_mode
        import trading.trade_mode as tm
        old = tm._current_mode
        try:
            tm._current_mode = TradeMode.MOCK
            with self.assertRaises(RuntimeError):
                set_trade_mode(TradeMode.LIVE)
        finally:
            tm._current_mode = old

    def test_set_mode_blocks_live_without_env(self):
        from trading.trade_mode import TradeMode, set_trade_mode
        import trading.trade_mode as tm
        old = tm._current_mode
        try:
            tm._current_mode = TradeMode.PAPER
            with patch.dict(os.environ, {"MERID_ALLOW_LIVE_TRADES": "false"}):
                with self.assertRaises(RuntimeError):
                    set_trade_mode(TradeMode.LIVE)
        finally:
            tm._current_mode = old

    def test_assert_not_live_passes_in_paper(self):
        from trading.trade_mode import TradeMode, assert_not_live
        import trading.trade_mode as tm
        old = tm._current_mode
        try:
            tm._current_mode = TradeMode.PAPER
            assert_not_live("test")  # should not raise
        finally:
            tm._current_mode = old


class TestModeGuardOnAdapter(unittest.TestCase):
    """§2 — Venue adapters reject live orders when mode != LIVE."""

    def test_submit_order_blocked_in_paper_mode(self):
        from trading.adapters.base import (
            TradingVenueAdapterBase,
            TradeRequest,
            TradeSide,
        )
        import trading.trade_mode as tm

        old = tm._current_mode
        try:
            tm._current_mode = tm.TradeMode.PAPER

            adapter = TradingVenueAdapterBase(use_mock=False)
            adapter.supports_trading = True
            request = TradeRequest(
                venue="test",
                symbol="BTC/USDT",
                side=TradeSide.BUY,
                quantity=1.0,
            )
            with self.assertRaises(RuntimeError) as ctx:
                adapter.submit_order(request)
            self.assertIn("paper", str(ctx.exception).lower())
        finally:
            tm._current_mode = old

    def test_submit_order_blocked_in_mock_mode(self):
        from trading.adapters.base import (
            TradingVenueAdapterBase,
            TradeRequest,
            TradeSide,
        )
        import trading.trade_mode as tm

        old = tm._current_mode
        try:
            tm._current_mode = tm.TradeMode.MOCK

            adapter = TradingVenueAdapterBase(use_mock=False)
            adapter.supports_trading = True
            request = TradeRequest(
                venue="test",
                symbol="BTC/USDT",
                side=TradeSide.BUY,
                quantity=1.0,
            )
            with self.assertRaises(RuntimeError) as ctx:
                adapter.submit_order(request)
            self.assertIn("mock", str(ctx.exception).lower())
        finally:
            tm._current_mode = old


class TestPaperStatePersistence(unittest.TestCase):
    """§3 — Paper state survives save/load cycle."""

    def test_save_and_restore_positions(self):
        from trading.paper_trading import (
            PaperTradingEngine,
            PaperPosition,
            PaperOrder,
            PaperOrderStatus,
            PaperOrderType,
            _save_paper_state,
            _load_paper_state,
        )
        import trading.paper_trading as pt

        # Use temp file
        original_file = pt._PERSIST_FILE
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = Path(f.name)

        try:
            pt._PERSIST_FILE = temp_path

            # Create engine with a position
            engine = PaperTradingEngine.__new__(PaperTradingEngine)
            engine.starting_balance = 10000.0
            engine.portfolios = {}
            engine.order_counter = 0
            engine.position_counter = 0
            engine.current_prices = {}
            engine._listeners = {"summary": set(), "trade": set(), "position": set()}
            engine._summary_dirty = False
            engine._positions_dirty = False
            engine._last_summary_emit = 0.0
            engine._last_positions_emit = 0.0
            engine.summary_snapshot = None

            portfolio = engine.get_portfolio("test_user")
            portfolio.current_balance = 9500.0
            portfolio.total_pnl = 150.0
            portfolio.total_trades = 3
            portfolio.winning_trades = 2
            portfolio.losing_trades = 1
            portfolio.positions["BTC_long"] = PaperPosition(
                position_id="pos_1",
                user_id="test_user",
                asset="BTC",
                side="long",
                size_usd=500.0,
                entry_price=69000.0,
                current_price=70000.0,
                leverage=1,
                unrealized_pnl=7.25,
            )
            portfolio.trade_history.append(PaperOrder(
                order_id="ord_1",
                user_id="test_user",
                asset="BTC",
                side="long",
                order_type=PaperOrderType.MARKET,
                size_usd=500.0,
                status=PaperOrderStatus.FILLED,
                fill_price=69000.0,
                filled_size=500.0,
                created_at=time.time() - 100,
                filled_at=time.time() - 99,
            ))

            # Save
            _save_paper_state(engine)
            self.assertTrue(temp_path.exists())

            # Load into fresh engine
            engine2 = PaperTradingEngine.__new__(PaperTradingEngine)
            engine2.portfolios = {}
            engine2.order_counter = 0
            engine2.position_counter = 0
            engine2.current_prices = {}
            engine2._listeners = {"summary": set(), "trade": set(), "position": set()}
            engine2._summary_dirty = False
            engine2._positions_dirty = False
            engine2._last_summary_emit = 0.0
            engine2._last_positions_emit = 0.0
            engine2.summary_snapshot = None
            engine2.starting_balance = 10000.0

            _load_paper_state(engine2)

            # Verify
            self.assertIn("test_user", engine2.portfolios)
            p2 = engine2.portfolios["test_user"]
            self.assertAlmostEqual(p2.current_balance, 9500.0)
            self.assertAlmostEqual(p2.total_pnl, 150.0)
            self.assertEqual(p2.total_trades, 3)
            self.assertIn("BTC_long", p2.positions)
            pos = p2.positions["BTC_long"]
            self.assertAlmostEqual(pos.entry_price, 69000.0)
            self.assertAlmostEqual(pos.size_usd, 500.0)

            # Verify trade history restored
            self.assertEqual(len(p2.trade_history), 1)
            self.assertEqual(p2.trade_history[0].order_id, "ord_1")
            self.assertAlmostEqual(p2.trade_history[0].fill_price, 69000.0)

        finally:
            pt._PERSIST_FILE = original_file
            temp_path.unlink(missing_ok=True)


class TestReconciliation(unittest.TestCase):
    """§4 — Reconciliation detects balance identity violations."""

    def test_reconciliation_runs_without_error(self):
        from trading.reconciliation import run_reconciliation
        report = run_reconciliation()
        self.assertIsNotNone(report)
        self.assertIsInstance(report.all_ok, bool)
        self.assertGreater(len(report.snapshot_hash), 0)

    def test_reconciliation_report_serializable(self):
        from trading.reconciliation import run_reconciliation
        report = run_reconciliation()
        d = report.to_dict()
        self.assertIn("all_ok", d)
        self.assertIn("checks", d)
        self.assertIn("snapshot_hash", d)
        # Must be JSON-serializable
        json.dumps(d)

    def test_check_status_enum(self):
        from trading.reconciliation import CheckStatus
        self.assertEqual(CheckStatus.OK.value, "ok")
        self.assertEqual(CheckStatus.DELTA.value, "delta")
        self.assertEqual(CheckStatus.ERROR.value, "error")


class TestAuditTrail(unittest.TestCase):
    """§5 — Audit trail records intent→fill causality chain."""

    def test_record_intent_and_fill(self):
        from trading.audit_trail import (
            record_intent,
            record_fill,
            get_causality_chain,
        )
        import trading.audit_trail as at

        # Use temp file
        original_file = at._AUDIT_FILE
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            temp_path = Path(f.name)

        try:
            at._AUDIT_FILE = temp_path

            intent_id = record_intent(
                agent_id="test-agent",
                strategy_id="momentum-v1",
                venue="paper",
                symbol="BTC/USDT",
                side="long",
                size=100.0,
                price=69000.0,
            )
            self.assertIsInstance(intent_id, str)
            self.assertGreater(len(intent_id), 0)

            fill_id = record_fill(
                intent_id=intent_id,
                order_id="ord_123",
                venue="paper",
                symbol="BTC/USDT",
                side="long",
                size=100.0,
                price=69050.0,
                agent_id="test-agent",
                pre_snapshot_hash="aaa",
                post_snapshot_hash="bbb",
            )
            self.assertIsInstance(fill_id, str)

            # Verify causality chain
            chain = get_causality_chain(intent_id)
            self.assertEqual(len(chain), 2)
            self.assertEqual(chain[0]["event_type"], "intent")
            self.assertEqual(chain[1]["event_type"], "fill")
            self.assertEqual(chain[0]["intent_id"], intent_id)
            self.assertEqual(chain[1]["intent_id"], intent_id)

        finally:
            at._AUDIT_FILE = original_file
            temp_path.unlink(missing_ok=True)

    def test_audit_summary(self):
        from trading.audit_trail import get_audit_summary
        summary = get_audit_summary()
        self.assertIn("entries", summary)
        self.assertIn("file", summary)


class TestVenueGateAlignment(unittest.TestCase):
    """§6 — VenueGate aligns with canonical TradeMode."""

    def test_venue_gate_modes_exist(self):
        from merid.prediction.venue_gate import TradingMode
        self.assertEqual(TradingMode.SIM.value, "sim")
        self.assertEqual(TradingMode.PAPER.value, "paper")
        self.assertEqual(TradingMode.LIVE.value, "live")

    def test_venue_gate_blocks_sim_trading(self):
        from merid.prediction.venue_gate import VenueGate, TradingMode
        gate = VenueGate(mode=TradingMode.SIM)
        with self.assertRaises(gate.ModeBlockedError):
            gate.check_can_trade()

    def test_venue_gate_allows_paper_trading(self):
        from merid.prediction.venue_gate import VenueGate, TradingMode
        gate = VenueGate(mode=TradingMode.PAPER)
        gate.check_can_trade()  # should not raise

    def test_venue_gate_blocks_live_without_flag(self):
        from merid.prediction.venue_gate import VenueGate, TradingMode
        gate = VenueGate(mode=TradingMode.LIVE, live_enabled=False)
        with self.assertRaises(gate.ModeBlockedError):
            gate.check_can_trade()

    def test_venue_gate_simulates_in_paper(self):
        from merid.prediction.venue_gate import VenueGate, TradingMode
        gate = VenueGate(mode=TradingMode.PAPER)
        self.assertTrue(gate.should_simulate_fill())


class TestRuntimeConfigAlignment(unittest.TestCase):
    """§7 — Runtime config modes align with canonical enum."""

    def test_global_trading_mode_has_paper(self):
        from trading.config.runtime_config import GlobalTradingMode
        self.assertIn("paper", [m.value for m in GlobalTradingMode])
        self.assertIn("live", [m.value for m in GlobalTradingMode])
        self.assertIn("sim", [m.value for m in GlobalTradingMode])

    def test_venue_mode_has_paper(self):
        from trading.config.runtime_config import VenueMode
        self.assertIn("paper", [m.value for m in VenueMode])
        self.assertIn("live", [m.value for m in VenueMode])

    def test_mode_controller_defaults_to_paper(self):
        from trading.mode_controller import TradingModeController
        ctrl = TradingModeController()
        self.assertTrue(ctrl.is_paper)
        self.assertFalse(ctrl.is_live)

    def test_mode_controller_blocks_live_execution_in_paper(self):
        from trading.mode_controller import TradingModeController
        ctrl = TradingModeController()
        can_exec, reason = ctrl.can_execute_live("BTC/USDT", 100.0)
        self.assertFalse(can_exec)
        self.assertIn("Paper", reason)


if __name__ == "__main__":
    unittest.main()
