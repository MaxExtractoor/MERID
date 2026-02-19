"""Tests for Kalshi Stop-Loss Rules for Binary Contracts."""

import time
from unittest.mock import patch

import pytest

from merid.event_venues.kalshi.stop_loss import (
    DEFAULT_STOP_LOSS_CONFIG,
    StopAction,
    StopLossConfig,
    StopLossRules,
    TrackedPosition,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _pos(
    position_id: str = "p1",
    ticker: str = "KXBTC-H-55-60",
    side: str = "yes",
    entry_price: int = 55,
    contracts: int = 5,
    current_price: int = 55,
    entry_ts: float = None,
    expiry_ts: float = 0.0,
    equity: float = 500_000.0,
) -> TrackedPosition:
    return TrackedPosition(
        position_id=position_id,
        ticker=ticker,
        side=side,
        entry_price_cents=entry_price,
        contracts=contracts,
        entry_ts=entry_ts or time.time(),
        contract_expiry_ts=expiry_ts,
        current_price_cents=current_price,
        session_equity_cents=equity,
    )


# ── TrackedPosition properties ───────────────────────────────────────

class TestTrackedPosition:
    def test_unrealized_pnl_yes_winning(self):
        pos = _pos(side="yes", entry_price=50, current_price=60, contracts=10)
        assert pos.unrealized_pnl_cents == 100  # (60-50)*10

    def test_unrealized_pnl_yes_losing(self):
        pos = _pos(side="yes", entry_price=60, current_price=40, contracts=5)
        assert pos.unrealized_pnl_cents == -100  # (40-60)*5

    def test_unrealized_pnl_no_winning(self):
        pos = _pos(side="no", entry_price=60, current_price=50, contracts=10)
        assert pos.unrealized_pnl_cents == 100  # (60-50)*10

    def test_unrealized_pnl_no_losing(self):
        pos = _pos(side="no", entry_price=40, current_price=60, contracts=5)
        assert pos.unrealized_pnl_cents == -100  # (40-60)*5

    def test_loss_pct_of_equity(self):
        pos = _pos(entry_price=60, current_price=40, contracts=10, equity=10_000)
        # loss = 200c on 10000c equity = 2%
        assert pos.loss_pct_of_equity == pytest.approx(2.0)

    def test_loss_pct_zero_when_winning(self):
        pos = _pos(entry_price=50, current_price=60, contracts=5)
        assert pos.loss_pct_of_equity == 0.0

    def test_time_elapsed_pct(self):
        now = time.time()
        pos = _pos(entry_ts=now - 1800, expiry_ts=now + 1800)
        # 1800s elapsed out of 3600s total
        assert pos.time_elapsed_pct == pytest.approx(0.5, abs=0.05)


# ── Price floor ──────────────────────────────────────────────────────

class TestPriceFloor:
    def test_price_at_floor_triggers(self):
        cfg = StopLossConfig(price_floor_cents=10)
        rules = StopLossRules(cfg)
        pos = _pos(current_price=10)
        action = rules.check_position(pos)
        assert action.should_close
        assert action.rule == "price_floor"

    def test_price_below_floor_triggers(self):
        cfg = StopLossConfig(price_floor_cents=10)
        rules = StopLossRules(cfg)
        pos = _pos(current_price=5)
        action = rules.check_position(pos)
        assert action.should_close

    def test_price_above_floor_ok(self):
        cfg = StopLossConfig(price_floor_cents=10, price_invalidation_drop_cents=0)
        rules = StopLossRules(cfg)
        pos = _pos(current_price=50)
        action = rules.check_position(pos)
        assert not action.should_close


# ── Price invalidation ───────────────────────────────────────────────

class TestPriceInvalidation:
    def test_yes_drop_triggers(self):
        cfg = StopLossConfig(price_invalidation_drop_cents=20, price_floor_cents=0)
        rules = StopLossRules(cfg)
        pos = _pos(side="yes", entry_price=60, current_price=35)
        action = rules.check_position(pos)
        assert action.should_close
        assert action.rule == "price_invalidation"

    def test_no_drop_triggers(self):
        cfg = StopLossConfig(price_invalidation_drop_cents=20, price_floor_cents=0)
        rules = StopLossRules(cfg)
        pos = _pos(side="no", entry_price=40, current_price=65)
        action = rules.check_position(pos)
        assert action.should_close

    def test_small_drop_ok(self):
        cfg = StopLossConfig(price_invalidation_drop_cents=25, price_floor_cents=0)
        rules = StopLossRules(cfg)
        pos = _pos(side="yes", entry_price=60, current_price=45)
        action = rules.check_position(pos)
        assert not action.should_close

    def test_disabled_when_zero(self):
        cfg = StopLossConfig(price_invalidation_drop_cents=0, price_floor_cents=0)
        rules = StopLossRules(cfg)
        pos = _pos(entry_price=60, current_price=10)
        action = rules.check_position(pos)
        assert not action.should_close


# ── Per-trade loss cap ───────────────────────────────────────────────

class TestPerTradeLossCap:
    def test_loss_exceeds_cap(self):
        cfg = StopLossConfig(
            max_loss_per_trade_pct=1.0,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        # 10 contracts, entry 60, current 40 → loss 200c on 10000c equity = 2%
        pos = _pos(entry_price=60, current_price=40, contracts=10, equity=10_000)
        action = rules.check_position(pos)
        assert action.should_close
        assert action.rule == "per_trade_loss_cap"

    def test_loss_within_cap(self):
        cfg = StopLossConfig(
            max_loss_per_trade_pct=5.0,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        pos = _pos(entry_price=55, current_price=50, contracts=5, equity=500_000)
        action = rules.check_position(pos)
        assert not action.should_close


# ── Take-profit ──────────────────────────────────────────────────────

class TestTakeProfit:
    def test_yes_take_profit(self):
        cfg = StopLossConfig(
            take_profit_gain_cents=15,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        pos = _pos(side="yes", entry_price=50, current_price=70)
        action = rules.check_position(pos)
        assert action.should_close
        assert action.rule == "take_profit"

    def test_no_take_profit(self):
        cfg = StopLossConfig(
            take_profit_gain_cents=15,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        pos = _pos(side="no", entry_price=60, current_price=40)
        action = rules.check_position(pos)
        assert action.should_close

    def test_disabled_when_zero(self):
        cfg = StopLossConfig(
            take_profit_gain_cents=0,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        pos = _pos(entry_price=50, current_price=90)
        action = rules.check_position(pos)
        assert not action.should_close


# ── Max hold time ────────────────────────────────────────────────────

class TestMaxHoldTime:
    def test_exceeded_hold_time(self):
        cfg = StopLossConfig(
            max_hold_seconds=60,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        pos = _pos(entry_ts=time.time() - 120)  # 120s ago
        action = rules.check_position(pos)
        assert action.should_close
        assert action.rule == "max_hold_time"

    def test_within_hold_time(self):
        cfg = StopLossConfig(
            max_hold_seconds=3600,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        pos = _pos(entry_ts=time.time() - 10)
        action = rules.check_position(pos)
        assert not action.should_close

    def test_disabled_when_zero(self):
        cfg = StopLossConfig(
            max_hold_seconds=0,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        pos = _pos(entry_ts=time.time() - 999999)
        action = rules.check_position(pos)
        assert not action.should_close


# ── Time-based losing stop ───────────────────────────────────────────

class TestTimeBasedLosing:
    def test_losing_late_in_contract(self):
        now = time.time()
        cfg = StopLossConfig(
            close_if_losing_after_pct=0.75,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        # 90% of duration elapsed, losing
        pos = _pos(
            entry_price=60, current_price=50,
            entry_ts=now - 3240, expiry_ts=now + 360,  # 3600s total, 3240 elapsed
        )
        action = rules.check_position(pos)
        assert action.should_close
        assert action.rule == "time_based_losing"

    def test_winning_late_ok(self):
        now = time.time()
        cfg = StopLossConfig(
            close_if_losing_after_pct=0.75,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        pos = _pos(
            entry_price=50, current_price=60,
            entry_ts=now - 3240, expiry_ts=now + 360,
        )
        action = rules.check_position(pos)
        assert not action.should_close

    def test_losing_early_ok(self):
        now = time.time()
        cfg = StopLossConfig(
            close_if_losing_after_pct=0.75,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        pos = _pos(
            entry_price=60, current_price=50,
            entry_ts=now - 900, expiry_ts=now + 2700,  # 25% elapsed
        )
        action = rules.check_position(pos)
        assert not action.should_close


# ── Session loss cap ─────────────────────────────────────────────────

class TestSessionLossCap:
    def test_session_halts_on_cap(self):
        cfg = StopLossConfig(
            session_loss_cap_pct=3.0,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        rules.set_session_equity(100_000)
        rules.record_session_loss(3_500)  # 3.5% > 3%
        assert rules.session_halted

    def test_session_not_halted_below_cap(self):
        cfg = StopLossConfig(session_loss_cap_pct=5.0)
        rules = StopLossRules(cfg)
        rules.set_session_equity(100_000)
        rules.record_session_loss(2_000)  # 2% < 5%
        assert not rules.session_halted

    def test_halted_session_closes_all(self):
        cfg = StopLossConfig(
            session_loss_cap_pct=1.0,
            price_invalidation_drop_cents=0, price_floor_cents=0,
        )
        rules = StopLossRules(cfg)
        rules.set_session_equity(10_000)
        rules.record_session_loss(200)  # 2% > 1%
        pos = _pos(current_price=55)
        action = rules.check_position(pos)
        assert action.should_close
        assert action.rule == "session_halt"
        assert action.urgency == "critical"

    def test_reset_session(self):
        cfg = StopLossConfig(session_loss_cap_pct=1.0)
        rules = StopLossRules(cfg)
        rules.set_session_equity(10_000)
        rules.record_session_loss(200)
        assert rules.session_halted
        rules.reset_session(50_000)
        assert not rules.session_halted


# ── Record close ─────────────────────────────────────────────────────

class TestRecordClose:
    def test_record_close_logs(self):
        rules = StopLossRules()
        action = StopAction(should_close=True, reason="test", rule="price_floor")
        rules.record_close("p1", action, pnl_cents=-100)
        s = rules.summary()
        assert s["stops_triggered"] == 1
        assert len(s["recent_closes"]) == 1

    def test_record_close_adds_to_session_loss(self):
        rules = StopLossRules()
        rules.set_session_equity(100_000)
        action = StopAction(should_close=True, reason="test", rule="test")
        rules.record_close("p1", action, pnl_cents=-500)
        assert rules.summary()["session_loss_cents"] == 500


# ── Summary ──────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_structure(self):
        rules = StopLossRules()
        s = rules.summary()
        assert "session_halted" in s
        assert "stops_triggered" in s
        assert "config" in s
        assert "price_invalidation_drop_cents" in s["config"]

    def test_positions_checked_counter(self):
        rules = StopLossRules(StopLossConfig(
            price_invalidation_drop_cents=0, price_floor_cents=0,
        ))
        rules.check_position(_pos())
        rules.check_position(_pos())
        assert rules.summary()["positions_checked"] == 2


# ── StopAction ───────────────────────────────────────────────────────

class TestStopAction:
    def test_to_dict(self):
        a = StopAction(should_close=True, reason="test", rule="price_floor", urgency="high")
        d = a.to_dict()
        assert d["should_close"] is True
        assert d["rule"] == "price_floor"
