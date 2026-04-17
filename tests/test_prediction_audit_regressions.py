"""test_prediction_audit_regressions.py

Regression tests for all bugs fixed in the Prediction Module Audit.

Bug IDs map to the audit report tickets:
  BUG-01  Wire PaperLadder tier → PredictionRiskConfig notional caps
  BUG-02  Per-agent notional enforcement in check_order()
  BUG-03  Link PaperLadder + PaperSession into single paper→live gate
  BUG-04  Enforce cutoff_minutes_before_expiry >= 2
  BUG-05  Fix arb side='both' to place both YES and NO legs
  BUG-06  Deduct fees from realized PnL in record_close()
  BUG-07  Settlement price override in record_close() for SETTLED_YES/NO
  BUG-08  _resolve_markets loops all config.assets
  BUG-09  StopLossRules equity from ladder, not hardcoded $5K
  BUG-10  Post-fee edge formula branches on YES vs NO side
  BUG-11  _sentiment_size_multiplier full range (0.35–1.5), not capped at 1.0
"""
from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent

PAPER_LADDER_SRC   = ROOT / "merid" / "paper_ladder.py"
RISK_SRC           = ROOT / "merid" / "prediction" / "risk.py"
PAPER_SESSION_SRC  = ROOT / "merid" / "prediction" / "paper_session.py"
AGENT_GRID_CFG_SRC = ROOT / "merid" / "prediction" / "agent_grid_config.py"
TRADING_AGENT_SRC  = ROOT / "merid" / "prediction" / "trading_agent.py"
STOP_LOSS_SRC      = ROOT / "merid" / "event_venues" / "kalshi" / "stop_loss.py"
STRATEGY_SRC       = ROOT / "merid" / "prediction" / "strategy.py"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# BUG-01 — PaperLadder tier changes wire to PredictionRiskConfig
# =============================================================================

class TestBUG01_LadderTierRiskCaps:

    def test_apply_risk_caps_method_exists(self):
        src = _src(PAPER_LADDER_SRC)
        assert "def _apply_risk_caps" in src, (
            "BUG-01: _apply_risk_caps method not found in paper_ladder.py"
        )

    def test_apply_risk_caps_called_on_seed(self):
        src = _src(PAPER_LADDER_SRC)
        # Find seed_portfolio body and check _apply_risk_caps is called
        assert src.count("self._apply_risk_caps(") >= 3, (
            "BUG-01: _apply_risk_caps must be called from seed, promote, and demote "
            f"(found {src.count('self._apply_risk_caps(')} calls)"
        )

    def test_apply_risk_caps_sets_total_notional(self):
        src = _src(PAPER_LADDER_SRC)
        assert "max_total_notional_usd" in src, (
            "BUG-01: max_total_notional_usd not updated in _apply_risk_caps"
        )

    def test_apply_risk_caps_sets_per_market_notional(self):
        src = _src(PAPER_LADDER_SRC)
        assert "max_notional_per_market_usd" in src, (
            "BUG-01: max_notional_per_market_usd not updated in _apply_risk_caps"
        )

    def test_apply_risk_caps_sets_daily_loss(self):
        src = _src(PAPER_LADDER_SRC)
        assert "max_daily_loss_usd" in src, (
            "BUG-01: max_daily_loss_usd not updated in _apply_risk_caps"
        )

    def test_apply_risk_caps_runtime(self):
        """Unit: _apply_risk_caps updates get_prediction_risk().config caps."""
        import merid.prediction.risk as risk_mod
        from merid.paper_ladder import PaperLadder, LadderTier
        from merid.prediction.risk import PredictionRiskConfig

        original_risk = risk_mod._risk
        try:
            cfg = PredictionRiskConfig()
            risk_mod._risk = risk_mod.PredictionMarketRisk(cfg)

            tier = LadderTier(
                level=1,
                name="Rookie",
                seed_usd=2_000.0,
                profit_target_pct=15.0,
                max_drawdown_pct=8.0,
                min_trades=30,
                min_win_rate_pct=52.0,
            )
            ladder = PaperLadder.__new__(PaperLadder)
            ladder._apply_risk_caps(tier)

            r = risk_mod._risk
            assert float(r.config.max_total_notional_usd) == pytest.approx(1_000.0), (
                "BUG-01: total notional cap should be seed * 0.5 = 1000"
            )
            assert float(r.config.max_notional_per_market_usd) == pytest.approx(100.0), (
                "BUG-01: per-market cap should be seed * 0.05 = 100"
            )
        finally:
            risk_mod._risk = original_risk


# =============================================================================
# BUG-02 — Per-agent notional enforcement in check_order()
# =============================================================================

class TestBUG02_PerAgentNotionalEnforcement:

    def test_agent_max_notional_param_in_check_order(self):
        src = _src(RISK_SRC)
        assert "agent_max_notional_usd" in src, (
            "BUG-02: agent_max_notional_usd param not found in risk.py"
        )

    def test_check_order_rejects_when_order_exceeds_agent_cap(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_notional_per_market_usd=Decimal("10000"),
            max_total_notional_usd=Decimal("50000"),
        )
        risk = PredictionMarketRisk(cfg)
        # Order notional = 10 * 60c = $6.00, agent cap = $5.00 → reject/reduce
        check = risk.check_order(
            market_id="TEST-ARB-1",
            event_id="EV-1",
            side="yes",
            contracts=10,
            price_cents=Decimal("60"),
            agent_max_notional_usd=Decimal("5.00"),
        )
        assert not check.allowed, (
            "BUG-02: order exceeding agent notional cap should be rejected"
        )

    def test_check_order_allows_when_under_agent_cap(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_notional_per_market_usd=Decimal("10000"),
            max_total_notional_usd=Decimal("50000"),
        )
        risk = PredictionMarketRisk(cfg)
        # Order notional = 5 * 50c = $2.50, agent cap = $10.00 → allowed
        check = risk.check_order(
            market_id="TEST-ARB-2",
            event_id="EV-2",
            side="yes",
            contracts=5,
            price_cents=Decimal("50"),
            agent_max_notional_usd=Decimal("10.00"),
        )
        assert check.allowed, (
            "BUG-02: order within agent notional cap should be allowed"
        )

    def test_adjusted_size_computed_on_reduce(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_notional_per_market_usd=Decimal("100000"),
            max_total_notional_usd=Decimal("500000"),
        )
        risk = PredictionMarketRisk(cfg)
        # Order: 20 contracts @ 50¢ = $10, cap = $5 → expect adjusted_size=10
        check = risk.check_order(
            market_id="TEST-ARB-3",
            event_id="EV-3",
            side="yes",
            contracts=20,
            price_cents=Decimal("50"),
            agent_max_notional_usd=Decimal("5.00"),
        )
        assert not check.allowed
        assert check.adjusted_size is not None and check.adjusted_size > 0, (
            "BUG-02: adjusted_size should be set when agent cap is breached"
        )

    def test_agent_max_notional_passed_in_trading_agent(self):
        src = _src(TRADING_AGENT_SRC)
        assert "agent_max_notional_usd=self.config.risk_limits.max_notional_usd" in src, (
            "BUG-02: trading_agent must pass agent_max_notional_usd to check_order()"
        )


# =============================================================================
# BUG-03 — PaperLadder + PaperSession single paper→live gate
# =============================================================================

class TestBUG03_LadderSessionGate:

    def test_ladder_tier_check_in_check_readiness(self):
        src = _src(PAPER_SESSION_SRC)
        assert "ladder_tier" in src, (
            "BUG-03: 'ladder_tier' check not found in paper_session.py"
        )

    def test_live_ready_tier_constant(self):
        src = _src(PAPER_SESSION_SRC)
        assert "_LIVE_READY_TIER" in src, (
            "BUG-03: _LIVE_READY_TIER constant not defined in paper_session.py"
        )

    def test_get_paper_ladder_imported_in_session(self):
        src = _src(PAPER_SESSION_SRC)
        assert "get_paper_ladder" in src, (
            "BUG-03: get_paper_ladder not imported in paper_session.py"
        )

    def test_check_readiness_returns_ladder_tier_in_checks(self):
        """check_readiness verdict must include 'ladder_tier' key."""
        from merid.prediction.paper_session import PaperSession, ReadinessBenchmark
        from merid.prediction.paper_session import IntervalPnL

        sess = PaperSession.__new__(PaperSession)
        sess._benchmark = ReadinessBenchmark()
        sess._risk_limits = MagicMock()
        sess._intervals = {}
        sess._session_start = 0.0
        sess._session_id = "test"
        sess._live_promoted = set()

        # Seed a fake interval that passes all non-ladder checks
        interval = IntervalPnL(asset="BTC", timeframe="1h", agent_name="BTC_1H")
        interval.total_trades = 100
        interval.winning_trades = 56
        interval.losing_trades = 44
        interval.gross_wins_cents = 5000.0
        interval.gross_losses_cents = 2000.0
        interval.errors = 0
        interval.circuit_breaker_trips = 0
        interval.high_water_mark_cents = 500.0
        interval.net_pnl_cents = 200.0
        interval.max_drawdown_cents = 10.0
        interval.first_trade_at = "2026-01-01T00:00:00"
        sess._intervals["BTC_1H"] = interval
        sess._session_start = 0.0  # session_hours will be very large

        # Patch get_paper_ladder to return no portfolios → ladder_tier fails
        with patch("merid.paper_ladder.get_paper_ladder") as mock_ladder:
            mock_p = MagicMock()
            mock_p.get_all_progress.return_value = {}
            mock_ladder.return_value = mock_p

            verdict = sess.check_readiness("BTC_1H")

        assert "ladder_tier" in verdict.checks, (
            "BUG-03: ReadinessVerdict.checks must include 'ladder_tier' key"
        )
        assert verdict.checks["ladder_tier"] is False, (
            "BUG-03: ladder_tier should fail when no portfolios tracked"
        )

    def test_check_readiness_passes_ladder_when_tier4(self):
        """check_readiness passes ladder_tier when portfolio is at tier 4."""
        from merid.prediction.paper_session import PaperSession, ReadinessBenchmark, IntervalPnL

        sess = PaperSession.__new__(PaperSession)
        sess._benchmark = ReadinessBenchmark()
        sess._risk_limits = MagicMock()
        sess._intervals = {}
        sess._session_start = 0.0
        sess._session_id = "test"
        sess._live_promoted = set()

        interval = IntervalPnL(asset="BTC", timeframe="1h", agent_name="BTC_1H")
        interval.total_trades = 100
        interval.winning_trades = 56
        interval.losing_trades = 44
        interval.gross_wins_cents = 5000.0
        interval.gross_losses_cents = 2000.0
        interval.errors = 0
        interval.circuit_breaker_trips = 0
        interval.high_water_mark_cents = 500.0
        interval.net_pnl_cents = 200.0
        interval.max_drawdown_cents = 10.0
        sess._intervals["BTC_1H"] = interval

        with patch("merid.paper_ladder.get_paper_ladder") as mock_ladder:
            progress = MagicMock()
            progress.current_tier = 4
            mock_p = MagicMock()
            mock_p.get_all_progress.return_value = {"portfolio-1": progress}
            mock_ladder.return_value = mock_p

            verdict = sess.check_readiness("BTC_1H")

        assert verdict.checks.get("ladder_tier") is True, (
            "BUG-03: ladder_tier should pass when max portfolio tier == 4"
        )


# =============================================================================
# BUG-04 — cutoff_minutes_before_expiry >= 2 enforced
# =============================================================================

class TestBUG04_CutoffMinimum:

    def test_min_cutoff_constant_exists(self):
        src = _src(AGENT_GRID_CFG_SRC)
        assert "_MIN_CUTOFF_MINUTES" in src, (
            "BUG-04: _MIN_CUTOFF_MINUTES constant not found in agent_grid_config.py"
        )

    def test_min_cutoff_value_is_2(self):
        from merid.prediction.agent_grid_config import _MIN_CUTOFF_MINUTES
        assert _MIN_CUTOFF_MINUTES == 2, (
            f"BUG-04: _MIN_CUTOFF_MINUTES should be 2, got {_MIN_CUTOFF_MINUTES}"
        )

    def test_parse_entry_window_clamps_cutoff_below_2(self):
        from merid.prediction.agent_grid_config import _parse_entry_window
        ew = _parse_entry_window({"minutes_before_expiry": 10, "cutoff_minutes_before_expiry": 0})
        assert ew.cutoff_minutes_before_expiry == 2, (
            f"BUG-04: cutoff=0 should be clamped to 2, got {ew.cutoff_minutes_before_expiry}"
        )

    def test_parse_entry_window_clamps_cutoff_of_1(self):
        from merid.prediction.agent_grid_config import _parse_entry_window
        ew = _parse_entry_window({"minutes_before_expiry": 5, "cutoff_minutes_before_expiry": 1})
        assert ew.cutoff_minutes_before_expiry == 2, (
            f"BUG-04: cutoff=1 should be clamped to 2, got {ew.cutoff_minutes_before_expiry}"
        )

    def test_parse_entry_window_preserves_cutoff_above_2(self):
        from merid.prediction.agent_grid_config import _parse_entry_window
        ew = _parse_entry_window({"minutes_before_expiry": 30, "cutoff_minutes_before_expiry": 5})
        assert ew.cutoff_minutes_before_expiry == 5, (
            f"BUG-04: cutoff=5 should be preserved, got {ew.cutoff_minutes_before_expiry}"
        )

    def test_parse_entry_window_default_is_2(self):
        from merid.prediction.agent_grid_config import _parse_entry_window
        ew = _parse_entry_window({})
        assert ew.cutoff_minutes_before_expiry == 2, (
            f"BUG-04: default cutoff should be 2, got {ew.cutoff_minutes_before_expiry}"
        )


# =============================================================================
# BUG-05 — Arb side='both' places YES and NO legs
# =============================================================================

class TestBUG05_ArbBothLegs:

    def test_side_both_branch_in_execute_signal(self):
        src = _src(TRADING_AGENT_SRC)
        assert 'signal.side == "both"' in src, (
            'BUG-05: side="both" branch not found in _execute_signal'
        )

    def test_no_leg_placed_in_arb_branch(self):
        src = _src(TRADING_AGENT_SRC)
        # The arb branch must place a NO leg
        assert '"no"' in src or "\"no\"" in src, (
            'BUG-05: NO leg placement not found in arb branch'
        )
        assert "no_price" in src, (
            "BUG-05: no_price variable not computed in arb branch"
        )

    def test_yes_leg_placed_in_arb_branch(self):
        src = _src(TRADING_AGENT_SRC)
        assert "yes_price" in src, (
            "BUG-05: yes_price variable not computed in arb branch"
        )

    def test_arb_result_payload_has_arb_flag(self):
        src = _src(TRADING_AGENT_SRC)
        assert '"arb": True' in src, (
            'BUG-05: arb result payload missing "arb": True flag'
        )

    def test_complementary_price_formula(self):
        src = _src(TRADING_AGENT_SRC)
        assert "100 - yes_price" in src, (
            "BUG-05: complementary NO price formula '100 - yes_price' not found"
        )


# =============================================================================
# BUG-06 — Fees deducted from realized PnL in record_close()
# =============================================================================

class TestBUG06_FeesDeductedFromPnL:

    def test_fee_cents_param_in_record_close(self):
        src = _src(RISK_SRC)
        assert "fee_cents: Decimal" in src, (
            "BUG-06: fee_cents parameter not found in record_close()"
        )

    def test_fee_deducted_from_realized(self):
        src = _src(RISK_SRC)
        assert "realized -= fee_usd" in src, (
            "BUG-06: 'realized -= fee_usd' not found — fees not deducted from realized PnL"
        )

    def test_total_pnl_subtracts_fees(self):
        src = _src(RISK_SRC)
        assert "self.realized_pnl_usd + self.unrealized_pnl_usd - self.fees_usd" in src, (
            "BUG-06: total_pnl_usd must subtract fees"
        )

    def test_record_close_fee_deduction_runtime(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig()
        risk = PredictionMarketRisk(cfg)

        # Open 10 contracts @ 50¢ → notional $5
        risk.record_fill(
            market_id="FEE-TEST-1",
            event_id="EV-FEE",
            side="yes",
            contracts=10,
            price_cents=Decimal("50"),
        )
        # Close all @ 70¢ with $0.20 fee
        risk.record_close(
            market_id="FEE-TEST-1",
            contracts=10,
            exit_price_cents=Decimal("70"),
            fee_cents=Decimal("20"),  # 20¢ = $0.20
        )
        today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
        daily = risk._daily_pnl.get(today)
        assert daily is not None
        # Gross PnL = (70-50)*10 / 100 = $2.00; fee = $0.20; net = $1.80
        expected = Decimal("1.80")
        assert daily.realized_pnl_usd == expected, (
            f"BUG-06: expected net PnL $1.80 after fees, got {daily.realized_pnl_usd}"
        )


# =============================================================================
# BUG-07 — Settlement price override in record_close()
# =============================================================================

class TestBUG07_SettlementPriceOverride:

    def test_outcome_param_in_record_close(self):
        src = _src(RISK_SRC)
        assert "outcome: Optional[str]" in src, (
            "BUG-07: outcome param not found in record_close()"
        )

    def test_yes_settlement_overrides_price_to_100(self):
        src = _src(RISK_SRC)
        assert 'exit_price_cents = Decimal("100")' in src, (
            "BUG-07: settlement YES override to 100¢ not found"
        )

    def test_no_settlement_overrides_price_to_0(self):
        src = _src(RISK_SRC)
        assert 'exit_price_cents = Decimal("0")' in src, (
            "BUG-07: settlement NO override to 0¢ not found"
        )

    def test_cancelled_uses_entry_price(self):
        src = _src(RISK_SRC)
        assert "exit_price_cents = exp.avg_entry_cents" in src, (
            "BUG-07: cancelled settlement (return entry) not found"
        )

    def test_settled_yes_pnl_runtime(self):
        """Closing YES at settlement=yes should yield (100-entry)*contracts/100."""
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig()
        risk = PredictionMarketRisk(cfg)

        risk.record_fill(
            market_id="SET-YES-1",
            event_id="EV-SET",
            side="yes",
            contracts=5,
            price_cents=Decimal("60"),
        )
        risk.record_close(
            market_id="SET-YES-1",
            contracts=5,
            exit_price_cents=Decimal("55"),  # ignored — outcome overrides
            outcome="yes",
        )
        today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
        daily = risk._daily_pnl[today]
        # (100-60)*5 / 100 = $2.00
        assert daily.realized_pnl_usd == Decimal("2.00"), (
            f"BUG-07: SETTLED_YES PnL should be $2.00, got {daily.realized_pnl_usd}"
        )

    def test_settled_no_pnl_runtime(self):
        """Closing YES at settlement=no should yield (0-entry)*contracts/100 = loss."""
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig()
        risk = PredictionMarketRisk(cfg)

        risk.record_fill(
            market_id="SET-NO-1",
            event_id="EV-SET-NO",
            side="yes",
            contracts=5,
            price_cents=Decimal("60"),
        )
        risk.record_close(
            market_id="SET-NO-1",
            contracts=5,
            exit_price_cents=Decimal("65"),  # ignored
            outcome="no",
        )
        today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
        daily = risk._daily_pnl[today]
        # (0-60)*5 / 100 = -$3.00
        assert daily.realized_pnl_usd == Decimal("-3.00"), (
            f"BUG-07: SETTLED_NO PnL should be -$3.00, got {daily.realized_pnl_usd}"
        )


# =============================================================================
# BUG-08 — _resolve_markets loops all config.assets
# =============================================================================

class TestBUG08_ResolveAllAssets:

    def test_resolve_markets_iterates_all_assets(self):
        src = _src(TRADING_AGENT_SRC)
        assert "for asset in assets:" in src, (
            "BUG-08: 'for asset in assets:' loop not found in _resolve_markets"
        )

    def test_resolve_markets_uses_all_assets_not_index_zero(self):
        src = _src(TRADING_AGENT_SRC)
        # The old code was: asset = self.config.assets[0] if self.config.assets else ""
        # Followed by a single call to _kalshi_list_markets. Ensure the loop pattern exists.
        assert "assets = self.config.assets if self.config.assets else" in src, (
            "BUG-08: multi-asset expansion not found in _resolve_markets"
        )

    def test_dedup_by_ticker(self):
        src = _src(TRADING_AGENT_SRC)
        assert "seen_tickers" in src, (
            "BUG-08: seen_tickers dedup set not found in _resolve_markets"
        )


# =============================================================================
# BUG-09 — StopLossRules equity from ladder, not hardcoded $5K
# =============================================================================

class TestBUG09_StopLossEquityFromLadder:

    def test_default_equity_is_zero(self):
        from merid.event_venues.kalshi.stop_loss import StopLossRules
        rules = StopLossRules()
        assert rules._session_equity_cents == 0.0, (
            f"BUG-09: default _session_equity_cents should be 0.0, got {rules._session_equity_cents}"
        )

    def test_tracked_position_default_equity_zero(self):
        from merid.event_venues.kalshi.stop_loss import TrackedPosition
        pos = TrackedPosition(
            position_id="p1", ticker="T-1", side="yes",
            entry_price_cents=50, contracts=1, entry_ts=0.0,
        )
        assert pos.session_equity_cents == 0.0, (
            f"BUG-09: TrackedPosition default session_equity_cents should be 0.0, got {pos.session_equity_cents}"
        )

    def test_set_session_equity_from_ladder_method_exists(self):
        src = _src(STOP_LOSS_SRC)
        assert "def set_session_equity_from_ladder" in src, (
            "BUG-09: set_session_equity_from_ladder method not found in stop_loss.py"
        )

    def test_set_session_equity_from_ladder_updates_equity(self):
        from merid.event_venues.kalshi.stop_loss import StopLossRules
        rules = StopLossRules()

        progress = MagicMock()
        progress.current_equity = 10_000.0  # $10,000

        with patch("merid.paper_ladder.get_paper_ladder") as mock_ladder:
            mock_p = MagicMock()
            mock_p.get_all_progress.return_value = {"portfolio-1": progress}
            mock_ladder.return_value = mock_p

            rules.set_session_equity_from_ladder()

        assert rules._session_equity_cents == pytest.approx(1_000_000.0), (
            f"BUG-09: equity should be $10K * 100 = 1,000,000¢, got {rules._session_equity_cents}"
        )

    def test_set_session_equity_from_ladder_with_specific_portfolio(self):
        from merid.event_venues.kalshi.stop_loss import StopLossRules
        rules = StopLossRules()

        p1 = MagicMock(); p1.current_equity = 5_000.0
        p2 = MagicMock(); p2.current_equity = 20_000.0

        with patch("merid.paper_ladder.get_paper_ladder") as mock_ladder:
            mock_p = MagicMock()
            mock_p.get_all_progress.return_value = {"port-A": p1, "port-B": p2}
            mock_ladder.return_value = mock_p

            rules.set_session_equity_from_ladder(portfolio_id="port-A")

        assert rules._session_equity_cents == pytest.approx(500_000.0), (
            "BUG-09: specific portfolio equity should be used when portfolio_id provided"
        )


# =============================================================================
# BUG-10 — Post-fee edge formula branches on YES vs NO side
# =============================================================================

class TestBUG10_PostFeeEdgeFormula:

    def test_no_side_branch_in_risk_src(self):
        src = _src(RISK_SRC)
        assert '"no", "buy_no", "sell_no"' in src or "'no', 'buy_no', 'sell_no'" in src, (
            "BUG-10: NO-side branch not found in post-fee edge check"
        )

    def test_yes_payout_per_is_100_minus_price(self):
        src = _src(RISK_SRC)
        assert 'payout_per = Decimal("100") - price_cents' in src, (
            "BUG-10: YES payout formula '100 - price_cents' not found"
        )

    def test_no_payout_per_is_price_cents(self):
        src = _src(RISK_SRC)
        assert "payout_per = price_cents" in src, (
            "BUG-10: NO payout formula 'payout_per = price_cents' not found"
        )

    def test_no_side_edge_check_uses_correct_denominator(self):
        """Edge formula for NO side must use price_cents as denominator."""
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_notional_per_market_usd=Decimal("10000"),
            max_total_notional_usd=Decimal("50000"),
        )
        risk = PredictionMarketRisk(cfg)
        # A very thin edge on a NO buy at 95¢ — with old formula (100-95=5) the
        # fee drag would swamp a 2% edge; with correct formula (95) it should pass.
        check = risk.check_order(
            market_id="EDGE-NO-1",
            event_id="EV-EDGE",
            side="no",
            contracts=1,
            price_cents=Decimal("95"),
            edge=Decimal("0.05"),  # 5% net edge, should pass at 95¢ NO
        )
        # With old formula: payout=5¢, fee~2¢, fee_per/payout = 0.4 → post_fee = 0.05-0.4 < 0.01 → REJECT
        # With correct formula: payout=95¢, fee~2¢, fee_per/payout ≈ 0.021 → post_fee ≈ 0.029 > 0.01 → ALLOW
        assert check.allowed, (
            "BUG-10: NO side buy with 5% edge at 95¢ should pass post-fee check "
            "(correct payout denominator = price_cents = 95)"
        )


# =============================================================================
# BUG-11 — _sentiment_size_multiplier full range 0.35–1.5 (not capped at 1.0)
# =============================================================================

class TestBUG11_SentimentMultiplierRange:

    def test_min_cap_is_035_in_contrarian(self):
        src = _src(STRATEGY_SRC)
        # Lines that apply the sentiment multiplier must use min(1.5, float(mult))
        # (not the kelly_size or vol_breakout lines which use size_factor directly)
        mult_lines = [l for l in src.splitlines() if "float(mult)" in l and "size_factor" in l]
        assert mult_lines, "BUG-11: no 'size_factor = max(...min(...float(mult)))' lines found"
        for line in mult_lines:
            assert "min(1.5" in line, (
                f"BUG-11: size_factor clamp should be min(1.5,...), got: {line.strip()}"
            )

    def test_multiplier_max_is_15_not_10(self):
        src = _src(STRATEGY_SRC)
        assert "min(1.5, float(mult))" in src, (
            "BUG-11: 'min(1.5, float(mult))' not found — multiplier still capped at 1.0"
        )
        assert "min(1.0, float(mult))" not in src, (
            "BUG-11: old 'min(1.0, float(mult))' cap still present"
        )

    def test_extreme_fear_buy_yes_returns_13(self):
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig, SignalAction

        cfg = StrategyConfig()
        strat = KalshiStrategy(cfg)

        snap = MagicMock()
        snap.sentiment_regime = "extreme_fear"
        mult = strat._sentiment_size_multiplier(snap, SignalAction.BUY_YES)
        assert mult == Decimal("1.3"), (
            f"BUG-11: extreme_fear + BUY_YES should return 1.3×, got {mult}"
        )

    def test_extreme_greed_buy_yes_returns_06(self):
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig, SignalAction

        cfg = StrategyConfig()
        strat = KalshiStrategy(cfg)

        snap = MagicMock()
        snap.sentiment_regime = "extreme_greed"
        mult = strat._sentiment_size_multiplier(snap, SignalAction.BUY_YES)
        assert mult == Decimal("0.6"), (
            f"BUG-11: extreme_greed + BUY_YES should return 0.6×, got {mult}"
        )

    def test_size_factor_allows_boost_above_1(self):
        """size_factor must be able to exceed 1.0 after the fix."""
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig, SignalAction

        cfg = StrategyConfig()
        strat = KalshiStrategy(cfg)

        snap = MagicMock()
        snap.sentiment_regime = "extreme_fear"

        mult = strat._sentiment_size_multiplier(snap, SignalAction.BUY_YES)  # 1.3
        size_factor = max(0.35, min(1.5, float(mult)))
        assert size_factor > 1.0, (
            f"BUG-11: size_factor with 1.3× mult should exceed 1.0, got {size_factor}"
        )


# =============================================================================
# BUG-L1 — PortfolioRiskAgent readiness gate before trading agents start
# =============================================================================

class TestBUGL1_PortfolioRiskReadinessGate:

    def test_ready_event_exists(self):
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        assert "_ready_event" in src, (
            "BUG-L1: _ready_event not found in portfolio_risk_agent.py"
        )

    def test_wait_ready_method_exists(self):
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        assert "async def wait_ready" in src, (
            "BUG-L1: wait_ready() method not found in portfolio_risk_agent.py"
        )

    def test_is_ready_property_exists(self):
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        assert "def is_ready" in src, (
            "BUG-L1: is_ready property not found in portfolio_risk_agent.py"
        )

    def test_ready_event_set_after_snapshot(self):
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        assert "_ready_event.set()" in src, (
            "BUG-L1: _ready_event.set() not called after first portfolio snapshot"
        )

    def test_agent_grid_waits_for_risk_ready(self):
        src = _src(ROOT / "merid" / "prediction" / "agent_grid.py")
        assert "wait_ready" in src, (
            "BUG-L1: agent_grid.start() must call portfolio_risk.wait_ready()"
        )

    def test_ready_event_set_on_stop(self):
        """stop() must set _ready_event so waiters don't hang on shutdown."""
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        # Ensure set() is called in stop() as well as in _check_portfolio
        assert src.count("_ready_event.set()") >= 2, (
            "BUG-L1: _ready_event.set() must be called in both stop() and _check_portfolio()"
        )

    @pytest.mark.asyncio
    async def test_wait_ready_returns_false_on_timeout(self):
        """wait_ready(timeout=0.01) returns False when loop never sets event."""
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent, PortfolioRiskConfig
        agent = PortfolioRiskAgent(PortfolioRiskConfig())
        result = await agent.wait_ready(timeout=0.01)
        assert result is False, "BUG-L1: wait_ready should return False on timeout"

    @pytest.mark.asyncio
    async def test_wait_ready_returns_true_when_event_set(self):
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent, PortfolioRiskConfig
        agent = PortfolioRiskAgent(PortfolioRiskConfig())
        agent._ready_event.set()
        result = await agent.wait_ready(timeout=1.0)
        assert result is True, "BUG-L1: wait_ready should return True when event is set"


# =============================================================================
# BUG-L2 — Idempotent start(): _running set only after task created
# =============================================================================

class TestBUGL2_IdempotentStart:

    def test_running_set_after_task_in_portfolio_risk(self):
        """_running = True must come AFTER asyncio.create_task() in portfolio_risk_agent."""
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        lines = src.splitlines()
        # create_task is on its own line; _run_loop() is on the next line
        task_line = next(
            (i for i, l in enumerate(lines) if "asyncio.create_task(" in l),
            None,
        )
        running_line = next(
            (i for i, l in enumerate(lines) if "self._running = True" in l),
            None,
        )
        assert task_line is not None, "BUG-L2: asyncio.create_task() not found in portfolio_risk_agent"
        assert running_line is not None, "BUG-L2: _running = True not found in portfolio_risk_agent"
        assert running_line > task_line, (
            f"BUG-L2: _running=True (line {running_line}) must come after create_task (line {task_line})"
        )

    def test_running_set_at_end_of_orchestrator_start(self):
        """OrchestratorAgentManager.start_all() must set self.running=True only at the end."""
        src = _src(ROOT / "web" / "startup_agents.py")
        lines = src.splitlines()
        # Find start_all def
        start_idx = next(i for i, l in enumerate(lines) if "async def start_all" in l)
        # Find next method def after start_all
        next_def = next(
            (i for i, l in enumerate(lines) if i > start_idx and l.strip().startswith("async def ")),
            len(lines),
        )
        start_all_body = lines[start_idx:next_def]
        running_true_lines = [i for i, l in enumerate(start_all_body) if "self.running = True" in l]
        assert running_true_lines, "BUG-L2: self.running = True not set in start_all()"
        # Ensure it's near the end — after at least 50% of the method body
        last_running_line = running_true_lines[-1]
        assert last_running_line > len(start_all_body) // 2, (
            "BUG-L2: self.running = True should be set near the END of start_all(), not at the top"
        )


# =============================================================================
# BUG-L3 — Position sync at startup
# =============================================================================

class TestBUGL3_PositionSyncAtStartup:

    def test_sync_open_positions_method_exists(self):
        src = _src(TRADING_AGENT_SRC)
        assert "async def _sync_open_positions" in src, (
            "BUG-L3: _sync_open_positions method not found in trading_agent.py"
        )

    def test_sync_called_in_start(self):
        src = _src(TRADING_AGENT_SRC)
        assert "_sync_open_positions()" in src, (
            "BUG-L3: _sync_open_positions() not called in start()"
        )

    def test_sync_uses_kalshi_get_positions(self):
        src = _src(TRADING_AGENT_SRC)
        assert "_kalshi_get_positions" in src, (
            "BUG-L3: _sync_open_positions must call _kalshi_get_positions"
        )

    def test_sync_builds_tracked_positions(self):
        src = _src(TRADING_AGENT_SRC)
        assert "TrackedPosition" in src, (
            "BUG-L3: _sync_open_positions must create TrackedPosition objects"
        )

    def test_sync_is_non_fatal(self):
        """_sync_open_positions must catch all exceptions and only log warning."""
        src = _src(TRADING_AGENT_SRC)
        # Should have a broad except block with a warning
        assert "_sync_open_positions failed (non-fatal" in src, (
            "BUG-L3: _sync_open_positions must be non-fatal (log warning, don't raise)"
        )

    def test_sync_filters_by_agent_assets(self):
        src = _src(TRADING_AGENT_SRC)
        assert "agent_tickers" in src, (
            "BUG-L3: _sync_open_positions must filter by agent assets using agent_tickers"
        )


# =============================================================================
# BUG-L4 — Consensus quorum uses live healthy-agent count
# =============================================================================

class TestBUGL4_DynamicConsensusQuorum:
    CONSENSUS_SRC = ROOT / "consensus" / "consensus_coordinator.py"

    def test_effective_quorum_property_exists(self):
        src = _src(self.CONSENSUS_SRC)
        assert "def effective_quorum" in src, (
            "BUG-L4: effective_quorum property not found in consensus_coordinator.py"
        )

    def test_effective_quorum_uses_agent_heartbeats(self):
        src = _src(self.CONSENSUS_SRC)
        assert "_agent_heartbeats" in src, (
            "BUG-L4: effective_quorum must reference _agent_heartbeats for healthy count"
        )

    def test_clear_stale_opinions_method_exists(self):
        src = _src(self.CONSENSUS_SRC)
        assert "def clear_stale_opinions" in src, (
            "BUG-L4: clear_stale_opinions method not found"
        )

    def test_handle_opinion_uses_effective_quorum(self):
        src = _src(self.CONSENSUS_SRC)
        assert "effective_quorum" in src, (
            "BUG-L4: _handle_opinion_event and _try_form_consensus must use effective_quorum"
        )

    def test_effective_quorum_fallback_to_config(self):
        """With no registered agents, effective_quorum falls back to config minimum."""
        from consensus.consensus_coordinator import EnhancedConsensusCoordinator, ConsensusConfig
        # Use a fresh instance
        cc = EnhancedConsensusCoordinator(ConsensusConfig(min_agents_for_quorum=3))
        assert cc.effective_quorum == 3, (
            f"BUG-L4: with no agents, effective_quorum should be 3 (config min), got {cc.effective_quorum}"
        )

    def test_effective_quorum_scales_with_healthy_agents(self):
        """With 10 healthy agents and 60% quorum_pct, effective_quorum == max(3, ceil(6)) == 6."""
        import math
        from consensus.consensus_coordinator import EnhancedConsensusCoordinator, ConsensusConfig, AgentHeartbeat
        cc = EnhancedConsensusCoordinator(ConsensusConfig(min_agents_for_quorum=3, quorum_percentage=0.6))
        for i in range(10):
            hb = AgentHeartbeat(agent_id=f"agent-{i}", agent_role="trader")
            hb.is_healthy = True
            cc._agent_heartbeats[f"agent-{i}"] = hb
        expected = max(3, math.ceil(10 * 0.6))  # 6
        assert cc.effective_quorum == expected, (
            f"BUG-L4: with 10 healthy agents expected quorum={expected}, got {cc.effective_quorum}"
        )

    def test_clear_stale_opinions_purges_old(self):
        """clear_stale_opinions removes entries older than max_age_s."""
        import time
        from consensus.consensus_coordinator import EnhancedConsensusCoordinator, ConsensusConfig
        from unittest.mock import MagicMock
        cc = EnhancedConsensusCoordinator(ConsensusConfig())
        old_op = MagicMock()
        old_op.timestamp = time.time() - 120  # 2 min old
        fresh_op = MagicMock()
        fresh_op.timestamp = time.time() - 5   # 5 sec old
        cc._pending_opinions["BTC"] = [old_op, fresh_op]
        purged = cc.clear_stale_opinions(max_age_s=60.0)
        assert purged == 1, f"BUG-L4: expected 1 purged, got {purged}"
        assert len(cc._pending_opinions["BTC"]) == 1, "BUG-L4: fresh opinion must survive purge"


# =============================================================================
# BUG-L5 — Shutdown order: drain agents before stopping PortfolioRiskAgent
# =============================================================================

class TestBUGL5_ShutdownDrainOrder:

    def test_drain_method_exists(self):
        src = _src(TRADING_AGENT_SRC)
        assert "async def drain" in src, (
            "BUG-L5: drain() method not found in trading_agent.py"
        )

    def test_drain_sets_lifecycle_draining(self):
        src = _src(TRADING_AGENT_SRC)
        assert "LifecycleState.DRAINING" in src, (
            "BUG-L5: drain() must set lifecycle to DRAINING"
        )

    def test_drain_calls_final_stop_loss(self):
        src = _src(TRADING_AGENT_SRC)
        assert "_check_stop_losses" in src, (
            "BUG-L5: drain() must call _check_stop_losses for final sweep"
        )

    def test_agent_grid_calls_drain_before_stop(self):
        src = _src(ROOT / "merid" / "prediction" / "agent_grid.py")
        lines = src.splitlines()
        drain_line = next((i for i, l in enumerate(lines) if "await agent.drain()" in l), None)
        stop_line = next((i for i, l in enumerate(lines) if "await agent.stop()" in l), None)
        assert drain_line is not None, "BUG-L5: agent.drain() not called in agent_grid.stop()"
        assert stop_line is not None, "BUG-L5: agent.stop() not called in agent_grid.stop()"
        assert drain_line < stop_line, (
            f"BUG-L5: drain() (line {drain_line}) must come before stop() (line {stop_line})"
        )

    def test_portfolio_risk_stopped_after_agents(self):
        src = _src(ROOT / "merid" / "prediction" / "agent_grid.py")
        lines = src.splitlines()
        agent_stop_line = next((i for i, l in enumerate(lines) if "await agent.stop()" in l), None)
        risk_stop_line = next((i for i, l in enumerate(lines) if "_portfolio_risk.stop()" in l), None)
        assert agent_stop_line is not None, "BUG-L5: agent.stop() not found in agent_grid"
        assert risk_stop_line is not None, "BUG-L5: _portfolio_risk.stop() not found in agent_grid"
        assert risk_stop_line > agent_stop_line, (
            "BUG-L5: _portfolio_risk.stop() must come AFTER all agent.stop() calls"
        )

    @pytest.mark.asyncio
    async def test_drain_disables_agent_before_stop_loss(self):
        """After drain(), agent.state.enabled is False."""
        from merid.prediction.trading_agent import KalshiTradingAgent
        from merid.prediction.agent_grid_config import AgentConfig, AgentRiskLimits, EntryWindowConfig

        cfg = AgentConfig(
            name="drain-test", assets=["BTC"], timeframes=["15m"],
            risk_limits=AgentRiskLimits(), entry_window=EntryWindowConfig(),
        )
        agent = KalshiTradingAgent(cfg)
        agent.state.running = True
        agent.state.enabled = True
        # Patch _check_stop_losses to avoid real API calls
        agent._check_stop_losses = MagicMock(return_value=_make_coro(None))
        await agent.drain()
        assert agent.state.enabled is False, "BUG-L5: drain() must disable new signals"


def _make_coro(result):
    """Helper: create a coroutine that returns result."""
    async def _coro():
        return result
    return _coro()


# =============================================================================
# BUG-L6 — Shield mid-order placement from hard task cancellation
# =============================================================================

class TestBUGL6_ExecutionShielding:

    def test_in_execution_event_exists(self):
        src = _src(TRADING_AGENT_SRC)
        assert "_in_execution" in src, (
            "BUG-L6: _in_execution event not found in trading_agent.py"
        )

    def test_execute_signal_sets_in_execution(self):
        src = _src(TRADING_AGENT_SRC)
        assert "_in_execution.set()" in src, (
            "BUG-L6: _in_execution.set() not called in _execute_signal"
        )

    def test_execute_signal_clears_in_execution_in_finally(self):
        src = _src(TRADING_AGENT_SRC)
        assert "_in_execution.clear()" in src, (
            "BUG-L6: _in_execution.clear() must be called in finally block of _execute_signal"
        )

    def test_stop_waits_for_in_execution(self):
        src = _src(TRADING_AGENT_SRC)
        assert "_in_execution.is_set()" in src, (
            "BUG-L6: stop() must check _in_execution.is_set() before cancelling"
        )

    def test_execute_signal_body_method_exists(self):
        """The internal body is split into _execute_signal_body for clarity."""
        src = _src(TRADING_AGENT_SRC)
        assert "async def _execute_signal_body" in src, (
            "BUG-L6: _execute_signal_body method not found"
        )


# =============================================================================
# BUG-L7 — Single-owner shutdown: no triple-stop race
# =============================================================================

class TestBUGL7_SingleOwnerShutdown:
    MAIN_SRC = ROOT / "web" / "main.py"

    def test_shutdown_comment_present(self):
        src = _src(self.MAIN_SRC)
        assert "BUG-L7" in src, (
            "BUG-L7: BUG-L7 comment not found in main.py shutdown section"
        )

    def test_orchestrator_manager_stop_called_once(self):
        src = _src(self.MAIN_SRC)
        yield_idx = src.index("yield")
        shutdown_section = src[yield_idx:]
        # Count only actual call sites — exclude comment lines and def lines
        call_count = sum(
            1 for line in shutdown_section.splitlines()
            if "stop_all()" in line
            and "def " not in line
            and not line.strip().startswith("#")
        )
        assert call_count == 1, (
            f"BUG-L7: stop_all() should be called exactly once in shutdown, found {call_count} times"
        )

    def test_grid_stop_called_once_in_lifespan_shutdown(self):
        src = _src(self.MAIN_SRC)
        yield_idx = src.index("yield")
        shutdown_section = src[yield_idx:]
        # Exclude comment lines
        count = sum(
            1 for line in shutdown_section.splitlines()
            if "grid.stop()" in line and not line.strip().startswith("#")
        )
        assert count <= 1, (
            f"BUG-L7: grid.stop() should appear at most once in lifespan shutdown, got {count}"
        )


# =============================================================================
# BUG-L8 — WARMING_UP state + safe mode + stale opinion purge on restart
# =============================================================================

class TestBUGL8_WarmingUpState:

    def test_lifecycle_state_class_exists(self):
        src = _src(TRADING_AGENT_SRC)
        assert "class LifecycleState" in src, (
            "BUG-L8: LifecycleState class not found in trading_agent.py"
        )

    def test_warming_up_constant_exists(self):
        src = _src(TRADING_AGENT_SRC)
        assert "WARMING_UP" in src, (
            "BUG-L8: WARMING_UP state not defined in LifecycleState"
        )

    def test_warmup_seconds_constant_exists(self):
        src = _src(TRADING_AGENT_SRC)
        assert "_WARMUP_SECONDS" in src, (
            "BUG-L8: _WARMUP_SECONDS constant not found in trading_agent.py"
        )

    def test_execution_blocked_during_warming_up(self):
        src = _src(TRADING_AGENT_SRC)
        assert "LifecycleState.WARMING_UP" in src and "execution skipped" in src, (
            "BUG-L8: execution must be blocked when lifecycle == WARMING_UP"
        )

    def test_started_at_set_in_start(self):
        src = _src(TRADING_AGENT_SRC)
        assert "state.started_at" in src, (
            "BUG-L8: state.started_at must be set in start() for warmup baseline"
        )

    def test_lifecycle_promoted_to_active_after_warmup(self):
        src = _src(TRADING_AGENT_SRC)
        assert "LifecycleState.ACTIVE" in src, (
            "BUG-L8: lifecycle must be promoted to ACTIVE after warmup period"
        )

    def test_state_tracks_lifecycle(self):
        src = _src(TRADING_AGENT_SRC)
        assert "lifecycle: str" in src, (
            "BUG-L8: AgentState must have a lifecycle field"
        )

    def test_clear_stale_opinions_called_at_startup(self):
        src = _src(ROOT / "merid" / "prediction" / "agent_grid.py")
        assert "clear_stale_opinions" in src, (
            "BUG-L8: clear_stale_opinions must be called in agent_grid.start() to purge pre-restart opinions"
        )

    def test_solo_seconds_uses_started_at_not_last_cycle(self):
        """The solo_seconds fallback must use started_at, not last_cycle_at."""
        src = _src(TRADING_AGENT_SRC)
        assert "self.state.started_at or now" in src, (
            "BUG-L8: solo_seconds fallback must use started_at (not last_cycle_at)"
        )
        assert "self.state.last_cycle_at or now" not in src, (
            "BUG-L8: old solo_seconds fallback using last_cycle_at still present"
        )


# =============================================================================
# MED — Medium-risk fixes
# =============================================================================

class TestMediumRiskFixes:

    def test_consecutive_errors_field_in_agent_state(self):
        src = _src(TRADING_AGENT_SRC)
        assert "consecutive_errors" in src, (
            "MED: consecutive_errors field not found in AgentState"
        )

    def test_max_consecutive_errors_constant(self):
        src = _src(TRADING_AGENT_SRC)
        assert "_MAX_CONSECUTIVE_ERRORS" in src, (
            "MED: _MAX_CONSECUTIVE_ERRORS constant not found"
        )

    def test_consecutive_errors_incremented_on_exception(self):
        src = _src(TRADING_AGENT_SRC)
        assert "consecutive_errors += 1" in src, (
            "MED: consecutive_errors not incremented in _run_loop exception handler"
        )

    def test_consecutive_errors_reset_on_success(self):
        src = _src(TRADING_AGENT_SRC)
        assert "consecutive_errors = 0" in src, (
            "MED: consecutive_errors not reset to 0 on successful cycle"
        )

    def test_canonical_agent_error_count_reset_on_success(self):
        src = _src(ROOT / "merid" / "agents" / "base.py")
        assert "self._error_count = 0" in src, (
            "MED: CanonicalAgent._error_count must reset to 0 on successful run"
        )

    def test_canonical_agent_auto_retires_after_max_errors(self):
        src = _src(ROOT / "merid" / "agents" / "base.py")
        assert "_MAX_CANONICAL_CONSECUTIVE_ERRORS" in src, (
            "MED: _MAX_CANONICAL_CONSECUTIVE_ERRORS not defined in base.py"
        )
        assert "AgentStatus.RETIRED" in src, (
            "MED: agent must auto-retire after max consecutive errors"
        )

    def test_gather_uses_return_exceptions_in_loop(self):
        src = _src(ROOT / "merid" / "loop.py")
        assert "return_exceptions=True" in src, (
            "MED: asyncio.gather in _run_agent_cycles must use return_exceptions=True"
        )

    def test_draining_flag_in_agent_grid(self):
        src = _src(ROOT / "merid" / "prediction" / "agent_grid.py")
        assert "_draining" in src, (
            "MED: _draining flag not found in AgentGrid"
        )
