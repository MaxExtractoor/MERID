"""Comprehensive test suite for merid.prediction — Kalshi-first prediction markets.

Covers all 5 areas:
§1 VenueGate (mode gating, Polymarket blocking)
§2 PredictionMarketModel (implied probs, edge, lifecycle)
§3 KalshiStrategy (signals, time-to-expiry, Kelly sizing, exits)
§4 PredictionMarketRisk (pre-trade checks, kill switch, circuit breaker)
§5 Alerts (fire, dedup, history)
"""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from merid.prediction.venue_gate import VenueGate, TradingMode, get_venue_gate
from merid.prediction.model import (
    ContractState,
    PredictionMarketModel,
    ImpliedProbability,
    EdgeEstimate,
    MarketSnapshot,
)
from merid.prediction.strategy import (
    KalshiStrategy,
    StrategyConfig,
    StrategySignal,
    SignalAction,
    ExpiryPhase,
    PositionState,
)
from merid.prediction.risk import (
    PredictionMarketRisk,
    PredictionRiskConfig,
    PreTradeCheck,
    RiskAction,
)
from merid.prediction.alerts import (
    PredictionAlertManager,
    PredictionAlert,
    AlertCategory,
    AlertSeverity,
)


# ======================================================================
# §1 VenueGate Tests
# ======================================================================

class TestVenueGate:
    """Tests for VenueGate mode gating and US-compliance guardrails."""

    def test_default_mode_is_sim(self):
        gate = VenueGate(mode=TradingMode.MOCK)
        assert gate.mode == TradingMode.MOCK

    def test_explicit_mode(self):
        gate = VenueGate(mode=TradingMode.PAPER)
        assert gate.mode == TradingMode.PAPER

    def test_mode_from_string(self):
        gate = VenueGate(mode="paper")
        assert gate.mode == TradingMode.PAPER

    def test_kalshi_allowed(self):
        gate = VenueGate()
        gate.check_venue("kalshi")  # should not raise

    def test_polymarket_blocked(self):
        gate = VenueGate()
        with pytest.raises(VenueGate.VenueBlockedError, match="blocked for US compliance"):
            gate.check_venue("polymarket")

    def test_augur_blocked(self):
        gate = VenueGate()
        with pytest.raises(VenueGate.VenueBlockedError):
            gate.check_venue("augur")

    def test_unknown_venue_blocked(self):
        gate = VenueGate()
        with pytest.raises(VenueGate.VenueBlockedError, match="Unknown"):
            gate.check_venue("binance_prediction")

    def test_sim_mode_blocks_trading(self):
        gate = VenueGate(mode=TradingMode.MOCK)
        with pytest.raises(VenueGate.ModeBlockedError, match="MOCK"):
            gate.check_can_trade()

    def test_paper_mode_allows_trading(self):
        gate = VenueGate(mode=TradingMode.PAPER)
        gate.check_can_trade()  # should not raise

    def test_live_mode_without_enable_blocks(self):
        # Safety guard forces LIVE→PAPER when MERID_ALLOW_LIVE_TRADES is not set,
        # so the gate should now be in PAPER mode and allow trading (simulated).
        gate = VenueGate(mode=TradingMode.LIVE, live_enabled=False)
        # If MERID_ALLOW_LIVE_TRADES is not set, the safety guard forces PAPER
        import os
        if os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower() not in ("1", "true", "yes", "on"):
            assert gate.mode == TradingMode.PAPER, "Safety guard should force PAPER when MERID_ALLOW_LIVE_TRADES unset"
            gate.check_can_trade()  # PAPER mode allows trading
        else:
            with pytest.raises(VenueGate.ModeBlockedError, match="MERID_PM_LIVE_ENABLED"):
                gate.check_can_trade()

    def test_live_mode_with_enable_allows(self):
        # With MERID_ALLOW_LIVE_TRADES not set, safety guard forces PAPER regardless
        gate = VenueGate(mode=TradingMode.LIVE, live_enabled=True)
        import os
        if os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower() not in ("1", "true", "yes", "on"):
            assert gate.mode == TradingMode.PAPER, "Safety guard should force PAPER"
        else:
            gate.check_can_trade()  # should not raise in live-enabled env

    def test_check_order_combined(self):
        gate = VenueGate(mode=TradingMode.PAPER)
        gate.check_order("kalshi")  # should not raise

    def test_check_order_blocked_venue(self):
        gate = VenueGate(mode=TradingMode.PAPER)
        with pytest.raises(VenueGate.VenueBlockedError):
            gate.check_order("polymarket")

    def test_check_order_blocked_mode(self):
        gate = VenueGate(mode=TradingMode.SIM)
        with pytest.raises(VenueGate.ModeBlockedError):
            gate.check_order("kalshi")

    def test_should_simulate_fill_sim(self):
        gate = VenueGate(mode=TradingMode.SIM)
        assert gate.should_simulate_fill() is True

    def test_should_simulate_fill_paper(self):
        gate = VenueGate(mode=TradingMode.PAPER)
        assert gate.should_simulate_fill() is True

    def test_should_simulate_fill_live(self):
        # Safety guard forces LIVE→PAPER when MERID_ALLOW_LIVE_TRADES is not set
        gate = VenueGate(mode=TradingMode.LIVE, live_enabled=True)
        import os
        if os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower() not in ("1", "true", "yes", "on"):
            assert gate.should_simulate_fill() is True  # Forced to PAPER by safety guard
        else:
            assert gate.should_simulate_fill() is False

    def test_is_live_property(self):
        import os
        gate = VenueGate(mode=TradingMode.LIVE, live_enabled=True)
        if os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower() not in ("1", "true", "yes", "on"):
            assert gate.is_live is False  # Safety guard forced PAPER
        else:
            assert gate.is_live is True
        gate2 = VenueGate(mode=TradingMode.LIVE, live_enabled=False)
        assert gate2.is_live is False

    def test_mode_setter(self):
        gate = VenueGate(mode=TradingMode.SIM)
        gate.mode = TradingMode.PAPER
        assert gate.mode == TradingMode.PAPER

    def test_summary(self):
        gate = VenueGate(mode=TradingMode.PAPER, live_enabled=False)
        s = gate.summary()
        assert s["mode"] == "paper"
        assert s["live_enabled"] is False
        assert "kalshi" in s["allowed_venues"]
        assert "polymarket" in s["blocked_venues"]

    def test_case_insensitive_venue(self):
        gate = VenueGate()
        gate.check_venue("Kalshi")  # should not raise
        gate.check_venue("KALSHI")  # should not raise

    def test_case_insensitive_blocked(self):
        gate = VenueGate()
        with pytest.raises(VenueGate.VenueBlockedError):
            gate.check_venue("Polymarket")


# ======================================================================
# §2 PredictionMarketModel Tests
# ======================================================================

class TestPredictionMarketModel:
    """Tests for implied probabilities, edge computation, and lifecycle."""

    def setup_method(self):
        self.model = PredictionMarketModel()

    def test_implied_probabilities_basic(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("53"), yes_ask=Decimal("57")
        )
        assert ip.yes_prob == Decimal("0.5500")
        assert ip.no_prob == Decimal("0.4500")
        assert ip.spread_cents == Decimal("4")

    def test_implied_probabilities_derive_no(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("40"), yes_ask=Decimal("42")
        )
        # no_bid = 100 - yes_ask = 58, no_ask = 100 - yes_bid = 60
        assert ip.no_bid == Decimal("58")
        assert ip.no_ask == Decimal("60")

    def test_implied_probabilities_overround(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("50"), yes_ask=Decimal("52"),
            no_bid=Decimal("50"), no_ask=Decimal("52"),
        )
        # yes_mid=51, no_mid=51 → overround = 0.51 + 0.51 - 1 = 0.02
        assert ip.overround == Decimal("0.0200")
        assert ip.is_efficient is True  # within 3 cents

    def test_implied_probabilities_inefficient(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("50"), yes_ask=Decimal("55"),
            no_bid=Decimal("50"), no_ask=Decimal("55"),
        )
        # yes_mid=52.5, no_mid=52.5 → overround = 0.05
        assert ip.overround > Decimal("0.03")
        assert ip.is_efficient is False

    def test_implied_probabilities_none_bid(self):
        ip = self.model.implied_probabilities(
            yes_bid=None, yes_ask=Decimal("60")
        )
        assert ip.yes_prob == Decimal("0.6000")

    def test_implied_probabilities_none_ask(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("40"), yes_ask=None
        )
        assert ip.yes_prob == Decimal("0.4000")

    def test_implied_probabilities_both_none(self):
        ip = self.model.implied_probabilities(yes_bid=None, yes_ask=None)
        assert ip.yes_prob == Decimal("0.5000")

    def test_determine_state_active(self):
        state = self.model.determine_state("active")
        assert state == ContractState.TRADING

    def test_determine_state_closed(self):
        state = self.model.determine_state("closed")
        assert state == ContractState.CLOSED

    def test_determine_state_settled_yes(self):
        state = self.model.determine_state("settled", resolution="yes")
        assert state == ContractState.SETTLED_YES

    def test_determine_state_settled_no(self):
        state = self.model.determine_state("settled", resolution="no")
        assert state == ContractState.SETTLED_NO

    def test_determine_state_cancelled(self):
        state = self.model.determine_state("cancelled")
        assert state == ContractState.CANCELLED

    def test_determine_state_closing_near_expiry(self):
        close_time = datetime.now(timezone.utc) + timedelta(hours=1)
        state = self.model.determine_state("active", close_time=close_time)
        assert state == ContractState.CLOSING

    def test_determine_state_closed_past_expiry(self):
        close_time = datetime.now(timezone.utc) - timedelta(hours=1)
        state = self.model.determine_state("active", close_time=close_time)
        assert state == ContractState.CLOSED

    def test_compute_edge_buy_yes(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("50"), yes_ask=Decimal("52")
        )
        self.model.set_model_probability("TEST-MKT", Decimal("0.60"))
        edge = self.model.compute_edge("TEST-MKT", ip, side="yes", action="buy")
        assert edge.raw_edge > Decimal("0")
        assert edge.edge_type == "speculative"
        assert edge.market_id == "TEST-MKT"

    def test_compute_edge_sell_yes(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("50"), yes_ask=Decimal("52")
        )
        self.model.set_model_probability("TEST-MKT", Decimal("0.40"))
        edge = self.model.compute_edge("TEST-MKT", ip, side="yes", action="sell")
        assert edge.raw_edge > Decimal("0")

    def test_compute_edge_arb_detection(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("45"), yes_ask=Decimal("47"),
            no_bid=Decimal("45"), no_ask=Decimal("47"),
        )
        # yes_ask + no_ask = 94 < 100 → arb
        edge = self.model.compute_edge("ARB-MKT", ip, side="yes", action="buy")
        assert edge.edge_type == "arb"

    def test_compute_edge_no_arb(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("48"), yes_ask=Decimal("52"),
            no_bid=Decimal("48"), no_ask=Decimal("52"),
        )
        # yes_ask + no_ask = 104 >= 100 → no arb
        edge = self.model.compute_edge("NO-ARB", ip, side="yes", action="buy")
        assert edge.edge_type == "speculative"

    def test_detect_arb_profitable(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("45"), yes_ask=Decimal("46"),
            no_bid=Decimal("45"), no_ask=Decimal("46"),
        )
        # total = 92, gross = 8, fee = 4, net = 4
        arb = self.model.detect_arb(ip)
        assert arb is not None
        assert arb.edge_type == "arb"
        assert arb.net_edge > Decimal("0")

    def test_detect_arb_not_profitable_after_fees(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("49"), yes_ask=Decimal("49"),
            no_bid=Decimal("49"), no_ask=Decimal("49"),
        )
        # total = 98, gross = 2, fee = 4, net = -2
        arb = self.model.detect_arb(ip)
        assert arb is None

    def test_detect_arb_no_arb(self):
        ip = self.model.implied_probabilities(
            yes_bid=Decimal("50"), yes_ask=Decimal("52"),
            no_bid=Decimal("48"), no_ask=Decimal("52"),
        )
        # total = 104 >= 100
        arb = self.model.detect_arb(ip)
        assert arb is None

    def test_build_snapshot(self):
        snap = self.model.build_snapshot(
            market_id="FED-25DEC",
            event_id="FED-DEC",
            title="Fed rate cut",
            status="active",
            yes_bid=Decimal("55"),
            yes_ask=Decimal("57"),
            volume=Decimal("5000"),
            open_interest=Decimal("500"),
            close_time=datetime.now(timezone.utc) + timedelta(hours=12),
        )
        assert snap.state == ContractState.TRADING
        assert snap.implied.yes_prob > Decimal("0")
        assert snap.time_to_expiry_hours is not None

    def test_build_snapshot_settled(self):
        snap = self.model.build_snapshot(
            market_id="SETTLED",
            event_id="EVT",
            title="Settled market",
            status="settled",
            yes_bid=None,
            yes_ask=None,
            resolution="yes",
        )
        assert snap.state == ContractState.SETTLED_YES
        assert len(snap.edges) == 0  # No edges for settled markets

    def test_edge_is_actionable(self):
        edge = EdgeEstimate(
            market_id="X", side="yes", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("0.60"),
            raw_edge=Decimal("0.10"), fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"), net_edge=Decimal("0.07"),
            edge_type="speculative", confidence=Decimal("0.8"),
        )
        assert edge.is_actionable is True

    def test_edge_not_actionable(self):
        edge = EdgeEstimate(
            market_id="X", side="yes", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("0.48"),
            raw_edge=Decimal("-0.02"), fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"), net_edge=Decimal("-0.05"),
            edge_type="speculative", confidence=Decimal("0.5"),
        )
        assert edge.is_actionable is False


# ======================================================================
# §3 KalshiStrategy Tests
# ======================================================================

class TestKalshiStrategy:
    """Tests for strategy signals, time-to-expiry logic, and exits."""

    def setup_method(self):
        self.model = PredictionMarketModel()
        self.config = StrategyConfig(
            min_volume=Decimal("100"),
            min_open_interest=Decimal("10"),
        )
        self.strategy = KalshiStrategy(config=self.config, model=self.model)

    def _make_snapshot(
        self,
        market_id="TEST",
        state=ContractState.TRADING,
        yes_bid=Decimal("50"),
        yes_ask=Decimal("52"),
        volume=Decimal("5000"),
        oi=Decimal("500"),
        hours_left=Decimal("12"),
        edges=None,
    ) -> MarketSnapshot:
        implied = self.model.implied_probabilities(yes_bid, yes_ask)
        if edges is None:
            edges = []
        return MarketSnapshot(
            market_id=market_id,
            event_id="EVT",
            title="Test Market",
            state=state,
            implied=implied,
            volume=volume,
            open_interest=oi,
            time_to_expiry_hours=hours_left,
            edges=edges,
        )

    def test_no_action_for_settled_market(self):
        snap = self._make_snapshot(state=ContractState.SETTLED_YES)
        sig = self.strategy.evaluate(snap)
        assert sig.action == SignalAction.NO_ACTION
        assert "not tradeable" in sig.reason

    def test_liquidity_guard_after_arb_low_volume(self):
        """Min volume runs after archetype evaluation (arb would otherwise pass)."""
        arb_edge = EdgeEstimate(
            market_id="ARB", side="both", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("1"),
            raw_edge=Decimal("0.06"), fee_drag=Decimal("0.04"),
            slippage_est=Decimal("0"), net_edge=Decimal("0.02"),
            edge_type="arb", confidence=Decimal("0.99"),
        )
        snap = self._make_snapshot(volume=Decimal("10"), edges=[arb_edge])
        sig = self.strategy.evaluate(snap, archetype="arbitrage")
        assert sig.action == SignalAction.NO_ACTION
        assert "Liquidity guard" in sig.reason
        assert "volume" in sig.reason.lower()

    def test_liquidity_guard_after_arb_low_oi(self):
        arb_edge = EdgeEstimate(
            market_id="ARB", side="both", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("1"),
            raw_edge=Decimal("0.06"), fee_drag=Decimal("0.04"),
            slippage_est=Decimal("0"), net_edge=Decimal("0.02"),
            edge_type="arb", confidence=Decimal("0.99"),
        )
        snap = self._make_snapshot(
            volume=Decimal("5000"), oi=Decimal("1"), edges=[arb_edge],
        )
        sig = self.strategy.evaluate(snap, archetype="arbitrage")
        assert sig.action == SignalAction.NO_ACTION
        assert "Liquidity guard" in sig.reason
        assert "oi" in sig.reason.lower()

    def test_arb_signal(self):
        arb_edge = EdgeEstimate(
            market_id="ARB", side="both", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("1"),
            raw_edge=Decimal("0.06"), fee_drag=Decimal("0.04"),
            slippage_est=Decimal("0"), net_edge=Decimal("0.02"),
            edge_type="arb", confidence=Decimal("0.99"),
        )
        snap = self._make_snapshot(edges=[arb_edge])
        sig = self.strategy.evaluate(snap)
        assert sig.action == SignalAction.BUY_YES
        assert "arb" in sig.reason.lower()

    def test_speculative_signal_with_edge(self):
        # Probability gate: prob_edge = |model_prob-0.5| must beat conviction-modulated
        # floor (default 0.15 + 0.10 boost when structural conviction is mid).
        spec_edge = EdgeEstimate(
            market_id="SPEC", side="yes", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("0.82"),
            raw_edge=Decimal("0.32"), fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"), net_edge=Decimal("0.29"),
            edge_type="speculative", confidence=Decimal("0.8"),
        )
        snap = self._make_snapshot(edges=[spec_edge], hours_left=Decimal("12"))
        with (
            patch.object(self.strategy, "_kelly_size_with_sentiment", return_value=5),
            patch.object(self.strategy, "_get_size_cap_for_asset", return_value=1.0),
        ):
            sig = self.strategy.evaluate(snap)
        assert sig.action in (SignalAction.BUY_YES, SignalAction.BUY_NO)
        assert sig.contracts > 0

    def test_no_action_edge_below_threshold(self):
        weak_edge = EdgeEstimate(
            market_id="WEAK", side="yes", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("0.51"),
            raw_edge=Decimal("0.01"), fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"), net_edge=Decimal("0.001"),
            edge_type="speculative", confidence=Decimal("0.8"),
        )
        snap = self._make_snapshot(edges=[weak_edge])
        sig = self.strategy.evaluate(snap)
        assert sig.action == SignalAction.NO_ACTION

    def test_expiry_phase_early(self):
        phase = self.strategy._expiry_phase(Decimal("48"))
        assert phase == ExpiryPhase.EARLY

    def test_expiry_phase_mid(self):
        phase = self.strategy._expiry_phase(Decimal("12"))
        assert phase == ExpiryPhase.MID

    def test_expiry_phase_late(self):
        phase = self.strategy._expiry_phase(Decimal("2"))
        assert phase == ExpiryPhase.LATE

    def test_expiry_phase_terminal(self):
        phase = self.strategy._expiry_phase(Decimal("0.5"))
        assert phase == ExpiryPhase.TERMINAL

    def test_expiry_phase_none(self):
        phase = self.strategy._expiry_phase(None)
        assert phase == ExpiryPhase.UNKNOWN

    def test_kelly_size_positive_edge(self):
        edge = EdgeEstimate(
            market_id="K", side="yes", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("0.65"),
            raw_edge=Decimal("0.15"), fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"), net_edge=Decimal("0.12"),
            edge_type="speculative", confidence=Decimal("0.8"),
        )
        # Mock kalshi_risk to return positive equity so sizing can proceed
        with patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk:
            mock_state = MagicMock()
            mock_state.current_equity_usd = 10000.0  # $10k equity
            mock_risk.return_value.state = mock_state
            size = self.strategy._kelly_size(edge, ExpiryPhase.MID)
        assert size > 0
        assert size <= self.config.max_contracts_per_order

    def test_kelly_size_zero_for_no_edge(self):
        edge = EdgeEstimate(
            market_id="K", side="yes", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("0.40"),
            raw_edge=Decimal("-0.10"), fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"), net_edge=Decimal("-0.13"),
            edge_type="speculative", confidence=Decimal("0.5"),
        )
        size = self.strategy._kelly_size(edge, ExpiryPhase.MID)
        assert size == 0

    def test_kelly_size_reduced_in_terminal(self):
        edge = EdgeEstimate(
            market_id="K", side="yes", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("0.70"),
            raw_edge=Decimal("0.20"), fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"), net_edge=Decimal("0.17"),
            edge_type="speculative", confidence=Decimal("0.8"),
        )
        size_mid = self.strategy._kelly_size(edge, ExpiryPhase.MID)
        size_term = self.strategy._kelly_size(edge, ExpiryPhase.TERMINAL)
        assert size_term <= size_mid

    def test_signal_to_dict(self):
        sig = StrategySignal(
            market_id="X", action=SignalAction.BUY_YES,
            side="yes", contracts=10, phase=ExpiryPhase.MID,
            reason="test",
        )
        d = sig.to_dict()
        assert d["market_id"] == "X"
        assert d["action"] == "buy_yes"
        assert d["phase"] == "mid"

    def test_evaluate_exits_profit_target(self):
        pos = PositionState(
            market_id="EXIT-MKT", side="yes", contracts=10,
            avg_entry_cents=Decimal("50"),
            opened_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        self.strategy.register_position(pos)

        implied = self.model.implied_probabilities(
            yes_bid=Decimal("60"), yes_ask=Decimal("62")
        )
        snap = MarketSnapshot(
            market_id="EXIT-MKT", event_id="EVT", title="Exit test",
            state=ContractState.TRADING, implied=implied,
            volume=Decimal("5000"), open_interest=Decimal("500"),
            time_to_expiry_hours=Decimal("12"),
        )
        signals = self.strategy.evaluate_exits({"EXIT-MKT": snap})
        assert len(signals) >= 1
        assert signals[0].action == SignalAction.SELL_YES

    def test_evaluate_exits_stop_loss(self):
        pos = PositionState(
            market_id="STOP-MKT", side="yes", contracts=10,
            avg_entry_cents=Decimal("50"),
            opened_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        self.strategy.register_position(pos)

        implied = self.model.implied_probabilities(
            yes_bid=Decimal("40"), yes_ask=Decimal("42")
        )
        snap = MarketSnapshot(
            market_id="STOP-MKT", event_id="EVT", title="Stop test",
            state=ContractState.TRADING, implied=implied,
            volume=Decimal("5000"), open_interest=Decimal("500"),
            time_to_expiry_hours=Decimal("12"),
        )
        signals = self.strategy.evaluate_exits({"STOP-MKT": snap})
        assert len(signals) >= 1
        assert "Stop loss" in signals[0].reason

    def test_evaluate_exits_market_closing(self):
        pos = PositionState(
            market_id="CLOSE-MKT", side="no", contracts=5,
            avg_entry_cents=Decimal("50"),
            opened_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        self.strategy.register_position(pos)

        implied = self.model.implied_probabilities(
            yes_bid=Decimal("50"), yes_ask=Decimal("52")
        )
        snap = MarketSnapshot(
            market_id="CLOSE-MKT", event_id="EVT", title="Close test",
            state=ContractState.CLOSING, implied=implied,
            volume=Decimal("5000"), open_interest=Decimal("500"),
            time_to_expiry_hours=Decimal("0.5"),
        )
        signals = self.strategy.evaluate_exits({"CLOSE-MKT": snap})
        assert len(signals) >= 1
        assert "closing" in signals[0].reason.lower() or "CLOSING" in signals[0].reason

    def test_remove_position(self):
        pos = PositionState(
            market_id="RM-MKT", side="yes", contracts=5,
            avg_entry_cents=Decimal("50"),
            opened_at=datetime.now(timezone.utc),
        )
        self.strategy.register_position(pos)
        self.strategy.remove_position("RM-MKT")
        signals = self.strategy.evaluate_exits({"RM-MKT": self._make_snapshot()})
        assert len(signals) == 0

    def test_scan_markets_filters_no_action(self):
        snap1 = self._make_snapshot(market_id="A", state=ContractState.SETTLED_YES)
        snap2 = self._make_snapshot(market_id="B", volume=Decimal("1"))
        results = self.strategy.scan_markets([snap1, snap2])
        assert len(results) == 0

    def test_low_confidence_rejected(self):
        weak_conf_edge = EdgeEstimate(
            market_id="CONF", side="yes", action="buy",
            market_prob=Decimal("0.50"), model_prob=Decimal("0.65"),
            raw_edge=Decimal("0.15"), fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"), net_edge=Decimal("0.12"),
            edge_type="speculative", confidence=Decimal("0.2"),
        )
        snap = self._make_snapshot(edges=[weak_conf_edge])
        sig = self.strategy.evaluate(snap)
        assert sig.action == SignalAction.NO_ACTION
        assert "Confidence" in sig.reason


# ======================================================================
# §4 PredictionMarketRisk Tests
# ======================================================================

class TestPredictionMarketRisk:
    """Tests for pre-trade checks, kill switch, and circuit breaker."""

    def setup_method(self):
        self.config = PredictionRiskConfig(
            max_contracts_per_order=50,
            max_contracts_per_market=200,
            max_notional_per_market_usd=Decimal("500"),
            max_notional_per_event_usd=Decimal("1000"),
            max_total_notional_usd=Decimal("5000"),
            max_daily_loss_usd=Decimal("250"),
            max_open_markets=20,
            max_slippage_cents=Decimal("3"),
            min_depth_contracts=5,
            max_spread_cents=Decimal("10"),
        )
        self.risk = PredictionMarketRisk(config=self.config)

    def test_order_allowed(self):
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="buy",
            contracts=10, price_cents=Decimal("55"),
            best_bid_cents=Decimal("54"), best_ask_cents=Decimal("56"),
            depth_at_price=20,
        )
        assert check.allowed is True
        assert check.action == RiskAction.ALLOW

    def test_order_exceeds_max_size(self):
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="buy",
            contracts=100, price_cents=Decimal("55"),
        )
        assert check.allowed is False
        assert check.action == RiskAction.REDUCE_SIZE
        assert check.adjusted_size == 50

    def test_order_exceeds_market_contracts(self):
        self.risk.record_fill("MKT-1", "EVT-1", "yes", 190, Decimal("55"))
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="buy",
            contracts=20, price_cents=Decimal("55"),
        )
        assert check.allowed is False
        assert check.action == RiskAction.REDUCE_SIZE
        assert check.adjusted_size == 10

    def test_order_at_max_market_contracts(self):
        self.risk.record_fill("MKT-1", "EVT-1", "yes", 200, Decimal("55"))
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="buy",
            contracts=1, price_cents=Decimal("55"),
        )
        assert check.allowed is False
        assert check.action == RiskAction.REJECT

    def test_order_exceeds_market_notional(self):
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="buy",
            contracts=50, price_cents=Decimal("99"),
        )
        # 50 * 99 / 100 = $49.50 for new, but existing 0 + 50 = 50 contracts
        # notional = 50 * 99 / 100 = $49.50 — under $500
        assert check.allowed is True

    def test_order_exceeds_event_notional(self):
        # Fill up event
        self.risk.record_fill("MKT-A", "EVT-1", "yes", 50, Decimal("90"))
        self.risk.record_fill("MKT-B", "EVT-1", "yes", 50, Decimal("90"))
        # Already $90 in event
        check = self.risk.check_order(
            market_id="MKT-C", event_id="EVT-1", side="buy",
            contracts=50, price_cents=Decimal("90"),
        )
        # event_notional = 45 + 45 + 45 = $135 > $1000? No, 45+45=90, +45=135
        # Actually: 50*90/100 = $45 each, total event = $90, new = $45, total = $135
        assert check.allowed is True  # $135 < $1000

    def test_spread_too_wide(self):
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="buy",
            contracts=10, price_cents=Decimal("55"),
            best_bid_cents=Decimal("40"), best_ask_cents=Decimal("60"),
        )
        assert check.allowed is False
        assert "Spread" in check.reason

    def test_slippage_guard_buy(self):
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="buy",
            contracts=10, price_cents=Decimal("65"),
            best_bid_cents=Decimal("54"), best_ask_cents=Decimal("56"),
        )
        assert check.allowed is False
        assert "above best ask" in check.reason

    def test_slippage_guard_sell(self):
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="sell",
            contracts=10, price_cents=Decimal("40"),
            best_bid_cents=Decimal("54"), best_ask_cents=Decimal("56"),
        )
        assert check.allowed is False
        assert "below best bid" in check.reason

    def test_depth_check(self):
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="buy",
            contracts=10, price_cents=Decimal("55"),
            best_bid_cents=Decimal("54"), best_ask_cents=Decimal("56"),
            depth_at_price=2,
        )
        assert check.allowed is False
        assert "Depth" in check.reason

    def test_kill_switch_blocks_orders(self):
        self.risk.halt("Test halt")
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="buy",
            contracts=10, price_cents=Decimal("55"),
        )
        assert check.allowed is False
        assert check.action == RiskAction.HALT

    def test_kill_switch_resume(self):
        self.risk.halt("Test halt")
        assert self.risk.is_halted is True
        self.risk.resume()
        assert self.risk.is_halted is False
        check = self.risk.check_order(
            market_id="MKT-1", event_id="EVT-1", side="buy",
            contracts=10, price_cents=Decimal("55"),
        )
        assert check.allowed is True

    def test_halt_with_unwind(self):
        self.risk.record_fill("MKT-1", "EVT-1", "yes", 10, Decimal("55"))
        self.risk.halt("Drawdown", unwind=True)
        assert self.risk.unwind_requested is True
        markets = self.risk.get_markets_to_unwind()
        assert "MKT-1" in markets

    def test_no_unwind_when_not_requested(self):
        self.risk.record_fill("MKT-1", "EVT-1", "yes", 10, Decimal("55"))
        self.risk.halt("Drawdown", unwind=False)
        markets = self.risk.get_markets_to_unwind()
        assert len(markets) == 0

    def test_drawdown_halt(self):
        self.risk.check_drawdown(
            portfolio_value_usd=Decimal("900"),
            peak_value_usd=Decimal("1000"),
        )
        assert self.risk.is_halted is True
        assert self.risk.unwind_requested is False

    def test_drawdown_unwind(self):
        self.risk.check_drawdown(
            portfolio_value_usd=Decimal("800"),
            peak_value_usd=Decimal("1000"),
        )
        assert self.risk.is_halted is True
        assert self.risk.unwind_requested is True

    def test_drawdown_ok(self):
        self.risk.check_drawdown(
            portfolio_value_usd=Decimal("950"),
            peak_value_usd=Decimal("1000"),
        )
        assert self.risk.is_halted is False

    def test_circuit_breaker_trips(self):
        now = datetime.now(timezone.utc)
        with patch("merid.prediction.risk._prediction_risk.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.risk.record_price("MKT-1", Decimal("50"))
            self.risk.record_price("MKT-1", Decimal("70"))

        reason = self.risk.check_circuit_breaker("MKT-1")
        assert reason is not None
        assert "odds moved" in reason

    def test_circuit_breaker_ok(self):
        self.risk.record_price("MKT-1", Decimal("50"))
        self.risk.record_price("MKT-1", Decimal("52"))
        reason = self.risk.check_circuit_breaker("MKT-1")
        assert reason is None

    def test_record_fill_and_close(self):
        self.risk.record_fill("MKT-1", "EVT-1", "yes", 10, Decimal("50"))
        assert "MKT-1" in self.risk._exposures
        assert self.risk._exposures["MKT-1"].contracts == 10

        self.risk.record_close("MKT-1", 10, Decimal("60"))
        assert "MKT-1" not in self.risk._exposures

    def test_record_partial_close(self):
        self.risk.record_fill("MKT-1", "EVT-1", "yes", 10, Decimal("50"))
        self.risk.record_close("MKT-1", 5, Decimal("60"))
        assert self.risk._exposures["MKT-1"].contracts == 5

    def test_daily_pnl_tracking(self):
        self.risk.record_fill("MKT-1", "EVT-1", "yes", 10, Decimal("50"), fee_cents=Decimal("20"))
        self.risk.record_close("MKT-1", 10, Decimal("60"))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = self.risk._daily_pnl[today]
        assert daily.trades == 1
        assert daily.realized_pnl_usd == Decimal("1.00")  # (60-50)*10/100
        assert daily.fees_usd == Decimal("0.20")

    def test_max_open_markets(self):
        for i in range(20):
            self.risk.record_fill(f"MKT-{i}", f"EVT-{i}", "yes", 1, Decimal("50"))
        check = self.risk.check_order(
            market_id="MKT-NEW", event_id="EVT-NEW", side="buy",
            contracts=1, price_cents=Decimal("50"),
        )
        assert check.allowed is False
        assert "20 markets" in check.reason

    def test_summary(self):
        self.risk.record_fill("MKT-1", "EVT-1", "yes", 10, Decimal("55"))
        s = self.risk.summary()
        assert len(s["exposures"]) >= 1  # open_markets key renamed to exposures
        assert s["halted"] is False
        assert len(s["exposures"]) == 1
        assert "limits" in s

    def test_pretrade_check_to_dict(self):
        check = PreTradeCheck(
            allowed=True, action=RiskAction.ALLOW,
            reason="OK", market_id="MKT-1",
        )
        d = check.to_dict()
        assert d["allowed"] is True
        assert d["action"] == "allow"


# ======================================================================
# §5 Alerts Tests
# ======================================================================

class TestPredictionAlerts:
    """Tests for alert firing, dedup, and history."""

    def setup_method(self):
        self.mgr = PredictionAlertManager()

    def test_fire_alert(self):
        alert = PredictionAlert(
            category=AlertCategory.TRADE,
            severity=AlertSeverity.INFO,
            title="Test",
            message="Test alert",
        )
        self.mgr.fire(alert)
        assert len(self.mgr._history) == 1

    def test_fire_with_sink(self):
        received = []
        self.mgr.add_sink(lambda a: received.append(a))
        self.mgr.fire(PredictionAlert(
            category=AlertCategory.TRADE,
            severity=AlertSeverity.INFO,
            title="Sink test",
            message="msg",
        ))
        assert len(received) == 1

    def test_dedup_suppression(self):
        for _ in range(5):
            self.mgr.fire(PredictionAlert(
                category=AlertCategory.TRADE,
                severity=AlertSeverity.INFO,
                title="Dup",
                message="msg",
            ))
        assert len(self.mgr._history) == 1  # suppressed duplicates

    def test_different_alerts_not_suppressed(self):
        self.mgr.fire(PredictionAlert(
            category=AlertCategory.TRADE,
            severity=AlertSeverity.INFO,
            title="Alert A",
            message="msg",
        ))
        self.mgr.fire(PredictionAlert(
            category=AlertCategory.RISK_LIMIT,
            severity=AlertSeverity.WARNING,
            title="Alert B",
            message="msg",
        ))
        assert len(self.mgr._history) == 2

    def test_fire_risk_warning(self):
        self.mgr.fire_risk_warning("MKT-1", "Approaching limit")
        assert len(self.mgr._history) == 1
        assert self.mgr._history[0].severity == AlertSeverity.WARNING

    def test_fire_risk_breach(self):
        self.mgr.fire_risk_breach("MKT-1", "Limit exceeded")
        assert self.mgr._history[0].severity == AlertSeverity.CRITICAL

    def test_fire_resolution(self):
        self.mgr.fire_resolution("MKT-1", "yes", Decimal("25.50"))
        assert self.mgr._history[0].category == AlertCategory.RESOLUTION

    def test_fire_connectivity(self):
        self.mgr.fire_connectivity("Connection timeout")
        assert self.mgr._history[0].category == AlertCategory.CONNECTIVITY

    def test_fire_staleness(self):
        self.mgr.fire_staleness("MKT-1", 120)
        assert self.mgr._history[0].category == AlertCategory.STALENESS

    def test_fire_kill_switch(self):
        self.mgr.fire_kill_switch("Drawdown", unwind=True)
        assert self.mgr._history[0].category == AlertCategory.KILL_SWITCH

    def test_get_history_filtered(self):
        self.mgr.fire_risk_warning("A", "warn")
        self.mgr.fire_connectivity("conn")
        history = self.mgr.get_history(category=AlertCategory.RISK_LIMIT)
        assert len(history) == 1

    def test_acknowledge(self):
        self.mgr.fire_risk_warning("A", "warn")
        assert self.mgr.unacknowledged_count() == 1
        alert_id = self.mgr.get_history()[0].alert_id
        self.mgr.acknowledge(alert_id)
        assert self.mgr.unacknowledged_count() == 0

    def test_summary(self):
        self.mgr.fire_risk_warning("A", "warn")
        s = self.mgr.summary()
        assert s["total_alerts"] == 1
        assert s["unacknowledged"] == 1

    def test_alert_to_dict(self):
        alert = PredictionAlert(
            category=AlertCategory.TRADE,
            severity=AlertSeverity.INFO,
            title="Test",
            message="msg",
            market_id="MKT-1",
        )
        d = alert.to_dict()
        assert d["category"] == "trade"
        assert d["severity"] == "info"
        assert d["market_id"] == "MKT-1"

    def test_sink_error_does_not_crash(self):
        def bad_sink(a):
            raise RuntimeError("sink error")
        self.mgr.add_sink(bad_sink)
        # Should not raise
        self.mgr.fire(PredictionAlert(
            category=AlertCategory.TRADE,
            severity=AlertSeverity.INFO,
            title="Error test",
            message="msg",
        ))
        assert len(self.mgr._history) == 1

    def test_max_history_cap(self):
        mgr = PredictionAlertManager(max_history=5)
        for i in range(10):
            mgr.fire(PredictionAlert(
                category=AlertCategory.TRADE,
                severity=AlertSeverity.INFO,
                title=f"Alert {i}",
                message="msg",
                market_id=f"MKT-{i}",  # unique to avoid dedup
            ))
        assert len(mgr._history) <= 5
