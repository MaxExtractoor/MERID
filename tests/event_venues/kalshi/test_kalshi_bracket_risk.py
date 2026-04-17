"""Tests for Kalshi Bracket Risk Rules."""

import pytest

from merid.event_venues.kalshi.bracket_risk import (
    BracketOrder,
    BracketRiskConfig,
    BracketRiskManager,
    BracketState,
    DEFAULT_BRACKET_RISK_CONFIG,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _order(
    bracket_id: str = "b1",
    ticker: str = "KXBTC-H-55-60",
    underlying: str = "BTC",
    hour_key: str = "2026-02-16T03",
    side: str = "sell",
    contracts: int = 5,
    price_cents: int = 55,
    max_loss_cents: float = 500.0,
) -> BracketOrder:
    return BracketOrder(
        bracket_id=bracket_id,
        ticker=ticker,
        underlying=underlying,
        hour_key=hour_key,
        side=side,
        contracts=contracts,
        price_cents=price_cents,
        max_loss_cents=max_loss_cents,
    )


# ── Pre-trade checks ─────────────────────────────────────────────────

class TestPreTradeChecks:
    def test_order_passes_all_checks(self):
        mgr = BracketRiskManager()
        ok, reason = mgr.check_bracket_order(_order())
        assert ok is True
        assert reason == "OK"

    def test_halted_blocks_order(self):
        mgr = BracketRiskManager()
        mgr._state.halted = True
        mgr._state.halt_reason = "test"
        ok, reason = mgr.check_bracket_order(_order())
        assert ok is False
        assert "halted" in reason.lower()

    def test_max_open_brackets(self):
        cfg = BracketRiskConfig(max_open_brackets=2)
        mgr = BracketRiskManager(cfg)
        mgr._state.open_brackets = {"b1", "b2"}
        ok, reason = mgr.check_bracket_order(_order(bracket_id="b3"))
        assert ok is False
        assert "open brackets" in reason.lower()

    def test_per_bracket_loss_pct_cap(self):
        cfg = BracketRiskConfig(max_loss_per_contract_pct=0.1)
        mgr = BracketRiskManager(cfg)
        # 5 contracts × 0.1% of 500000c = 2500c allowed, order has 5000c loss
        order = _order(contracts=5, max_loss_cents=5000.0)
        ok, reason = mgr.check_bracket_order(order, session_equity_cents=500_000)
        assert ok is False
        assert "equity cap" in reason.lower()

    def test_per_bracket_absolute_loss_cap(self):
        cfg = BracketRiskConfig(max_loss_per_bracket_cents=200.0)
        mgr = BracketRiskManager(cfg)
        ok, reason = mgr.check_bracket_order(_order(max_loss_cents=300.0))
        assert ok is False
        assert "absolute cap" in reason.lower()

    def test_contracts_per_hour_cap(self):
        cfg = BracketRiskConfig(max_contracts_per_hour=10)
        mgr = BracketRiskManager(cfg)
        mgr._state.contracts_by_hour["2026-02-16T03"] = 8
        ok, reason = mgr.check_bracket_order(_order(contracts=5))
        assert ok is False
        assert "contracts" in reason.lower()

    def test_notional_per_hour_cap(self):
        cfg = BracketRiskConfig(max_notional_per_hour_cents=1000.0)
        mgr = BracketRiskManager(cfg)
        mgr._state.notional_by_hour["2026-02-16T03"] = 800.0
        ok, reason = mgr.check_bracket_order(_order(contracts=5, price_cents=55))
        assert ok is False
        assert "notional" in reason.lower()

    def test_unhedged_delta_cap(self):
        cfg = BracketRiskConfig(max_unhedged_delta=10)
        mgr = BracketRiskManager(cfg)
        mgr._state.net_delta = 8
        ok, reason = mgr.check_bracket_order(_order(side="buy", contracts=5))
        assert ok is False
        assert "delta" in reason.lower()

    def test_sell_reduces_delta(self):
        cfg = BracketRiskConfig(max_unhedged_delta=10)
        mgr = BracketRiskManager(cfg)
        mgr._state.net_delta = 8
        ok, reason = mgr.check_bracket_order(_order(side="sell", contracts=5))
        assert ok is True  # net_delta goes to 3


# ── Recording ─────────────────────────────────────────────────────────

class TestRecording:
    def test_record_bracket_open(self):
        mgr = BracketRiskManager()
        order = _order()
        mgr.record_bracket_open(order)
        assert "b1" in mgr.state.open_brackets
        assert mgr.state.total_brackets == 1
        assert mgr.state.contracts_by_hour["2026-02-16T03"] == 5

    def test_record_winning_result(self):
        mgr = BracketRiskManager()
        mgr.record_bracket_open(_order())
        mgr.record_bracket_result("b1", pnl_cents=100.0, hour_key="2026-02-16T03")
        assert mgr.state.winning_brackets == 1
        assert mgr.state.consecutive_losers == 0
        assert "b1" not in mgr.state.open_brackets

    def test_record_losing_result(self):
        mgr = BracketRiskManager()
        mgr.record_bracket_open(_order())
        mgr.record_bracket_result("b1", pnl_cents=-200.0, hour_key="2026-02-16T03")
        assert mgr.state.losing_brackets == 1
        assert mgr.state.consecutive_losers == 1

    def test_delta_tracking(self):
        mgr = BracketRiskManager()
        mgr.record_bracket_open(_order(side="buy", contracts=10))
        assert mgr.state.net_delta == 10
        mgr.record_bracket_open(_order(bracket_id="b2", side="sell", contracts=3))
        assert mgr.state.net_delta == 7

    def test_hour_cleanup_on_result(self):
        mgr = BracketRiskManager()
        mgr.record_bracket_open(_order())
        mgr.record_bracket_result("b1", pnl_cents=50.0, hour_key="2026-02-16T03")
        # Hour should be cleaned up since no more brackets
        assert "2026-02-16T03" not in mgr.state.open_by_hour

    def test_hour_expired_cleanup(self):
        mgr = BracketRiskManager()
        mgr.record_bracket_open(_order())
        mgr.record_bracket_open(_order(bracket_id="b2"))
        mgr.record_hour_expired("2026-02-16T03")
        assert "2026-02-16T03" not in mgr.state.contracts_by_hour
        assert len(mgr.state.open_brackets) == 0


# ── Consecutive loser kill-switch ────────────────────────────────────

class TestConsecutiveLoserKillSwitch:
    def test_halt_after_n_losers(self):
        cfg = BracketRiskConfig(max_consecutive_losers=3)
        mgr = BracketRiskManager(cfg)
        for i in range(3):
            mgr.record_bracket_result(f"b{i}", pnl_cents=-100.0)
        assert mgr.halted
        assert "consecutive" in mgr.state.halt_reason.lower()

    def test_no_halt_below_threshold(self):
        cfg = BracketRiskConfig(max_consecutive_losers=3)
        mgr = BracketRiskManager(cfg)
        mgr.record_bracket_result("b1", pnl_cents=-100.0)
        mgr.record_bracket_result("b2", pnl_cents=-100.0)
        assert not mgr.halted

    def test_winner_resets_counter(self):
        cfg = BracketRiskConfig(max_consecutive_losers=3)
        mgr = BracketRiskManager(cfg)
        mgr.record_bracket_result("b1", pnl_cents=-100.0)
        mgr.record_bracket_result("b2", pnl_cents=-100.0)
        mgr.record_bracket_result("b3", pnl_cents=50.0)  # win resets
        mgr.record_bracket_result("b4", pnl_cents=-100.0)
        assert not mgr.halted
        assert mgr.state.consecutive_losers == 1

    def test_halt_blocks_new_orders(self):
        cfg = BracketRiskConfig(max_consecutive_losers=1)
        mgr = BracketRiskManager(cfg)
        mgr.record_bracket_result("b1", pnl_cents=-100.0)
        assert mgr.halted
        ok, _ = mgr.check_bracket_order(_order())
        assert ok is False

    def test_reset_halt(self):
        cfg = BracketRiskConfig(max_consecutive_losers=1)
        mgr = BracketRiskManager(cfg)
        mgr.record_bracket_result("b1", pnl_cents=-100.0)
        assert mgr.halted
        mgr.reset_halt()
        assert not mgr.halted
        ok, _ = mgr.check_bracket_order(_order())
        assert ok is True


# ── Cross-bracket correlation ────────────────────────────────────────

class TestCrossBracketCorrelation:
    def test_overlapping_brackets_share_hour_limit(self):
        cfg = BracketRiskConfig(max_contracts_per_hour=20)
        mgr = BracketRiskManager(cfg)
        # Two brackets on same hour
        mgr.record_bracket_open(_order(bracket_id="b1", contracts=10))
        mgr.record_bracket_open(_order(bracket_id="b2", contracts=8))
        # Third bracket would exceed 20
        ok, reason = mgr.check_bracket_order(_order(bracket_id="b3", contracts=5))
        assert ok is False

    def test_different_hours_independent(self):
        cfg = BracketRiskConfig(max_contracts_per_hour=20)
        mgr = BracketRiskManager(cfg)
        mgr.record_bracket_open(_order(bracket_id="b1", hour_key="2026-02-16T03", contracts=15))
        # Different hour — should pass
        ok, reason = mgr.check_bracket_order(
            _order(bracket_id="b2", hour_key="2026-02-16T04", contracts=15)
        )
        assert ok is True


# ── Summary ──────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_structure(self):
        mgr = BracketRiskManager()
        s = mgr.summary()
        assert "halted" in s
        assert "open_brackets" in s
        assert "win_rate_pct" in s
        assert "net_delta" in s
        assert "config" in s
        assert "max_consecutive_losers" in s["config"]

    def test_summary_with_data(self):
        mgr = BracketRiskManager()
        mgr.record_bracket_open(_order())
        mgr.record_bracket_result("b1", pnl_cents=100.0)
        s = mgr.summary()
        assert s["total_brackets"] == 1
        assert s["winning_brackets"] == 1
        assert s["total_pnl_usd"] == 1.0
