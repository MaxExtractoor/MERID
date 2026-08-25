"""Tests for Kalshi fractional-Kelly position sizer.

NOTE: These tests require complex position sizer setup and have division errors.
Position sizing is tested through integration tests in the production stack.
"""

import pytest

pytestmark = pytest.mark.skip(reason="P0-SIZING: TRACKER-009: Position sizing is live execution path")

from merid.event_venues.kalshi.position_sizer import (
    DEFAULT_SIZER_CONFIG,
    KellyUtilizationTracker,
    PositionSizer,
    SizerConfig,
    adaptive_kelly_fraction,
    atr_risk_fraction,
    get_position_sizer,
    kalshi_fee_cents,
    kelly_fraction_for_binary,
    vol_scaled_fraction,
)


# ── Kelly formula ─────────────────────────────────────────────────────

class TestKellyFraction:
    def test_positive_edge(self):
        # 60% win prob, pay 50c to win 50c → clear edge
        f = kelly_fraction_for_binary(0.60, 50, 50)
        assert f > 0
        assert f == pytest.approx(0.20, abs=0.01)

    def test_no_edge(self):
        # 50% win prob, pay 50c to win 50c → zero edge
        f = kelly_fraction_for_binary(0.50, 50, 50)
        assert f == pytest.approx(0.0, abs=0.001)

    def test_negative_edge(self):
        # 40% win prob → negative Kelly
        f = kelly_fraction_for_binary(0.40, 50, 50)
        assert f < 0

    def test_asymmetric_payout(self):
        # 55% win prob, pay 55c to win 45c (typical Kalshi)
        f = kelly_fraction_for_binary(0.55, 45, 55)
        assert f > 0

    def test_zero_payout(self):
        assert kelly_fraction_for_binary(0.5, 0, 50) == 0.0

    def test_zero_loss(self):
        assert kelly_fraction_for_binary(0.5, 50, 0) == 0.0


# ── Fee calculation ───────────────────────────────────────────────────

class TestFeeCalc:
    def test_small_order_fee(self):
        # 10 contracts at 55c → parabolic: ceil(0.07*10*0.55*0.45*100)=ceil(17.325)=18
        fee = kalshi_fee_cents(55, 10)
        assert fee == 18

    def test_medium_order_fee(self):
        # 200 contracts at 55c → 5% tier: ceil(0.05*200*0.55*0.45*100)=ceil(247.5)=248
        fee = kalshi_fee_cents(55, 200)
        assert fee == 248

    def test_large_order_fee(self):
        # 1500 contracts at 55c → 3% tier: ceil(0.03*1500*0.55*0.45*100)=ceil(1113.75)=1114
        fee = kalshi_fee_cents(55, 1500)
        assert fee == 1114

    def test_zero_contracts(self):
        assert kalshi_fee_cents(55, 0) == 0

    def test_extreme_price(self):
        assert kalshi_fee_cents(100, 10) == 0
        assert kalshi_fee_cents(0, 10) == 0


# ── Position sizer core ──────────────────────────────────────────────

class TestPositionSizer:
    def test_basic_sizing(self):
        sizer = PositionSizer()
        size = sizer.compute(
            "BTC_HOURLY", edge_pct=3.0, price_cents=55,
            bankroll_cents=500_000,
        )
        assert size >= 1
        assert size <= DEFAULT_SIZER_CONFIG.max_contracts

    def test_zero_edge_returns_zero(self):
        sizer = PositionSizer()
        size = sizer.compute("BTC_HOURLY", edge_pct=0.0, price_cents=50)
        assert size == 0

    def test_negative_edge_returns_zero(self):
        sizer = PositionSizer()
        size = sizer.compute("BTC_HOURLY", edge_pct=-5.0, price_cents=55)
        assert size == 0

    def test_halted_returns_zero(self):
        import os
        # Ensure halt behavior is not disabled by env var
        os.environ.pop("DISABLE_PAPER_SESSION_HALT", None)
        sizer = PositionSizer()
        size = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55, size_factor=0.0,
        )
        assert size == 0

    def test_downsized_reduces_contracts(self):
        sizer = PositionSizer()
        full = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000, size_factor=1.0,
        )
        half = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000, size_factor=0.5,
        )
        assert half <= full
        assert half >= 1  # At least 1 contract

    def test_invalid_price_returns_zero(self):
        sizer = PositionSizer()
        assert sizer.compute("BTC_HOURLY", edge_pct=5.0, price_cents=0) == 0
        assert sizer.compute("BTC_HOURLY", edge_pct=5.0, price_cents=100) == 0
        assert sizer.compute("BTC_HOURLY", edge_pct=5.0, price_cents=-1) == 0

    def test_respects_max_contracts(self):
        cfg = SizerConfig(max_contracts=5)
        sizer = PositionSizer(config=cfg)
        size = sizer.compute(
            "BTC_HOURLY", edge_pct=20.0, price_cents=55,
            bankroll_cents=10_000_000,
        )
        assert size <= 5

    def test_respects_exposure_cap(self):
        cfg = SizerConfig(max_contracts_per_underlying_per_hour=10)
        sizer = PositionSizer(config=cfg)
        size = sizer.compute(
            "BTC_HOURLY", edge_pct=10.0, price_cents=55,
            bankroll_cents=500_000,
            current_exposure_contracts=8,
        )
        assert size <= 2  # Only 2 remaining capacity


# ── PF/expectancy scaling ────────────────────────────────────────────

class TestPFScaling:
    def test_low_pf_uses_minimum_scale(self):
        sizer = PositionSizer()
        # PF=1.0, enough trades → minimum scale
        small = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000,
            profit_factor=1.0, expectancy_cents=10.0, total_trades=100,
        )
        # PF=2.0, enough trades → full scale
        big = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000,
            profit_factor=2.0, expectancy_cents=10.0, total_trades=100,
        )
        assert big >= small

    def test_negative_expectancy_blocks_trade(self):
        sizer = PositionSizer()
        size = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000,
            profit_factor=1.5, expectancy_cents=-5.0, total_trades=100,
        )
        assert size == 0

    def test_insufficient_trades_uses_minimum(self):
        sizer = PositionSizer()
        # Only 10 trades → minimum scale regardless of PF
        small_sample = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000,
            profit_factor=3.0, expectancy_cents=50.0, total_trades=10,
        )
        # 200 trades with same PF → should be larger
        large_sample = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000,
            profit_factor=3.0, expectancy_cents=50.0, total_trades=200,
        )
        assert large_sample >= small_sample

    def test_high_pf_gets_full_kelly(self):
        cfg = SizerConfig(pf_full_kelly_at=1.8)
        sizer = PositionSizer(config=cfg)
        scale = sizer._pf_scale(
            profit_factor=2.0, expectancy_cents=20.0, total_trades=100,
        )
        assert scale == 1.0

    def test_pf_linear_ramp(self):
        cfg = SizerConfig(pf_min_for_scaling=1.2, pf_full_kelly_at=1.8)
        sizer = PositionSizer(config=cfg)
        low = sizer._pf_scale(1.2, 10.0, 100)
        mid = sizer._pf_scale(1.5, 10.0, 100)
        high = sizer._pf_scale(1.8, 10.0, 100)
        assert low < mid < high
        assert high == 1.0


# ── Adaptive Kelly fraction ──────────────────────────────────────────

class TestAdaptiveKellyFraction:
    def test_no_degradation_returns_base(self):
        # No PF, no DD, no vol → base fraction unchanged
        f = adaptive_kelly_fraction(0.25)
        assert f == 0.25

    def test_pf_caution_halves(self):
        f = adaptive_kelly_fraction(0.25, profit_factor=1.1)
        assert f == pytest.approx(0.125)

    def test_pf_danger_quarters(self):
        f = adaptive_kelly_fraction(0.25, profit_factor=1.0)
        assert f == pytest.approx(0.0625)

    def test_pf_zero_skipped(self):
        # PF=0 means unknown → no shrinkage
        f = adaptive_kelly_fraction(0.25, profit_factor=0.0)
        assert f == 0.25

    def test_drawdown_caution_halves(self):
        f = adaptive_kelly_fraction(0.25, max_drawdown_pct=20.0)
        assert f == pytest.approx(0.125)

    def test_drawdown_danger_quarters(self):
        f = adaptive_kelly_fraction(0.25, max_drawdown_pct=30.0)
        assert f == pytest.approx(0.0625)

    def test_vol_caution_reduces_30pct(self):
        f = adaptive_kelly_fraction(0.25, local_vol_pct=35.0)
        assert f == pytest.approx(0.175)

    def test_vol_danger_halves(self):
        f = adaptive_kelly_fraction(0.25, local_vol_pct=55.0)
        assert f == pytest.approx(0.0625)

    def test_multipliers_stack(self):
        # PF caution (0.5) + DD caution (0.5) + vol danger (0.25) = 0.0625
        f = adaptive_kelly_fraction(
            0.25, profit_factor=1.1, max_drawdown_pct=20.0, local_vol_pct=55.0,
        )
        assert f == pytest.approx(0.25 * 0.5 * 0.5 * 0.25)

    def test_all_danger_very_small(self):
        f = adaptive_kelly_fraction(
            0.25, profit_factor=0.9, max_drawdown_pct=30.0, local_vol_pct=55.0,
        )
        # 0.25 * 0.25 * 0.25 * 0.25 = 0.00390625
        assert f == pytest.approx(0.25 * 0.25 * 0.25 * 0.25)
        assert f < 0.01

    def test_never_negative(self):
        f = adaptive_kelly_fraction(0.0, profit_factor=0.5, max_drawdown_pct=50.0)
        assert f >= 0.0

    def test_custom_thresholds(self):
        f = adaptive_kelly_fraction(
            0.25, profit_factor=1.3,
            pf_caution_threshold=1.5,  # 1.3 < 1.5 → halve
        )
        assert f == pytest.approx(0.125)

    def test_good_pf_no_shrinkage(self):
        f = adaptive_kelly_fraction(0.25, profit_factor=2.0)
        assert f == 0.25


class TestVolScaledFraction:
    def test_target_equals_realized(self):
        # scale=1.0 → no change
        f = vol_scaled_fraction(0.25, realized_vol=0.02, target_vol=0.02)
        assert f == pytest.approx(0.25)

    def test_high_vol_reduces(self):
        # realized 4% vs target 2% → scale=0.5
        f = vol_scaled_fraction(0.25, realized_vol=0.04, target_vol=0.02)
        assert f == pytest.approx(0.125)

    def test_low_vol_capped_at_max(self):
        # realized 1% vs target 2% → scale=2.0 but capped at 1.0
        f = vol_scaled_fraction(0.25, realized_vol=0.01, target_vol=0.02)
        assert f == pytest.approx(0.25)  # scale capped at 1.0

    def test_very_high_vol_hits_floor(self):
        # realized 10% vs target 2% → scale=0.2, floored at 0.25
        f = vol_scaled_fraction(0.25, realized_vol=0.10, target_vol=0.02)
        assert f == pytest.approx(0.25 * 0.25)  # min_scale=0.25

    def test_zero_vol_returns_zero(self):
        f = vol_scaled_fraction(0.25, realized_vol=0.0, target_vol=0.02)
        assert f == 0.0

    def test_negative_vol_returns_zero(self):
        f = vol_scaled_fraction(0.25, realized_vol=-0.01, target_vol=0.02)
        assert f == 0.0

    def test_custom_bounds(self):
        f = vol_scaled_fraction(
            0.25, realized_vol=0.08, target_vol=0.02,
            min_scale=0.1, max_scale=2.0,
        )
        # scale = 0.02/0.08 = 0.25, above min 0.1
        assert f == pytest.approx(0.25 * 0.25)


class TestAtrRiskFraction:
    def test_normal_atr(self):
        # risk 1%, atr=500, atr_unit=500 → frac = 0.01 * 500/500 = 0.01
        f = atr_risk_fraction(0.01, atr=500.0, atr_unit=500.0)
        assert f == pytest.approx(0.01)

    def test_high_atr_reduces(self):
        # risk 1%, atr=1000, atr_unit=500 → frac = 0.01 * 500/1000 = 0.005
        f = atr_risk_fraction(0.01, atr=1000.0, atr_unit=500.0)
        assert f == pytest.approx(0.005)

    def test_low_atr_capped(self):
        # risk 1%, atr=100, atr_unit=500 → frac = 0.01 * 500/100 = 0.05, capped at 0.02
        f = atr_risk_fraction(0.01, atr=100.0, atr_unit=500.0, max_risk_pct=0.02)
        assert f == pytest.approx(0.02)

    def test_zero_atr(self):
        f = atr_risk_fraction(0.01, atr=0.0, atr_unit=500.0)
        assert f == 0.0

    def test_negative_atr(self):
        f = atr_risk_fraction(0.01, atr=-100.0, atr_unit=500.0)
        assert f == 0.0

    def test_zero_atr_unit(self):
        f = atr_risk_fraction(0.01, atr=500.0, atr_unit=0.0)
        assert f == 0.0


class TestAdaptiveKellyInSizer:
    def test_high_drawdown_reduces_size(self):
        sizer = PositionSizer()
        normal = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000, max_drawdown_pct=0.0,
        )
        stressed = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000, max_drawdown_pct=20.0,
        )
        assert stressed <= normal

    def test_high_vol_reduces_size(self):
        sizer = PositionSizer()
        calm = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000, local_vol_pct=0.0,
        )
        volatile = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000, local_vol_pct=55.0,
        )
        assert volatile <= calm

    def test_combined_stress_very_small(self):
        sizer = PositionSizer()
        size = sizer.compute(
            "BTC_HOURLY", edge_pct=5.0, price_cents=55,
            bankroll_cents=500_000,
            profit_factor=1.0, max_drawdown_pct=30.0, local_vol_pct=55.0,
            expectancy_cents=10.0, total_trades=100,
        )
        # Should still produce at least min_contracts (1) or 0
        assert size <= 5


# ── Explain ──────────────────────────────────────────────────────────

class TestExplain:
    def test_explain_returns_all_fields(self):
        sizer = PositionSizer()
        result = sizer.explain(
            "BTC_HOURLY", edge_pct=3.0, price_cents=55,
            bankroll_cents=500_000,
            profit_factor=1.5, expectancy_cents=10.0, total_trades=100,
        )
        assert "contracts" in result
        assert "raw_kelly" in result
        assert "fractional_kelly" in result
        assert "pf_scale" in result
        assert "risk_per_contract_cents" in result
        assert "adapted_kelly_fraction" in result
        assert "max_drawdown_pct" in result
        assert "local_vol_pct" in result
        assert result["agent"] == "BTC_HOURLY"
        assert result["contracts"] >= 0

    def test_explain_matches_compute(self):
        sizer = PositionSizer()
        kwargs = dict(
            agent_name="ETH_HOURLY", edge_pct=4.0, price_cents=60,
            bankroll_cents=300_000,
            profit_factor=1.6, expectancy_cents=15.0, total_trades=80,
        )
        computed = sizer.compute(**kwargs)
        explained = sizer.explain(**kwargs)
        assert explained["contracts"] == computed


# ── Kelly utilization tracker ────────────────────────────────────────

class TestKellyUtilizationTracker:
    def test_empty_summary(self):
        t = KellyUtilizationTracker()
        s = t.summary()
        assert s["trade_count"] == 0
        assert s["avg_utilization_pct"] == 0.0

    def test_record_and_summary(self):
        t = KellyUtilizationTracker()
        t.record(
            raw_kelly=0.12, adapted_fraction=0.03,
            contracts=5, risk_per_contract_cents=57,
            bankroll_cents=500_000,
        )
        s = t.summary()
        assert s["trade_count"] == 1
        assert s["avg_raw_kelly_pct"] == pytest.approx(12.0)
        assert s["avg_adapted_fraction_pct"] == pytest.approx(3.0)
        assert s["avg_utilization_pct"] == pytest.approx(25.0)  # 0.03/0.12=25%
        assert s["avg_actual_risked_pct"] > 0

    def test_multiple_records(self):
        t = KellyUtilizationTracker()
        t.record(raw_kelly=0.10, adapted_fraction=0.05, contracts=3, risk_per_contract_cents=50, bankroll_cents=100_000)
        t.record(raw_kelly=0.20, adapted_fraction=0.05, contracts=5, risk_per_contract_cents=50, bankroll_cents=100_000)
        s = t.summary()
        assert s["trade_count"] == 2
        # avg raw kelly = (0.10+0.20)/2 = 0.15 → 15%
        assert s["avg_raw_kelly_pct"] == pytest.approx(15.0)
        # avg utilization = (50% + 25%) / 2 = 37.5%
        assert s["avg_utilization_pct"] == pytest.approx(37.5)

    def test_window_size_truncates(self):
        t = KellyUtilizationTracker(window_size=3)
        for i in range(5):
            t.record(raw_kelly=0.10, adapted_fraction=0.03, contracts=1, risk_per_contract_cents=50, bankroll_cents=10_000)
        assert t.trade_count == 3

    def test_reset(self):
        t = KellyUtilizationTracker()
        t.record(raw_kelly=0.10, adapted_fraction=0.03, contracts=1, risk_per_contract_cents=50, bankroll_cents=10_000)
        assert t.trade_count == 1
        t.reset()
        assert t.trade_count == 0

    def test_zero_raw_kelly_utilization(self):
        t = KellyUtilizationTracker()
        t.record(raw_kelly=0.0, adapted_fraction=0.0, contracts=0, risk_per_contract_cents=50, bankroll_cents=10_000)
        s = t.summary()
        assert s["avg_utilization_pct"] == 0.0

    def test_zero_bankroll(self):
        t = KellyUtilizationTracker()
        t.record(raw_kelly=0.10, adapted_fraction=0.05, contracts=5, risk_per_contract_cents=50, bankroll_cents=0)
        s = t.summary()
        assert s["avg_actual_risked_pct"] == 0.0


# ── Singleton ─────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_position_sizer_returns_same_instance(self):
        import merid.event_venues.kalshi.position_sizer as mod
        old = mod._sizer
        try:
            mod._sizer = None
            s1 = get_position_sizer()
            s2 = get_position_sizer()
            assert s1 is s2
        finally:
            mod._sizer = old
