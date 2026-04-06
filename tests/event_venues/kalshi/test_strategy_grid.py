"""Tests for strategy_grid.py — named strategy set for Kalshi crypto markets.

Covers:
  1. Grid registration — all 30 (5 assets × 6 timeframes) pairs registered.
  2. Strategy assignment — correct strategies per timeframe.
  3. Edge computation — each strategy returns non-zero edge with real inputs.
  4. Asset-tier caps — satellite assets have lower Kelly multipliers.
  5. Liquidity gate — low-volume candidates are skipped.
  6. Regime gate — annual/regime_bet returns None when regime is flat.
  7. Integration — first_estimate helper works end-to-end.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from merid.event_venues.kalshi.strategy_grid import (
    DayCloseDirectionStrategy,
    GridEntry,
    MeanRevertSpikeStrategy,
    RangeCompressionStrategy,
    RegimeBetStrategy,
    SpotMomentumStrategy,
    StrategyGrid,
    TrendFollowCarryStrategy,
    VolSurfaceMispricingStrategy,
    get_strategy_grid,
    _CORE_ASSETS,
    _SATELLITE_ASSETS,
    _KELLY_MULTIPLIER,
    _MIN_VOLUME,
    _MIN_OI,
)
from config.crypto_universe import (
    CRYPTO_ASSETS_ORDERED,
    CRYPTO_TIMEFRAMES_ORDERED,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

def _ctx(asset: str, timeframe: str, **kwargs: Any) -> Dict[str, Any]:
    """Build a minimal context dict for strategy.estimate() calls."""
    base = {
        "asset": asset,
        "timeframe": timeframe,
        "volume": 500.0,
        "open_interest": 50.0,
        # Spot momentum signals
        "spot_return_pct": 2.5,
        "orderbook_imbalance": 0.3,
        # Mean revert signal
        "deviation_from_fair": 0.08,
        # Day-close signals
        "intraday_drift_pct": 1.5,
        "cross_asset_confirm": 0.8,
        # Range signals
        "realized_range_pct": 3.0,
        "implied_range_pct": 1.5,
        # Trend / vol signals
        "multi_tf_alignment": 0.75,
        "kalshi_vs_terminal_pct": 0.05,
        "tail_skew": 0.3,
        "realized_vol_rank": 0.8,
        # Regime signals
        "regime_score": 0.70,
        "regime_confidence": 0.75,
    }
    base.update(kwargs)
    return base


@pytest.fixture()
def grid() -> StrategyGrid:
    return StrategyGrid()


# ═══════════════════════════════════════════════════════════════════════════
# 1. Grid registration
# ═══════════════════════════════════════════════════════════════════════════

class TestGridRegistration:
    """All 30 (asset, timeframe) pairs must be registered in the grid."""

    def test_grid_has_30_entries(self, grid: StrategyGrid) -> None:
        assert len(grid.all_entries()) == 30

    def test_all_assets_present(self, grid: StrategyGrid) -> None:
        for asset in CRYPTO_ASSETS_ORDERED:
            for tf in CRYPTO_TIMEFRAMES_ORDERED:
                entry = grid.get(asset, tf)
                assert entry is not None, f"Missing entry for ({asset!r}, {tf!r})"

    def test_annual_entries_present(self, grid: StrategyGrid) -> None:
        """Every asset has an 'annual' entry registered."""
        for asset in CRYPTO_ASSETS_ORDERED:
            entry = grid.get(asset, "annual")
            assert entry is not None, f"Missing annual entry for {asset!r}"

    def test_unknown_pair_returns_none(self, grid: StrategyGrid) -> None:
        assert grid.get("BTC", "unknown_tf") is None

    def test_strategies_list_empty_for_unknown(self, grid: StrategyGrid) -> None:
        assert grid.strategies("ETH", "not_a_timeframe") == []


# ═══════════════════════════════════════════════════════════════════════════
# 2. Strategy assignment by timeframe
# ═══════════════════════════════════════════════════════════════════════════

class TestStrategyAssignment:
    """Each timeframe must use the correct named strategies."""

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS_ORDERED)
    def test_intraday_15m_strategies(self, grid: StrategyGrid, asset: str) -> None:
        names = [s.name for s in grid.strategies(asset, "15m")]
        assert "spot_momentum" in names
        assert "mean_revert_spike" in names

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS_ORDERED)
    def test_intraday_1h_strategies(self, grid: StrategyGrid, asset: str) -> None:
        names = [s.name for s in grid.strategies(asset, "1h")]
        assert "spot_momentum" in names
        assert "mean_revert_spike" in names

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS_ORDERED)
    def test_daily_strategies(self, grid: StrategyGrid, asset: str) -> None:
        names = [s.name for s in grid.strategies(asset, "daily")]
        assert "day_close_direction" in names
        assert "range_compression" in names

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS_ORDERED)
    def test_weekly_strategies(self, grid: StrategyGrid, asset: str) -> None:
        names = [s.name for s in grid.strategies(asset, "weekly")]
        assert "trend_follow_carry" in names
        assert "vol_surface_misprice" in names

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS_ORDERED)
    def test_monthly_strategies(self, grid: StrategyGrid, asset: str) -> None:
        names = [s.name for s in grid.strategies(asset, "monthly")]
        assert "trend_follow_carry" in names
        assert "vol_surface_misprice" in names

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS_ORDERED)
    def test_annual_strategy_is_regime_bet(self, grid: StrategyGrid, asset: str) -> None:
        names = [s.name for s in grid.strategies(asset, "annual")]
        assert names == ["regime_bet"], (
            f"{asset}/annual should only have regime_bet, got {names}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. Edge computation — non-zero with real inputs
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeComputation:
    """Each strategy must return a non-None estimate with sufficient real signals."""

    def _estimate(self, strategy, asset: str, timeframe: str, market_prob: float = 0.50):
        ctx = _ctx(asset, timeframe)
        return strategy.estimate("test_agent", f"K{asset}-{timeframe}", market_prob, context=ctx)

    def test_spot_momentum_produces_estimate_for_btc(self) -> None:
        s = SpotMomentumStrategy()
        est = self._estimate(s, "BTC", "15m", market_prob=0.45)
        assert est is not None, "SpotMomentum should return estimate with real inputs"
        assert abs(est.edge) > 0.0

    def test_spot_momentum_produces_estimate_for_eth(self) -> None:
        s = SpotMomentumStrategy()
        est = self._estimate(s, "ETH", "1h", market_prob=0.45)
        assert est is not None

    def test_mean_revert_produces_estimate(self) -> None:
        s = MeanRevertSpikeStrategy()
        est = self._estimate(s, "BTC", "15m", market_prob=0.55)
        assert est is not None

    def test_day_close_produces_estimate(self) -> None:
        s = DayCloseDirectionStrategy()
        est = self._estimate(s, "BTC", "daily", market_prob=0.45)
        assert est is not None

    def test_range_compression_produces_estimate(self) -> None:
        s = RangeCompressionStrategy()
        est = self._estimate(s, "ETH", "daily", market_prob=0.50)
        assert est is not None

    def test_trend_carry_produces_estimate(self) -> None:
        s = TrendFollowCarryStrategy()
        est = self._estimate(s, "BTC", "weekly", market_prob=0.45)
        assert est is not None

    def test_vol_surface_produces_estimate(self) -> None:
        s = VolSurfaceMispricingStrategy()
        # BTC has kelly_scale=1.0 — ensures edge clears min_edge threshold
        est = self._estimate(s, "BTC", "monthly", market_prob=0.40)
        assert est is not None

    def test_regime_bet_produces_estimate_in_strong_trend(self) -> None:
        s = RegimeBetStrategy()
        est = self._estimate(s, "BTC", "annual", market_prob=0.35)
        assert est is not None, "RegimeBet should emit when regime score and confidence are high"

    def test_regime_bet_returns_none_in_weak_trend(self) -> None:
        """RegimeBet returns None when regime_score is near 0 (flat market)."""
        s = RegimeBetStrategy()
        ctx = _ctx("BTC", "annual", regime_score=0.1, regime_confidence=0.8)
        est = s.estimate("agent", "KXBTC-2026", 0.40, context=ctx)
        assert est is None, "RegimeBet should not emit when |regime_score| < threshold"

    def test_regime_bet_returns_none_when_low_confidence(self) -> None:
        """RegimeBet returns None when regime_confidence is too low even if score is high."""
        s = RegimeBetStrategy()
        ctx = _ctx("BTC", "annual", regime_score=0.80, regime_confidence=0.50)
        est = s.estimate("agent", "KXBTC-2026", 0.40, context=ctx)
        assert est is None

    def test_trend_carry_returns_none_when_alignment_weak(self) -> None:
        """TrendFollowCarry returns None when |multi_tf_alignment| < threshold."""
        s = TrendFollowCarryStrategy()
        ctx = _ctx("BTC", "weekly", multi_tf_alignment=0.3)
        est = s.estimate("agent", "KXBTC-W", 0.45, context=ctx)
        assert est is None


# ═══════════════════════════════════════════════════════════════════════════
# 4. Asset-tier: satellite assets have lower Kelly multipliers
# ═══════════════════════════════════════════════════════════════════════════

class TestAssetTierCaps:
    """Satellite assets (SOL/XRP/DOGE) have lower Kelly multipliers than BTC/ETH."""

    def test_core_assets_have_full_kelly(self) -> None:
        for asset in _CORE_ASSETS:
            assert _KELLY_MULTIPLIER[asset] == 1.0, f"{asset} should have Kelly multiplier 1.0"

    def test_satellite_assets_have_reduced_kelly(self) -> None:
        for asset in _SATELLITE_ASSETS:
            assert _KELLY_MULTIPLIER[asset] < 1.0, (
                f"{asset} should have Kelly multiplier < 1.0 (got {_KELLY_MULTIPLIER[asset]})"
            )

    def test_doge_has_lowest_kelly(self) -> None:
        """DOGE must have the lowest (most conservative) Kelly multiplier."""
        doge_k = _KELLY_MULTIPLIER["DOGE"]
        for other_asset in CRYPTO_ASSETS_ORDERED:
            if other_asset != "DOGE":
                assert doge_k <= _KELLY_MULTIPLIER[other_asset], (
                    f"DOGE Kelly ({doge_k}) should be ≤ {other_asset} Kelly ({_KELLY_MULTIPLIER[other_asset]})"
                )

    def test_satellite_confidence_lower_than_core(self) -> None:
        """For same signals, satellite asset estimates have lower confidence than core."""
        s = SpotMomentumStrategy()
        btc_ctx = _ctx("BTC", "15m")
        sol_ctx = _ctx("SOL", "15m")
        market_prob = 0.45

        btc_est = s.estimate("a", "KXBTC", market_prob, context=btc_ctx)
        sol_est = s.estimate("a", "KXSOL", market_prob, context=sol_ctx)

        assert btc_est is not None and sol_est is not None
        assert sol_est.confidence <= btc_est.confidence, (
            f"SOL confidence ({sol_est.confidence}) should be ≤ BTC confidence ({btc_est.confidence})"
        )

    def test_satellite_higher_min_volume(self) -> None:
        """Satellite assets require higher minimum volume."""
        for core in _CORE_ASSETS:
            for sat in _SATELLITE_ASSETS:
                assert _MIN_VOLUME[sat] >= _MIN_VOLUME[core], (
                    f"{sat} min_volume ({_MIN_VOLUME[sat]}) should be ≥ {core} ({_MIN_VOLUME[core]})"
                )


# ═══════════════════════════════════════════════════════════════════════════
# 5. Liquidity gate
# ═══════════════════════════════════════════════════════════════════════════

class TestLiquidityGate:
    """All strategies skip candidates that fail the liquidity gate."""

    def test_low_volume_skipped(self) -> None:
        s = SpotMomentumStrategy()
        ctx = _ctx("BTC", "15m", volume=1.0, open_interest=50.0)
        est = s.estimate("agent", "KXBTC", 0.45, context=ctx)
        assert est is None, "Low volume should skip even BTC"

    def test_zero_oi_skipped(self) -> None:
        s = DayCloseDirectionStrategy()
        ctx = _ctx("BTC", "daily", volume=500.0, open_interest=0.0)
        est = s.estimate("agent", "KXBTC", 0.45, context=ctx)
        assert est is None, "Zero OI should skip"

    def test_satellite_stricter_volume_floor(self) -> None:
        """SOL needs higher volume than BTC's floor to pass the gate."""
        s = SpotMomentumStrategy()
        # Use BTC's min_volume floor for SOL — should fail for SOL
        btc_floor = _MIN_VOLUME["BTC"]  # 50.0
        sol_floor = _MIN_VOLUME["SOL"]  # 75.0

        if sol_floor > btc_floor:
            ctx_borderline = _ctx("SOL", "15m", volume=btc_floor, open_interest=50.0)
            est = s.estimate("agent", "KXSOL", 0.45, context=ctx_borderline)
            assert est is None, (
                f"SOL at BTC's volume floor ({btc_floor}) should fail SOL's liquidity gate ({sol_floor})"
            )


# ═══════════════════════════════════════════════════════════════════════════
# 6. first_estimate integration helper
# ═══════════════════════════════════════════════════════════════════════════

class TestFirstEstimate:
    """first_estimate returns the first non-None estimate from the strategy list."""

    def test_first_estimate_btc_15m(self, grid: StrategyGrid) -> None:
        ctx = _ctx("BTC", "15m")
        est = grid.first_estimate("BTC", "15m", "agent", "KXBTC-15M", 0.45, context=ctx)
        assert est is not None
        assert est.edge != 0.0
        assert est.reasoning_tag in ("spot_momentum", "mean_revert_spike")

    def test_first_estimate_btc_annual_in_strong_regime(self, grid: StrategyGrid) -> None:
        ctx = _ctx("BTC", "annual", regime_score=0.75, regime_confidence=0.80)
        est = grid.first_estimate("BTC", "annual", "agent", "KXBTC-2026", 0.35, context=ctx)
        assert est is not None
        assert est.reasoning_tag == "regime_bet"

    def test_first_estimate_annual_flat_regime_returns_none(self, grid: StrategyGrid) -> None:
        ctx = _ctx("BTC", "annual", regime_score=0.20, regime_confidence=0.80)
        est = grid.first_estimate("BTC", "annual", "agent", "KXBTC-2026", 0.50, context=ctx)
        assert est is None

    def test_first_estimate_unknown_pair_returns_none(self, grid: StrategyGrid) -> None:
        est = grid.first_estimate("BTC", "unknown", "agent", "KXBTC-FOO", 0.50)
        assert est is None

    def test_first_estimate_skips_extremes(self, grid: StrategyGrid) -> None:
        """market_prob of 0.0 or 1.0 should_skip and return None."""
        ctx = _ctx("ETH", "daily")
        est_low = grid.first_estimate("ETH", "daily", "agent", "KXETH-D", 0.0, context=ctx)
        est_high = grid.first_estimate("ETH", "daily", "agent", "KXETH-D", 1.0, context=ctx)
        assert est_low is None
        assert est_high is None


# ═══════════════════════════════════════════════════════════════════════════
# 7. GridEntry metadata
# ═══════════════════════════════════════════════════════════════════════════

class TestGridEntryMetadata:
    """GridEntry carries correct metadata (is_core, kelly_multiplier, etc.)."""

    def test_btc_is_core(self, grid: StrategyGrid) -> None:
        entry = grid.get("BTC", "15m")
        assert entry is not None and entry.is_core is True

    def test_eth_is_core(self, grid: StrategyGrid) -> None:
        entry = grid.get("ETH", "1h")
        assert entry is not None and entry.is_core is True

    def test_sol_is_satellite(self, grid: StrategyGrid) -> None:
        entry = grid.get("SOL", "daily")
        assert entry is not None and entry.is_core is False

    def test_xrp_is_satellite(self, grid: StrategyGrid) -> None:
        entry = grid.get("XRP", "weekly")
        assert entry is not None and entry.is_core is False

    def test_doge_is_satellite(self, grid: StrategyGrid) -> None:
        entry = grid.get("DOGE", "monthly")
        assert entry is not None and entry.is_core is False

    def test_singleton_returns_same_grid(self) -> None:
        g1 = get_strategy_grid()
        g2 = get_strategy_grid()
        assert g1 is g2

    def test_summary_has_30_keys(self, grid: StrategyGrid) -> None:
        s = grid.summary()
        assert len(s) == 30
