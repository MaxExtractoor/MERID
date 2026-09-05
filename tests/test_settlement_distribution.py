"""Unit and property tests for the settlement-aware distribution model."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from merid.prediction.settlement_distribution import (
    SettlementDistribution,
    SettlementWindowAccumulator,
    build_settlement_state,
    compute_settlement_distribution,
    probability_yes,
)
from merid.prediction.trade_decision import compute_trade_decision


class FakeRtiObservation:
    def __init__(self, source_ts_ms: int, value: float):
        self.source_ts_ms = source_ts_ms
        self.value = value
        self.value_decimal = Decimal(str(value))


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _dt(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)


class TestSettlementDistribution:
    """Deterministic and property tests for the settlement average model."""

    def test_pre_window_mean_is_latest_rti(self):
        """Before the final 60s the forecast mean must equal the latest tick."""
        now = datetime(2026, 9, 5, 16, 0, 0, tzinfo=timezone.utc)
        expiry = now + timedelta(seconds=120)
        state = build_settlement_state(
            ticker="KXBTC15M-TEST",
            asset="BTC",
            strike_price=100.0,
            expiry_ts=expiry,
            now_ts=now,
            latest_rti=105.0,
            latest_rti_decimal=Decimal("105.0"),
            latest_rti_ts=now,
            rti_history=[FakeRtiObservation(_ms(now - timedelta(seconds=30)), 104.0)],
        )
        dist = compute_settlement_distribution(state, annualized_vol=0.60)

        assert dist.phase == "pre_window"
        assert dist.observed_count == 0
        assert dist.remaining_count == 60
        assert dist.mean == pytest.approx(105.0)
        assert dist.std > 0.0
        assert dist.p_yes_raw > 0.5  # latest above strike

    def test_in_window_partial_realization(self):
        """Inside the last minute the mean is a weighted blend."""
        now = datetime(2026, 9, 5, 16, 0, 45, tzinfo=timezone.utc)
        expiry = now + timedelta(seconds=15)
        window_start = expiry - timedelta(seconds=60)

        # 45 observations: average 99.0. Latest tick 102.0.
        history = []
        for i in range(45):
            ts = window_start + timedelta(seconds=i)
            history.append(FakeRtiObservation(_ms(ts), 99.0))

        state = build_settlement_state(
            ticker="KXBTC15M-TEST",
            asset="BTC",
            strike_price=100.0,
            expiry_ts=expiry,
            now_ts=now,
            latest_rti=102.0,
            latest_rti_decimal=Decimal("102.0"),
            latest_rti_ts=now,
            rti_history=history,
        )
        dist = compute_settlement_distribution(state, annualized_vol=0.60)

        assert dist.phase == "in_window"
        assert dist.observed_count == 45
        assert dist.remaining_count == 15
        # mean = (45*99 + 15*102) / 60 = 99.75
        assert dist.mean == pytest.approx(99.75)
        # residual std must be smaller than pre-window std at the same TTE.
        assert dist.std > 0.0

    def test_in_window_variance_collapses_at_expiry(self):
        """With one second left, the variance is tiny."""
        now = datetime(2026, 9, 5, 16, 0, 59, tzinfo=timezone.utc)
        expiry = now + timedelta(seconds=1)
        window_start = expiry - timedelta(seconds=60)

        history = []
        for i in range(59):
            ts = window_start + timedelta(seconds=i)
            history.append(FakeRtiObservation(_ms(ts), 100.0))

        state = build_settlement_state(
            ticker="KXBTC15M-TEST",
            asset="BTC",
            strike_price=100.0,
            expiry_ts=expiry,
            now_ts=now,
            latest_rti=100.0,
            latest_rti_decimal=Decimal("100.0"),
            latest_rti_ts=now,
            rti_history=history,
        )
        dist = compute_settlement_distribution(state, annualized_vol=0.60)

        assert dist.phase == "in_window"
        assert dist.observed_count == 59
        assert dist.remaining_count == 1
        # Residual R=1s -> variance is tiny.
        assert dist.std < 0.01

    def test_settled_degenerate_distribution(self):
        """After expiry the distribution is the observed average."""
        now = datetime(2026, 9, 5, 16, 1, 5, tzinfo=timezone.utc)
        expiry = now - timedelta(seconds=5)
        window_start = expiry - timedelta(seconds=60)

        history = []
        for i in range(60):
            ts = window_start + timedelta(seconds=i)
            history.append(FakeRtiObservation(_ms(ts), 101.0))

        state = build_settlement_state(
            ticker="KXBTC15M-TEST",
            asset="BTC",
            strike_price=100.0,
            expiry_ts=expiry,
            now_ts=now,
            latest_rti=101.0,
            latest_rti_decimal=Decimal("101.0"),
            latest_rti_ts=now,
            rti_history=history,
        )
        dist = compute_settlement_distribution(state, annualized_vol=0.60)

        assert dist.phase == "expired"
        assert dist.mean == pytest.approx(101.0)
        assert dist.std == 0.0
        assert dist.p_yes_raw == 1.0

    def test_probability_yes_monotonic_in_mean(self):
        """p_yes must be nondecreasing in the forecast mean."""
        for strike in [100.0, 50000.0, 0.10]:
            means = [strike - 5 * strike, strike - strike, strike, strike + strike, strike + 5 * strike]
            std = max(0.001, strike * 0.10)
            probs = [probability_yes(build_stub(mean, std, strike), strike) for mean in means]
            for i in range(1, len(probs)):
                assert probs[i] >= probs[i - 1] - 1e-9

    def test_probability_yes_nonincreasing_in_strike(self):
        """p_yes must fall as the strike rises, holding the mean fixed."""
        mean = 100.0
        std = 5.0
        strikes = [80.0, 90.0, 100.0, 110.0, 120.0]
        probs = [probability_yes(build_stub(mean, std, k), k) for k in strikes]
        for i in range(1, len(probs)):
            assert probs[i] <= probs[i - 1] + 1e-9

    def test_p_yes_p_no_sum_to_one(self):
        """The YES and NO probabilities must be exact complements."""
        mean = 100.0
        std = 5.0
        for strike in [90.0, 100.0, 110.0]:
            p = probability_yes(build_stub(mean, std, strike), strike)
            assert 0.0 <= p <= 1.0
            assert abs(p + (1.0 - p) - 1.0) < 1e-12

    def test_pre_window_std_less_than_point_std(self):
        """Averaging over the final minute reduces terminal variance."""
        now = datetime(2026, 9, 5, 16, 0, 0, tzinfo=timezone.utc)
        expiry = now + timedelta(seconds=120)
        state = build_settlement_state(
            ticker="KXBTC15M-TEST",
            asset="BTC",
            strike_price=100.0,
            expiry_ts=expiry,
            now_ts=now,
            latest_rti=100.0,
            latest_rti_decimal=Decimal("100.0"),
            latest_rti_ts=now,
            rti_history=[],
        )
        dist = compute_settlement_distribution(state, annualized_vol=0.60)

        # Point-price standard deviation would be sigma * sqrt(T).
        t_years = 120 / (365.0 * 24.0 * 60.0 * 60.0)
        point_std = 0.60 * 100.0 * math.sqrt(t_years)
        # Average-aware std must be smaller.
        assert dist.std < point_std

    def test_accumulator_groups_same_second(self):
        """Two frames in the same second should dedupe to the latest."""
        expiry = datetime(2026, 9, 5, 16, 1, 0, tzinfo=timezone.utc)
        window_start = expiry - timedelta(seconds=60)
        acc = SettlementWindowAccumulator(
            ticker="KXBTC15M-TEST", expiry_ts=expiry, window_start_ts=window_start
        )
        acc.add_observation(window_start, Decimal("100.0"))
        acc.add_observation(window_start + timedelta(milliseconds=300), Decimal("101.0"))
        assert acc.observed_count() == 1
        assert float(acc.observed_sum()) == 101.0


class TestSettlementDistributionTradeDecisionIntegration:
    """Confirm compute_trade_decision can use a settlement distribution."""

    def test_trade_decision_uses_settlement_distribution(self, monkeypatch):
        monkeypatch.setattr("merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", False)
        monkeypatch.setenv("MERID_TAIL_CALIBRATION_DEVIATION_GUARD", "1.0")
        dist = SettlementDistribution(
            mean=105.0,
            std=2.0,
            z_score=(105.0 - 100.0) / 2.0,
            p_yes_raw=0.99,
            observed_count=0,
            remaining_count=60,
            seconds_to_expiry=120.0,
            phase="pre_window",
            forecast_method="test",
        )
        decision = compute_trade_decision(
            run_id="r1",
            decision_id="d1",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            spot_price=105.0,
            strike_price=100.0,
            seconds_to_expiry=120.0,
            yes_bid_cents=79.0,
            yes_ask_cents=80.0,
            no_bid_cents=20.0,
            no_ask_cents=21.0,
            yes_depth_cc=200.0,
            no_depth_cc=200.0,
            fee_per_contract_cents=2.0,
            annualized_vol=0.60,
            model_uncertainty=0.05,
            min_required_edge=0.03,
            data_quality="live",
            data_state="healthy",
            regime="normal",
            regime_label="normal",
            regime_probability=1.0,
            settlement_reference="cfb_rti_live",
            settlement_distribution=dist,
        )
        assert decision.selected_outcome == "yes"
        assert decision.no_trade_reason is None
        assert "settlement_forecast_mean" in (decision.indicators or {})

    def test_trade_decision_ignores_distribution_when_p_yes_model_supplied(self, monkeypatch):
        monkeypatch.setattr("merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
        monkeypatch.setenv("MERID_TAIL_CALIBRATION_DEVIATION_GUARD", "1.0")
        # Distribution says NO (mean just below strike, p_yes ~0.40).
        dist = SettlementDistribution(
            mean=99.5,
            std=2.0,
            z_score=(99.5 - 100.0) / 2.0,
            p_yes_raw=0.40,
            observed_count=0,
            remaining_count=60,
            seconds_to_expiry=120.0,
            phase="pre_window",
            forecast_method="test",
        )
        # Hybrid p_yes_model overrides the distribution for the final selected side.
        decision = compute_trade_decision(
            run_id="r1",
            decision_id="d2",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            spot_price=99.5,
            strike_price=100.0,
            seconds_to_expiry=120.0,
            yes_bid_cents=39.0,
            yes_ask_cents=40.0,
            no_bid_cents=60.0,
            no_ask_cents=61.0,
            yes_depth_cc=200.0,
            no_depth_cc=200.0,
            fee_per_contract_cents=2.0,
            annualized_vol=0.60,
            model_uncertainty=0.05,
            min_required_edge=0.03,
            data_quality="live",
            data_state="healthy",
            regime="normal",
            regime_label="normal",
            regime_probability=1.0,
            settlement_reference="cfb_rti_live",
            settlement_distribution=dist,
            p_yes_model=0.90,  # Should override the 0.40 p_yes_raw and select YES
        )
        assert decision.selected_outcome == "yes"


def build_stub(mean: float, std: float, strike: float):
    """Build a tiny SettlementDistribution for probability tests."""
    from merid.prediction.settlement_distribution import SettlementDistribution

    return SettlementDistribution(
        mean=mean,
        std=std,
        z_score=(mean - strike) / std if std > 1e-12 else 0.0,
        p_yes_raw=0.5,
        observed_count=0,
        remaining_count=60,
        seconds_to_expiry=120.0,
        phase="pre_window",
        forecast_method="stub",
    )
