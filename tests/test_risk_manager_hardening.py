"""Tests for GlobalRiskManager and RiskController — the last gate before real money moves.

Covers:
- GlobalRiskManager: 7-check pre-trade gate, domain kill switches, exposure tracking,
  capital routing, fill/close recording, summary reporting
- RiskController: kill switch triggers (manual, daily loss, position limit, error threshold),
  PnL tracking, daily reset, state transitions, callbacks, status reporting
- RiskCheckResult: serialization
"""

import copy
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from merid.pipeline.risk_manager import (
    DomainRiskConfig,
    GlobalRiskManager,
    RiskCheckResult,
    VenueExposure,
)
from merid.pipeline.proposal import (
    OrderSide,
    OrderType,
    ProposalStatus,
    TradeDomain,
    TradeProposal,
)
from merid.risk.kill_switches import (
    KillSwitchEvent,
    KillSwitchReason,
    KillSwitchState,
    RiskController,
)


# ── Helpers ───────────────────────────────────────────────────────────

def _make_proposal(
    domain=TradeDomain.CRYPTO,
    venue="binance",
    qty=Decimal("1"),
    price=Decimal("100"),
    notional_usd=None,
) -> TradeProposal:
    return TradeProposal(
        domain=domain,
        venue=venue,
        instrument_id="BTC",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=qty,
        price=price,
        notional_usd=notional_usd,
    )


# ── GlobalRiskManager: 7-Check Gate ──────────────────────────────────

class TestGlobalRiskManagerChecks:
    """Verify all 7 risk checks fire correctly."""

    def _fresh_rm(self):
        from merid.pipeline.risk_manager import _DEFAULT_DOMAIN_CONFIGS
        return GlobalRiskManager(
            total_capital_usd=Decimal("50000"),
            max_portfolio_notional_usd=Decimal("50000"),
            domain_configs=copy.deepcopy(_DEFAULT_DOMAIN_CONFIGS),
        )

    def test_approves_valid_proposal(self):
        rm = self._fresh_rm()
        p = _make_proposal(qty=Decimal("1"), price=Decimal("100"))
        result = rm.check_proposal(p)
        assert result.approved is True
        assert "passed" in result.reason.lower()

    def test_rejects_disabled_domain(self):
        rm = self._fresh_rm()
        cfg = rm._domain_configs[TradeDomain.CRYPTO]
        cfg.enabled = False
        p = _make_proposal()
        result = rm.check_proposal(p)
        assert result.approved is False
        assert "disabled" in result.reason.lower()

    def test_rejects_halted_domain(self):
        rm = self._fresh_rm()
        rm.halt_domain("crypto", "emergency")
        p = _make_proposal()
        result = rm.check_proposal(p)
        assert result.approved is False
        assert "halted" in result.reason.lower()

    def test_rejects_oversized_single_order(self):
        rm = self._fresh_rm()
        # Crypto max single order is $5000
        p = _make_proposal(qty=Decimal("100"), price=Decimal("100"))  # $10,000
        result = rm.check_proposal(p)
        assert result.approved is False
        assert "exceeds domain max" in result.reason

    def test_rejects_domain_notional_breach(self):
        rm = self._fresh_rm()
        # Fill up domain notional close to limit ($25,000 for crypto)
        rm.record_fill("binance", "crypto", Decimal("24500"))
        p = _make_proposal(qty=Decimal("10"), price=Decimal("100"))  # $1,000
        result = rm.check_proposal(p)
        assert result.approved is False
        assert "notional" in result.reason.lower()

    def test_rejects_daily_loss_breach(self):
        rm = self._fresh_rm()
        # Crypto max daily loss is $1000
        rm.record_fill("binance", "crypto", Decimal("2000"))
        rm.record_close("binance", "crypto", Decimal("2000"), Decimal("-1000"))
        p = _make_proposal(qty=Decimal("1"), price=Decimal("100"))
        result = rm.check_proposal(p)
        assert result.approved is False
        assert "daily loss" in result.reason.lower()

    def test_rejects_position_count_breach(self):
        rm = self._fresh_rm()
        # Crypto max positions is 30
        for i in range(30):
            rm.record_fill(f"venue-{i}", "crypto", Decimal("10"))
        p = _make_proposal(qty=Decimal("1"), price=Decimal("100"))
        result = rm.check_proposal(p)
        assert result.approved is False
        assert "positions" in result.reason.lower()

    def test_rejects_portfolio_notional_breach(self):
        rm = self._fresh_rm()
        # Max portfolio is $50,000 — fill across two domains to avoid domain limit
        rm.record_fill("binance", "crypto", Decimal("24000"))
        rm.record_fill("alpaca", "equity", Decimal("20000"))
        rm.record_fill("kalshi", "prediction", Decimal("5000"))
        p = _make_proposal(qty=Decimal("20"), price=Decimal("100"))  # $2,000
        result = rm.check_proposal(p)
        assert result.approved is False
        assert "portfolio notional" in result.reason.lower() or "notional" in result.reason.lower()

    def test_rejects_allocation_pct_breach(self):
        rm = self._fresh_rm()
        # Crypto max allocation is 50% of $50,000 = $25,000
        # But max_notional is also $25,000, so domain notional check fires first.
        # Use a domain with lower allocation: prediction = 10% = $5,000
        rm.record_fill("kalshi", "prediction", Decimal("4500"))
        p = _make_proposal(
            domain=TradeDomain.PREDICTION, venue="kalshi",
            qty=Decimal("2"), price=Decimal("400"),  # $800 → total $5,300 = 10.6%
        )
        result = rm.check_proposal(p)
        assert result.approved is False
        # Could be notional or allocation depending on which fires first
        assert "allocation" in result.reason.lower() or "notional" in result.reason.lower()

    def test_rejects_unknown_domain(self):
        rm = self._fresh_rm()
        p = _make_proposal()
        p.domain = "unknown_domain"
        result = rm.check_proposal(p)
        assert result.approved is False
        assert "no risk config" in result.reason.lower()

    def test_notional_from_notional_usd_field(self):
        rm = self._fresh_rm()
        p = _make_proposal(notional_usd=Decimal("200"), qty=Decimal("0"), price=None)
        result = rm.check_proposal(p)
        assert result.approved is True

    def test_notional_fallback_to_qty(self):
        rm = self._fresh_rm()
        p = _make_proposal(qty=Decimal("200"), price=None)
        result = rm.check_proposal(p)
        assert result.approved is True


def _fresh_rm_default():
    """Create a fresh GlobalRiskManager with deep-copied default configs."""
    from merid.pipeline.risk_manager import _DEFAULT_DOMAIN_CONFIGS
    return GlobalRiskManager(
        total_capital_usd=Decimal("50000"),
        max_portfolio_notional_usd=Decimal("50000"),
        domain_configs=copy.deepcopy(_DEFAULT_DOMAIN_CONFIGS),
    )


class TestGlobalRiskManagerDomainKillSwitch:
    """Verify domain halt/resume behavior."""

    def test_halt_and_resume(self):
        rm = _fresh_rm_default()
        rm.halt_domain("crypto", "test halt")
        assert rm.is_domain_halted("crypto") is True
        rm.resume_domain("crypto")
        assert rm.is_domain_halted("crypto") is False

    def test_halt_blocks_proposals(self):
        rm = _fresh_rm_default()
        rm.halt_domain("prediction", "risk event")
        p = _make_proposal(domain=TradeDomain.PREDICTION, venue="kalshi")
        result = rm.check_proposal(p)
        assert result.approved is False


class TestGlobalRiskManagerExposureTracking:
    """Verify fill/close recording and aggregation."""

    def test_record_fill_increases_notional(self):
        rm = _fresh_rm_default()
        rm.record_fill("binance", "crypto", Decimal("1000"))
        assert rm.domain_notional("crypto") == Decimal("1000")
        assert rm.domain_positions("crypto") == 1

    def test_record_close_decreases_notional(self):
        rm = _fresh_rm_default()
        rm.record_fill("binance", "crypto", Decimal("1000"))
        rm.record_close("binance", "crypto", Decimal("500"), Decimal("50"))
        assert rm.domain_notional("crypto") == Decimal("500")

    def test_record_close_tracks_loss(self):
        rm = _fresh_rm_default()
        rm.record_fill("binance", "crypto", Decimal("1000"))
        rm.record_close("binance", "crypto", Decimal("1000"), Decimal("-200"))
        assert rm.domain_daily_loss("crypto") == Decimal("200")

    def test_portfolio_notional_aggregates_all(self):
        rm = _fresh_rm_default()
        rm.record_fill("binance", "crypto", Decimal("1000"))
        rm.record_fill("kalshi", "prediction", Decimal("500"))
        assert rm.portfolio_notional() == Decimal("1500")

    def test_update_unrealized(self):
        rm = _fresh_rm_default()
        rm.record_fill("binance", "crypto", Decimal("1000"))
        rm.update_unrealized("binance", Decimal("150"))
        exp = rm._exposures["binance"]
        assert exp.unrealized_pnl_usd == Decimal("150")

    def test_notional_floor_at_zero(self):
        rm = _fresh_rm_default()
        rm.record_fill("binance", "crypto", Decimal("100"))
        rm.record_close("binance", "crypto", Decimal("200"), Decimal("0"))
        assert rm.domain_notional("crypto") == Decimal("0")


class TestGlobalRiskManagerCapitalRouting:
    """Verify available_capital computation."""

    def test_available_capital_full(self):
        rm = _fresh_rm_default()
        avail = rm.available_capital(TradeDomain.CRYPTO)
        # Crypto: min(50000*0.50, 25000) = 25000
        assert avail == Decimal("25000")

    def test_available_capital_after_fill(self):
        rm = _fresh_rm_default()
        rm.record_fill("binance", "crypto", Decimal("10000"))
        avail = rm.available_capital(TradeDomain.CRYPTO)
        assert avail == Decimal("15000")

    def test_available_capital_unknown_domain(self):
        rm = _fresh_rm_default()
        rm._domain_configs.pop(TradeDomain.MACRO, None)
        avail = rm.available_capital(TradeDomain.MACRO)
        assert avail == Decimal("0")


class TestGlobalRiskManagerSummary:
    """Verify summary output structure."""

    def test_summary_structure(self):
        rm = _fresh_rm_default()
        rm.record_fill("binance", "crypto", Decimal("1000"))
        s = rm.summary()
        assert "total_capital_usd" in s
        assert "portfolio_notional_usd" in s
        assert "domains" in s
        assert "venue_exposures" in s
        assert "crypto" in s["domains"]
        assert s["domains"]["crypto"]["notional_usd"] == "1000"

    def test_summary_includes_halted(self):
        rm = _fresh_rm_default()
        rm.halt_domain("crypto", "test")
        s = rm.summary()
        assert s["halted_domains"]["crypto"] == "test"
        assert s["domains"]["crypto"]["halted"] is True


class TestRiskCheckResult:
    """Verify RiskCheckResult serialization."""

    def test_to_dict_approved(self):
        r = RiskCheckResult(approved=True, reason="All checks passed", domain="crypto", venue="binance")
        d = r.to_dict()
        assert d["approved"] is True
        assert d["domain"] == "crypto"
        assert d["venue"] == "binance"
        assert "timestamp" in d

    def test_to_dict_rejected_with_adjusted_qty(self):
        r = RiskCheckResult(
            approved=False,
            reason="Oversized",
            adjusted_qty=Decimal("5.5"),
            domain="prediction",
            venue="kalshi",
        )
        d = r.to_dict()
        assert d["approved"] is False
        assert d["adjusted_qty"] == "5.5"


class TestRiskContextScaling:
    """Verify RiskContext size_scale_factor integration."""

    def test_scale_factor_reduces_notional(self):
        rm = _fresh_rm_default()

        class FakeRiskContext:
            size_scale_factor = 0.5
        
        p = _make_proposal(qty=Decimal("10"), price=Decimal("100"))  # $1000 → scaled to $500
        result = rm.check_proposal(p, risk_context=FakeRiskContext())
        assert result.approved is True

    def test_scale_factor_zero_rejects(self):
        rm = _fresh_rm_default()

        class FakeRiskContext:
            size_scale_factor = 0.0

        p = _make_proposal(qty=Decimal("10"), price=Decimal("100"))
        result = rm.check_proposal(p, risk_context=FakeRiskContext())
        assert result.approved is False
        assert "size_scale_factor" in result.reason


# ── RiskController Tests ──────────────────────────────────────────────

class TestRiskControllerTrading:
    """Verify can_trade and kill switch behavior."""

    @pytest.fixture
    def rc(self):
        return RiskController(daily_loss_limit=500.0, max_position_value=10000.0, error_threshold=5)

    def test_can_trade_initially(self, rc):
        assert rc.can_trade() is True

    def test_emergency_stop_halts_trading(self, rc):
        rc.emergency_stop("test stop")
        assert rc.can_trade() is False
        assert rc.get_state() == KillSwitchState.TRIGGERED

    def test_emergency_stop_idempotent(self, rc):
        rc.emergency_stop("first")
        rc.emergency_stop("second")
        assert len(rc.get_events()) == 1

    def test_reset_allows_trading(self, rc):
        rc.emergency_stop("test")
        assert rc.can_trade() is False
        rc.reset("operator")
        assert rc.can_trade() is True

    def test_reset_when_not_triggered(self, rc):
        result = rc.reset("operator")
        assert result is True


class TestRiskControllerPnL:
    """Verify daily PnL tracking and kill switch triggers."""

    @pytest.fixture
    def rc(self):
        return RiskController(daily_loss_limit=500.0, max_position_value=10000.0)

    def test_record_positive_pnl(self, rc):
        result = rc.record_pnl(100.0)
        assert result is True
        assert rc._daily_pnl == 100.0

    def test_record_negative_pnl_within_limit(self, rc):
        result = rc.record_pnl(-200.0)
        assert result is True
        assert rc.can_trade() is True

    def test_daily_loss_triggers_kill(self, rc):
        result = rc.record_pnl(-500.0)
        assert result is False
        assert rc.can_trade() is False
        assert rc._kill_reason == KillSwitchReason.DAILY_LOSS

    def test_cumulative_loss_triggers_kill(self, rc):
        rc.record_pnl(-200.0)
        rc.record_pnl(-200.0)
        result = rc.record_pnl(-100.0)
        assert result is False
        assert rc.can_trade() is False


class TestRiskControllerPositionLimit:
    """Verify position value kill switch."""

    def test_position_within_limit(self):
        rc = RiskController(max_position_value=10000.0)
        result = rc.update_position_value(5000.0)
        assert result is True

    def test_position_exceeds_limit(self):
        rc = RiskController(max_position_value=10000.0)
        result = rc.update_position_value(15000.0)
        assert result is False
        assert rc.can_trade() is False
        assert rc._kill_reason == KillSwitchReason.POSITION_LIMIT


class TestRiskControllerErrorThreshold:
    """Verify error-based kill switch."""

    def test_errors_within_threshold(self):
        rc = RiskController(error_threshold=5)
        for _ in range(4):
            result = rc.record_error()
            assert result is True

    def test_errors_exceed_threshold(self):
        rc = RiskController(error_threshold=5)
        for _ in range(4):
            rc.record_error()
        result = rc.record_error()
        assert result is False
        assert rc.can_trade() is False
        assert rc._kill_reason == KillSwitchReason.ERROR_THRESHOLD


class TestRiskControllerCallbacks:
    """Verify kill switch event callbacks."""

    def test_callback_fires_on_kill(self):
        rc = RiskController(daily_loss_limit=100.0)
        events = []
        rc.on_kill(lambda e: events.append(e))
        rc.emergency_stop("test")
        assert len(events) == 1
        assert events[0].reason == KillSwitchReason.MANUAL

    def test_callback_error_does_not_break_kill(self):
        rc = RiskController(daily_loss_limit=100.0)
        rc.on_kill(lambda e: 1 / 0)  # Bad callback
        rc.emergency_stop("test")
        assert rc.can_trade() is False


class TestRiskControllerStatus:
    """Verify status reporting."""

    def test_status_structure(self):
        rc = RiskController(daily_loss_limit=500.0, max_position_value=10000.0, error_threshold=10)
        s = rc.get_status()
        assert s["state"] == "active"
        assert s["can_trade"] is True
        assert s["daily_pnl"] == 0.0
        assert s["daily_loss_limit"] == 500.0
        assert s["max_position_value"] == 10000.0
        assert s["error_count"] == 0

    def test_status_after_kill(self):
        rc = RiskController()
        rc.emergency_stop("test")
        s = rc.get_status()
        assert s["state"] == "triggered"
        assert s["can_trade"] is False
        assert s["kill_reason"] == "manual"

    def test_status_pnl_pct(self):
        rc = RiskController(daily_loss_limit=500.0)
        rc.record_pnl(-250.0)
        s = rc.get_status()
        assert s["daily_pnl_pct"] == pytest.approx(50.0)


class TestRiskControllerEvents:
    """Verify event history."""

    def test_events_recorded(self):
        rc = RiskController()
        rc.emergency_stop("test1")
        rc.reset("operator")
        events = rc.get_events()
        assert len(events) == 2
        assert events[0].new_state == KillSwitchState.TRIGGERED
        assert events[1].new_state == KillSwitchState.ACTIVE

    def test_events_limited(self):
        rc = RiskController()
        for i in range(20):
            rc.emergency_stop(f"stop-{i}")
            rc.reset("op")
        events = rc.get_events(limit=5)
        assert len(events) == 5
