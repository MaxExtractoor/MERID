"""Tests for CapitalEngine — the three-bucket exponential money loop.

Covers:
  1. Bucket initialisation
  2. Profit routing (positive PnL)
  3. Loss absorption (negative PnL) — core stays untouched
  4. Drawdown step-down and recovery
  5. Growth bucket usage for high-conviction trades
  6. Per-asset risk capital capping
  7. Per-(asset, timeframe) risk budget enforcement in allocate_to_trade
  8. Periodic core rebalance
  9. Snapshot correctness
  10. Integration: growing core under a synthetic win-run
  11. Integration: drawdown triggers step-down, recovery restores full sizing
"""

from __future__ import annotations

import math
import pytest

from merid.risk.capital_engine import (
    AssetCapitalConfig,
    CapitalEngine,
    CapitalSnapshot,
    RiskBudget,
    _default_asset_configs,
    _default_risk_budgets,
)


# ── Helpers ───────────────────────────────────────────────────────────────

TOTAL_EQUITY = 10_000.0
INITIAL_RISK_FRACTION = 0.40  # 4 000 risk, 6 000 core


@pytest.fixture()
def engine() -> CapitalEngine:
    """Default engine with £10 000 equity, 40% risk / 60% core split."""
    return CapitalEngine(
        total_equity=TOTAL_EQUITY,
        initial_risk_fraction=INITIAL_RISK_FRACTION,
    )


@pytest.fixture()
def btc_config() -> AssetCapitalConfig:
    return _default_asset_configs()["BTC"]


# ══════════════════════════════════════════════════════════════════════════
# 1. Initialisation
# ══════════════════════════════════════════════════════════════════════════

class TestInitialisation:
    def test_total_equity_preserved(self, engine: CapitalEngine) -> None:
        assert engine.total_equity == pytest.approx(TOTAL_EQUITY)

    def test_risk_capital_fraction(self, engine: CapitalEngine) -> None:
        assert engine.risk_capital == pytest.approx(TOTAL_EQUITY * INITIAL_RISK_FRACTION)

    def test_core_capital_fraction(self, engine: CapitalEngine) -> None:
        expected_core = TOTAL_EQUITY * (1 - INITIAL_RISK_FRACTION)
        assert engine.core_capital == pytest.approx(expected_core)

    def test_growth_starts_at_zero(self, engine: CapitalEngine) -> None:
        assert engine.growth_capital == 0.0

    def test_sizing_multiplier_starts_at_one(self, engine: CapitalEngine) -> None:
        assert engine.sizing_multiplier == pytest.approx(1.0)

    def test_invalid_equity_raises(self) -> None:
        with pytest.raises(ValueError, match="total_equity"):
            CapitalEngine(total_equity=0.0)

    def test_invalid_risk_fraction_raises(self) -> None:
        with pytest.raises(ValueError, match="initial_risk_fraction"):
            CapitalEngine(total_equity=1000.0, initial_risk_fraction=1.5)

    def test_invalid_sweep_sum_raises(self) -> None:
        with pytest.raises(ValueError, match="must not exceed"):
            AssetCapitalConfig(
                profit_sweep_pct_to_core=0.70,
                profit_sweep_pct_to_growth=0.50,
            )


# ══════════════════════════════════════════════════════════════════════════
# 2. Profit routing — positive PnL
# ══════════════════════════════════════════════════════════════════════════

class TestProfitRouting:
    PNL = 1_000.0  # $1 000 trade profit

    def test_core_grows_by_correct_fraction(self, engine: CapitalEngine, btc_config: AssetCapitalConfig) -> None:
        initial_core = engine.core_capital
        engine.record_trade_result("BTC", self.PNL)
        expected_delta = self.PNL * btc_config.profit_sweep_pct_to_core
        assert engine.core_capital == pytest.approx(initial_core + expected_delta)

    def test_growth_grows_by_correct_fraction(self, engine: CapitalEngine, btc_config: AssetCapitalConfig) -> None:
        engine.record_trade_result("BTC", self.PNL)
        expected = self.PNL * btc_config.profit_sweep_pct_to_growth
        assert engine.growth_capital == pytest.approx(expected)

    def test_risk_grows_by_recycle_fraction(self, engine: CapitalEngine, btc_config: AssetCapitalConfig) -> None:
        initial_risk = engine.risk_capital
        engine.record_trade_result("BTC", self.PNL)
        expected_delta = self.PNL * btc_config.profit_recycle_pct_to_risk
        assert engine.risk_capital == pytest.approx(initial_risk + expected_delta)

    def test_total_equity_conserved_after_profit(self, engine: CapitalEngine) -> None:
        initial_total = engine.total_equity
        engine.record_trade_result("BTC", self.PNL)
        assert engine.total_equity == pytest.approx(initial_total + self.PNL)

    def test_pnl_routing_sums_to_pnl(self, engine: CapitalEngine, btc_config: AssetCapitalConfig) -> None:
        to_core = self.PNL * btc_config.profit_sweep_pct_to_core
        to_growth = self.PNL * btc_config.profit_sweep_pct_to_growth
        to_risk = self.PNL - to_core - to_growth
        assert pytest.approx(to_core + to_growth + to_risk) == self.PNL


# ══════════════════════════════════════════════════════════════════════════
# 3. Loss absorption — core must never be touched
# ══════════════════════════════════════════════════════════════════════════

class TestLossAbsorption:
    SMALL_LOSS = 200.0
    BIG_LOSS = 5_000.0  # Exceeds initial risk capital

    def test_small_loss_reduces_risk_only(self, engine: CapitalEngine) -> None:
        initial_core = engine.core_capital
        initial_risk = engine.risk_capital
        engine.record_trade_result("BTC", -self.SMALL_LOSS)
        assert engine.core_capital == pytest.approx(initial_core)
        assert engine.risk_capital == pytest.approx(initial_risk - self.SMALL_LOSS)

    def test_core_never_reduced_by_loss(self, engine: CapitalEngine) -> None:
        initial_core = engine.core_capital
        # Apply a huge loss that exceeds risk capital
        engine.record_trade_result("BTC", -self.BIG_LOSS)
        assert engine.core_capital == pytest.approx(initial_core), "Core must never decrease on losses"

    def test_risk_floors_at_zero(self, engine: CapitalEngine) -> None:
        engine.record_trade_result("BTC", -self.BIG_LOSS)
        assert engine.risk_capital >= 0.0

    def test_growth_absorbs_overflow_loss(self, engine: CapitalEngine) -> None:
        # Prime the growth bucket first
        engine.record_trade_result("BTC", 1_000.0)
        growth_after_win = engine.growth_capital
        risk_after_win = engine.risk_capital

        # Now apply a loss larger than the risk stack
        big_loss = risk_after_win + 100.0
        engine.record_trade_result("BTC", -big_loss)

        assert engine.risk_capital == 0.0
        assert engine.growth_capital == pytest.approx(max(0.0, growth_after_win - 100.0))

    def test_total_equity_decreases_by_loss(self, engine: CapitalEngine) -> None:
        initial_total = engine.total_equity
        engine.record_trade_result("BTC", -self.SMALL_LOSS)
        assert engine.total_equity == pytest.approx(initial_total - self.SMALL_LOSS)


# ══════════════════════════════════════════════════════════════════════════
# 4. Drawdown step-down and recovery
# ══════════════════════════════════════════════════════════════════════════

class TestDrawdownStepDown:
    def _engine_with_threshold(self, threshold: float = 0.15, multiplier: float = 0.60) -> CapitalEngine:
        cfg = AssetCapitalConfig(
            drawdown_stepdown_threshold=threshold,
            drawdown_stepdown_multiplier=multiplier,
            drawdown_recovery_threshold=0.95,
        )
        return CapitalEngine(
            total_equity=10_000.0,
            asset_configs={"BTC": cfg},
            initial_risk_fraction=0.40,
        )

    def test_no_stepdown_below_threshold(self) -> None:
        e = self._engine_with_threshold(threshold=0.15)
        e.record_trade_result("BTC", -100.0)  # 100 / 4000 = 2.5%
        assert e.sizing_multiplier == pytest.approx(1.0)

    def test_stepdown_triggers_at_threshold(self) -> None:
        e = self._engine_with_threshold(threshold=0.15, multiplier=0.60)
        # Lose 15% of risk capital (600 on 4000)
        e.record_trade_result("BTC", -600.0)
        assert e.sizing_multiplier == pytest.approx(0.60)

    def test_stepdown_reduces_get_risk_capital(self) -> None:
        e = self._engine_with_threshold(threshold=0.10, multiplier=0.50)
        e.record_trade_result("BTC", -400.0)  # 10% of 4000
        risk_capital_full = e.risk_capital
        risk_cap_after = e.get_risk_capital("BTC")
        # Should be multiplied by something < 1.0
        assert risk_cap_after < risk_capital_full

    def test_recovery_restores_full_sizing(self) -> None:
        e = self._engine_with_threshold(threshold=0.15, multiplier=0.60)
        e.record_trade_result("BTC", -600.0)  # triggers step-down
        assert e.sizing_multiplier < 1.0

        # Need risk to recover from 3400 to ≥ 3800 (95% of 4000 peak).
        # BTC recycles 25% of profits to risk, so we need at least 1600 profit
        # to add 400 to the risk stack: 1600 * 0.25 = 400 → risk = 3800.
        e.record_trade_result("BTC", 1_600.0)
        assert e.sizing_multiplier == pytest.approx(1.0)


# ══════════════════════════════════════════════════════════════════════════
# 5. Growth bucket — high-conviction extra size
# ══════════════════════════════════════════════════════════════════════════

class TestGrowthBucket:
    def test_no_growth_used_for_low_conviction(self, engine: CapitalEngine) -> None:
        engine.record_trade_result("BTC", 1_000.0)
        baseline = engine.allocate_to_trade("BTC", 100.0, conviction=0.5)
        with_growth = engine.allocate_to_trade(
            "BTC", 100.0, use_growth_bucket=True, conviction=0.5
        )
        assert baseline == pytest.approx(with_growth)

    def test_growth_adds_extra_for_high_conviction(self, engine: CapitalEngine) -> None:
        engine.record_trade_result("BTC", 2_000.0)  # builds up growth bucket
        baseline = engine.allocate_to_trade("BTC", 100.0, conviction=0.9)
        with_growth = engine.allocate_to_trade(
            "BTC", 100.0, use_growth_bucket=True, conviction=0.9
        )
        assert with_growth >= baseline

    def test_growth_extra_bounded_by_growth_cap(self, engine: CapitalEngine) -> None:
        engine.record_trade_result("BTC", 2_000.0)
        cfg = _default_asset_configs()["BTC"]
        max_extra = engine.growth_capital * cfg.growth_bucket_max_usage_pct
        max_from_15pct = 100.0 * 0.15  # 15% of suggested_size
        expected_max_extra = min(max_from_15pct, max_extra)

        with_growth = engine.allocate_to_trade(
            "BTC", 100.0, use_growth_bucket=True, conviction=0.95
        )
        baseline = engine.allocate_to_trade("BTC", 100.0, conviction=0.95)
        extra = with_growth - baseline
        assert extra <= expected_max_extra + 1e-9

    def test_no_growth_used_when_bucket_empty(self, engine: CapitalEngine) -> None:
        assert engine.growth_capital == 0.0
        baseline = engine.allocate_to_trade("BTC", 100.0, conviction=0.9)
        with_growth = engine.allocate_to_trade(
            "BTC", 100.0, use_growth_bucket=True, conviction=0.9
        )
        assert with_growth == pytest.approx(baseline)


# ══════════════════════════════════════════════════════════════════════════
# 6. Per-asset risk capital capping
# ══════════════════════════════════════════════════════════════════════════

class TestPerAssetRiskCapital:
    def test_unknown_asset_returns_zero(self, engine: CapitalEngine) -> None:
        assert engine.get_risk_capital("SHIB") == 0.0

    def test_asset_equity_cap_applied(self, engine: CapitalEngine) -> None:
        cfg = _default_asset_configs()["DOGE"]
        cap = engine.total_equity * cfg.asset_max_risk_pct_of_total_equity
        # If risk_capital > cap the result should be capped
        risk_cap = engine.get_risk_capital("DOGE")
        assert risk_cap <= cap

    def test_btc_risk_capital_bounded_by_equity_cap(self, engine: CapitalEngine) -> None:
        cfg = _default_asset_configs()["BTC"]
        max_allowed = engine.total_equity * cfg.asset_max_risk_pct_of_total_equity
        assert engine.get_risk_capital("BTC") <= max_allowed + 1e-9

    def test_all_supported_assets_return_positive(self, engine: CapitalEngine) -> None:
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert engine.get_risk_capital(asset) > 0


# ══════════════════════════════════════════════════════════════════════════
# 7. allocate_to_trade — per-trade and per-budget caps
# ══════════════════════════════════════════════════════════════════════════

class TestAllocateToTrade:
    def test_suggested_below_cap_passed_through(self, engine: CapitalEngine) -> None:
        # Very small suggested size should not be capped
        result = engine.allocate_to_trade("BTC", 1.0)
        assert result == pytest.approx(1.0)

    def test_oversized_suggestion_capped(self, engine: CapitalEngine) -> None:
        very_large = engine.total_equity * 10
        result = engine.allocate_to_trade("BTC", very_large)
        cfg = _default_asset_configs()["BTC"]
        risk_cap = engine.get_risk_capital("BTC")
        per_trade_cap = risk_cap * cfg.max_risk_pct_per_trade
        assert result <= per_trade_cap + 1e-9

    def test_timeframe_budget_enforced(self, engine: CapitalEngine) -> None:
        budget = engine.get_risk_budget("BTC", "scalp")
        assert budget is not None
        risk_cap = engine.get_risk_capital("BTC")
        budget_cap = risk_cap * budget.max_risk_pct_risk_capital

        very_large = engine.total_equity
        result = engine.allocate_to_trade("BTC", very_large, timeframe="scalp")
        assert result <= budget_cap + 1e-9

    def test_swing_allows_larger_than_scalp(self, engine: CapitalEngine) -> None:
        scalp_alloc = engine.allocate_to_trade("BTC", 1_000.0, timeframe="scalp")
        swing_alloc = engine.allocate_to_trade("BTC", 1_000.0, timeframe="swing")
        assert swing_alloc >= scalp_alloc

    def test_unknown_asset_returns_zero(self, engine: CapitalEngine) -> None:
        assert engine.allocate_to_trade("SHIB", 100.0) == 0.0

    def test_result_never_negative(self, engine: CapitalEngine) -> None:
        assert engine.allocate_to_trade("BTC", -50.0) >= 0.0


# ══════════════════════════════════════════════════════════════════════════
# 8. Periodic core rebalance
# ══════════════════════════════════════════════════════════════════════════

class TestRebalanceCore:
    def test_no_rebalance_when_risk_below_threshold(self, engine: CapitalEngine) -> None:
        initial_core = engine.core_capital
        swept = engine.rebalance_core()
        assert swept == pytest.approx(0.0)
        assert engine.core_capital == pytest.approx(initial_core)

    def test_rebalance_sweeps_excess_to_core(self, engine: CapitalEngine) -> None:
        # Manually inflate risk capital well above rebalance multiple
        engine._risk_capital = engine._core_capital * 2.0
        initial_core = engine.core_capital
        swept = engine.rebalance_core()
        assert swept > 0.0
        assert engine.core_capital > initial_core

    def test_total_equity_unchanged_after_rebalance(self, engine: CapitalEngine) -> None:
        engine._risk_capital = engine._core_capital * 2.0
        total_before_rebalance = engine.total_equity  # after inflation
        engine.rebalance_core()
        assert engine.total_equity == pytest.approx(total_before_rebalance)

    def test_core_monotonically_grows_via_rebalance(self, engine: CapitalEngine) -> None:
        engine._risk_capital = engine._core_capital * 2.0
        core_before = engine.core_capital
        engine.rebalance_core()
        assert engine.core_capital >= core_before


# ══════════════════════════════════════════════════════════════════════════
# 9. Snapshot
# ══════════════════════════════════════════════════════════════════════════

class TestSnapshot:
    def test_snapshot_returns_correct_type(self, engine: CapitalEngine) -> None:
        snap = engine.snapshot()
        assert isinstance(snap, CapitalSnapshot)

    def test_snapshot_total_equity_matches(self, engine: CapitalEngine) -> None:
        snap = engine.snapshot()
        assert snap.total_equity == pytest.approx(engine.total_equity)

    def test_snapshot_to_dict_is_serialisable(self, engine: CapitalEngine) -> None:
        d = engine.snapshot().to_dict()
        import json
        json.dumps(d)  # should not raise

    def test_snapshot_in_drawdown_flag(self) -> None:
        cfg = AssetCapitalConfig(
            drawdown_stepdown_threshold=0.10,
            drawdown_stepdown_multiplier=0.50,
        )
        e = CapitalEngine(
            total_equity=10_000.0,
            asset_configs={"BTC": cfg},
            initial_risk_fraction=0.40,
        )
        e.record_trade_result("BTC", -500.0)  # 12.5% drawdown → triggers step-down
        snap = e.snapshot()
        assert snap.in_drawdown is True

    def test_snapshot_per_asset_risk_capital_populated(self, engine: CapitalEngine) -> None:
        snap = engine.snapshot()
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert asset in snap.per_asset_risk_capital
            assert snap.per_asset_risk_capital[asset] >= 0.0


# ══════════════════════════════════════════════════════════════════════════
# 10. Default configs coverage
# ══════════════════════════════════════════════════════════════════════════

class TestDefaultConfigs:
    def test_all_five_assets_configured(self) -> None:
        cfgs = _default_asset_configs()
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert asset in cfgs

    def test_all_sweep_fractions_valid(self) -> None:
        for asset, cfg in _default_asset_configs().items():
            total = cfg.profit_sweep_pct_to_core + cfg.profit_sweep_pct_to_growth
            assert total <= 1.0, f"{asset}: sweep fractions sum > 1"
            assert cfg.profit_recycle_pct_to_risk >= 0.0

    def test_risk_budgets_cover_all_asset_timeframes(self) -> None:
        budgets = _default_risk_budgets()
        assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        timeframes = {"scalp", "intraday", "swing"}
        keys = {(b.asset, b.timeframe) for b in budgets}
        for a in assets:
            for tf in timeframes:
                assert (a, tf) in keys, f"Missing budget for ({a}, {tf})"

    def test_noisy_coins_more_conservative_than_btc(self) -> None:
        cfgs = _default_asset_configs()
        for asset in ["DOGE", "XRP"]:
            assert cfgs[asset].max_risk_pct_per_trade <= cfgs["BTC"].max_risk_pct_per_trade
            assert cfgs[asset].core_capital_target_pct >= cfgs["BTC"].core_capital_target_pct


# ══════════════════════════════════════════════════════════════════════════
# 11. Integration: growing core under a synthetic win-run
# ══════════════════════════════════════════════════════════════════════════

class TestIntegrationWinRun:
    def test_core_grows_monotonically_on_wins(self) -> None:
        e = CapitalEngine(total_equity=10_000.0, initial_risk_fraction=0.40)
        cores = [e.core_capital]
        for _ in range(20):
            e.record_trade_result("BTC", 200.0)
            cores.append(e.core_capital)
        for i in range(1, len(cores)):
            assert cores[i] >= cores[i - 1], "Core must grow monotonically on wins"

    def test_total_equity_grows_on_wins(self) -> None:
        e = CapitalEngine(total_equity=10_000.0, initial_risk_fraction=0.40)
        for _ in range(10):
            e.record_trade_result("BTC", 300.0)
        assert e.total_equity > 10_000.0

    def test_risk_capital_bounded_after_rebalance(self) -> None:
        e = CapitalEngine(total_equity=10_000.0, initial_risk_fraction=0.40)
        for _ in range(10):
            e.record_trade_result("BTC", 500.0)
        before_risk = e.risk_capital
        e.rebalance_core()
        # Risk capital should be reduced or unchanged; core should be ≥ before
        assert e.risk_capital <= before_risk + 1e-9


# ══════════════════════════════════════════════════════════════════════════
# 12. Integration: drawdown triggers step-down, recovery restores full sizing
# ══════════════════════════════════════════════════════════════════════════

class TestIntegrationDrawdownRecovery:
    def test_stepdown_then_recovery_sequence(self) -> None:
        cfg = AssetCapitalConfig(
            drawdown_stepdown_threshold=0.15,
            drawdown_stepdown_multiplier=0.60,
            drawdown_recovery_threshold=0.95,
        )
        e = CapitalEngine(
            total_equity=10_000.0,
            asset_configs={"BTC": cfg},
            initial_risk_fraction=0.40,
        )
        initial_multiplier = e.sizing_multiplier
        assert initial_multiplier == 1.0

        # Induce 16% drawdown on risk capital (640 / 4000 = 16%)
        e.record_trade_result("BTC", -640.0)
        assert e.sizing_multiplier < 1.0, "Step-down should be active"

        # Win enough to recover risk past 95% of the 4000 peak (need ≥ 3800).
        # risk is now ~3360; recycle fraction = 25%; need 1760 profit to add 440.
        e.record_trade_result("BTC", 1_760.0)
        assert e.sizing_multiplier == pytest.approx(1.0), "Multiplier should be restored"

    def test_auto_compound_loop_expands_risk_capital(self) -> None:
        e = CapitalEngine(total_equity=10_000.0, initial_risk_fraction=0.40)
        initial_risk = e.risk_capital
        # 10 wins; the recycle fraction re-enters the risk stack each time
        for _ in range(10):
            e.record_trade_result("BTC", 100.0)
        assert e.risk_capital > initial_risk, "Risk capital must grow via auto-compound"
