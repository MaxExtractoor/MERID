"""Tests for BTC-Anchored Cross-Asset Move Model.

Covers:
  - BetaEstimate dataclass methods
  - BtcAnchoredMoveModel OLS regression
  - Prior fallback when insufficient data
  - Conditional bands by BTC move magnitude
  - Dollar and percent move predictions
  - Adjusted expected move blending
  - Suggested strike distance
  - Singleton access
  - Thread safety basics
  - Snapshot serialization
"""

from __future__ import annotations

import math
import random
import threading
import time
from decimal import Decimal
from typing import Dict, List

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _generate_correlated_returns(
    n: int,
    beta: float = 1.5,
    alpha: float = 0.0,
    noise_std: float = 0.001,
    btc_std: float = 0.005,
    seed: int = 42,
) -> tuple:
    """Generate synthetic BTC and alt returns with known beta."""
    rng = random.Random(seed)
    btc_rets = [rng.gauss(0, btc_std) for _ in range(n)]
    alt_rets = [alpha + beta * r + rng.gauss(0, noise_std) for r in btc_rets]
    return btc_rets, alt_rets


def _feed_model(model, btc_rets, alt_rets, asset="ETH", timeframe="15m"):
    """Feed paired returns into the model."""
    for b, a in zip(btc_rets, alt_rets):
        model.record_returns({"BTC": b, asset: a}, timeframe=timeframe)


# ═══════════════════════════════════════════════════════════════════════════
# Tests — BetaEstimate dataclass
# ═══════════════════════════════════════════════════════════════════════════

class TestBetaEstimate:
    def test_expected_alt_move_pct(self):
        from merid.signals.btc_anchored_move import BetaEstimate

        est = BetaEstimate(
            asset="ETH", timeframe="15m",
            beta=1.5, alpha=0.001,
            r_squared=0.85, residual_std=0.001,
            sample_count=50, is_prior=False,
        )
        # BTC +1% → ETH ≈ 0.1% + 1.5 * 1% = 1.6%
        result = est.expected_alt_move_pct(0.01)
        assert abs(result - 0.016) < 1e-6

    def test_expected_alt_dollar_move(self):
        from merid.signals.btc_anchored_move import BetaEstimate

        est = BetaEstimate(
            asset="ETH", timeframe="1h",
            beta=1.2, alpha=0.0,
            r_squared=0.80, residual_std=0.001,
            sample_count=50, is_prior=False,
        )
        # BTC at 84000, moves +250 USD → r_BTC = 250/84000 ≈ 0.002976
        # ETH at 2100 → ΔP_ETH ≈ 1.2 * 0.002976 * 2100 ≈ 7.50
        dollar = est.expected_alt_dollar_move(
            btc_delta_usd=250.0, btc_spot=84000.0, alt_spot=2100.0,
        )
        assert 7.0 < dollar < 8.0

    def test_dollar_move_zero_btc_spot(self):
        from merid.signals.btc_anchored_move import BetaEstimate

        est = BetaEstimate(
            asset="SOL", timeframe="15m",
            beta=1.4, alpha=0.0,
            r_squared=0.7, residual_std=0.001,
            sample_count=30, is_prior=False,
        )
        assert est.expected_alt_dollar_move(100.0, 0.0, 150.0) == 0.0

    def test_to_dict(self):
        from merid.signals.btc_anchored_move import BetaEstimate

        est = BetaEstimate(
            asset="XRP", timeframe="daily",
            beta=1.35, alpha=0.0002,
            r_squared=0.65, residual_std=0.003,
            sample_count=40, is_prior=False,
        )
        d = est.to_dict()
        assert d["asset"] == "XRP"
        assert d["timeframe"] == "daily"
        assert d["beta"] == 1.35
        assert d["is_prior"] is False
        assert "r_squared" in d


# ═══════════════════════════════════════════════════════════════════════════
# Tests — OLS Beta Regression
# ═══════════════════════════════════════════════════════════════════════════

class TestBetaRegression:
    def test_recovers_known_beta(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=20)
        btc_rets, eth_rets = _generate_correlated_returns(100, beta=1.5, noise_std=0.0005)
        _feed_model(model, btc_rets, eth_rets, "ETH", "15m")

        est = model.get_beta("ETH", "15m")
        assert not est.is_prior
        assert est.sample_count == 100
        assert abs(est.beta - 1.5) < 0.15, f"Expected beta ≈ 1.5, got {est.beta}"
        assert est.r_squared > 0.8

    def test_recovers_known_beta_with_alpha(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=20)
        btc_rets, sol_rets = _generate_correlated_returns(
            100, beta=1.8, alpha=0.0005, noise_std=0.0005,
        )
        _feed_model(model, btc_rets, sol_rets, "SOL", "1h")

        est = model.get_beta("SOL", "1h")
        assert abs(est.beta - 1.8) < 0.2
        assert abs(est.alpha - 0.0005) < 0.001

    def test_btc_beta_is_always_one(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel()
        est = model.get_beta("BTC", "15m")
        assert est.beta == 1.0
        assert est.r_squared == 1.0
        assert not est.is_prior

    def test_prior_fallback_insufficient_data(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel, PRIOR_BETAS

        model = BtcAnchoredMoveModel(window=100, min_obs=20)
        # Feed only 5 observations — below min_obs threshold
        for i in range(5):
            model.record_returns({"BTC": 0.001 * i, "ETH": 0.0015 * i}, "15m")

        est = model.get_beta("ETH", "15m")
        assert est.is_prior
        assert est.beta == PRIOR_BETAS["ETH"]["15m"]
        assert est.sample_count == 5

    def test_different_timeframes_independent(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=20)

        btc_15m, eth_15m = _generate_correlated_returns(50, beta=1.2, seed=1)
        btc_1h, eth_1h = _generate_correlated_returns(50, beta=1.8, seed=2)

        _feed_model(model, btc_15m, eth_15m, "ETH", "15m")
        _feed_model(model, btc_1h, eth_1h, "ETH", "1h")

        est_15m = model.get_beta("ETH", "15m")
        est_1h = model.get_beta("ETH", "1h")

        assert abs(est_15m.beta - 1.2) < 0.3
        assert abs(est_1h.beta - 1.8) < 0.3
        # They should differ meaningfully
        assert abs(est_15m.beta - est_1h.beta) > 0.2

    def test_windowing_trims_old_data(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=30, min_obs=10)
        # Feed 50 observations → only last 30 should be kept
        btc_rets, eth_rets = _generate_correlated_returns(50, beta=1.5)
        _feed_model(model, btc_rets, eth_rets, "ETH", "15m")

        est = model.get_beta("ETH", "15m")
        assert est.sample_count == 30


# ═══════════════════════════════════════════════════════════════════════════
# Tests — Conditional Bands
# ═══════════════════════════════════════════════════════════════════════════

class TestConditionalBands:
    def test_returns_empty_with_no_data(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel()
        bands = model.get_conditional_bands("ETH", "15m")
        assert bands == []

    def test_buckets_match_move_ranges(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel, MOVE_BUCKETS

        model = BtcAnchoredMoveModel(window=500, min_obs=5)
        btc_rets, eth_rets = _generate_correlated_returns(200, beta=1.5, btc_std=0.02)
        _feed_model(model, btc_rets, eth_rets, "ETH", "15m")

        bands = model.get_conditional_bands("ETH", "15m")
        assert len(bands) == len(MOVE_BUCKETS)

        # Total count across all buckets should equal number of observations
        total = sum(b.count for b in bands)
        assert total == 200

    def test_bucket_stats_serialization(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=500, min_obs=5)
        btc_rets, eth_rets = _generate_correlated_returns(100, beta=1.3, btc_std=0.015)
        _feed_model(model, btc_rets, eth_rets, "ETH", "1h")

        bands = model.get_conditional_bands("ETH", "1h")
        for b in bands:
            d = b.to_dict()
            assert "bucket" in d
            assert "count" in d
            assert "mean_btc_pct" in d
            assert "mean_alt_pct" in d


# ═══════════════════════════════════════════════════════════════════════════
# Tests — Convenience Methods
# ═══════════════════════════════════════════════════════════════════════════

class TestConvenienceMethods:
    def test_expected_dollar_move(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=20)
        btc_rets, eth_rets = _generate_correlated_returns(50, beta=1.5, noise_std=0.0003)
        _feed_model(model, btc_rets, eth_rets, "ETH", "15m")

        dollar = model.expected_dollar_move(
            asset="ETH",
            btc_delta_usd=300.0,
            btc_spot=84000.0,
            alt_spot=2100.0,
            timeframe="15m",
        )
        # β ≈ 1.5, r_BTC = 300/84000 ≈ 0.00357
        # ΔP_ETH ≈ 1.5 * 0.00357 * 2100 ≈ 11.25
        assert 8.0 < dollar < 16.0

    def test_expected_pct_move(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=20)
        btc_rets, sol_rets = _generate_correlated_returns(50, beta=1.8, noise_std=0.0003)
        _feed_model(model, btc_rets, sol_rets, "SOL", "1h")

        pct = model.expected_pct_move("SOL", btc_move_pct=0.01, timeframe="1h")
        # β ≈ 1.8 → ~1.8%
        assert 0.015 < pct < 0.022

    def test_adjusted_expected_move_blending(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=20)
        btc_rets, eth_rets = _generate_correlated_returns(
            100, beta=1.5, noise_std=0.0003,
        )
        _feed_model(model, btc_rets, eth_rets, "ETH", "15m")

        base_move = 0.005  # 0.5% from independent vol model
        btc_ret = 0.01     # BTC moved 1% this period

        adjusted = model.adjusted_expected_move(
            asset="ETH", timeframe="15m",
            base_expected_move=base_move,
            btc_return_current=btc_ret,
        )
        # Should be larger than base since β*r_BTC ≈ 1.5*1% = 1.5% > 0.5%
        assert adjusted > base_move

    def test_adjusted_expected_move_no_data_returns_base(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=20)
        # No data → prior → is_prior=True → returns base
        adjusted = model.adjusted_expected_move(
            asset="DOGE", timeframe="15m",
            base_expected_move=0.005,
            btc_return_current=0.02,
        )
        assert adjusted == 0.005


# ═══════════════════════════════════════════════════════════════════════════
# Tests — Strike Distance Suggestion
# ═══════════════════════════════════════════════════════════════════════════

class TestStrikeDistanceSuggestion:
    def test_widens_band_for_high_beta_asset(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=20)
        btc_rets, doge_rets = _generate_correlated_returns(50, beta=2.0, noise_std=0.0005)
        _feed_model(model, btc_rets, doge_rets, "DOGE", "15m")

        suggested = model.suggested_strike_distance_pct(
            asset="DOGE", timeframe="15m",
            btc_atr_pct=0.005,   # BTC ATR = 0.5% of price
            base_distance_pct=0.08,  # static 8% band
        )
        # β ≈ 2.0, implied alt ATR ≈ 2.0 * 0.5% = 1.0%
        # 2 × 1.0% = 2.0%, which is less than base 8%
        # So should return base_distance_pct
        assert suggested >= 0.08

    def test_caps_at_3x_base(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=20)
        btc_rets, doge_rets = _generate_correlated_returns(50, beta=2.0, noise_std=0.0005)
        _feed_model(model, btc_rets, doge_rets, "DOGE", "15m")

        suggested = model.suggested_strike_distance_pct(
            asset="DOGE", timeframe="15m",
            btc_atr_pct=0.10,     # Extreme: BTC ATR = 10%
            base_distance_pct=0.05,
        )
        # β * 10% = 20%, 2× = 40% → way over 3× base (15%)
        assert suggested <= 0.15 + 1e-9  # Capped at 3× base

    def test_uses_prior_beta_with_no_data(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel, PRIOR_BETAS

        model = BtcAnchoredMoveModel(window=100, min_obs=20)
        # No data fed → uses prior
        suggested = model.suggested_strike_distance_pct(
            asset="XRP", timeframe="1h",
            btc_atr_pct=0.003,
            base_distance_pct=0.12,
        )
        # Prior β for XRP-1h = 1.25
        # implied alt ATR = 1.25 * 0.3% = 0.375%, 2× = 0.75%
        # base 12% > 0.75% → returns base
        assert abs(suggested - 0.12) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════
# Tests — Snapshot & Serialization
# ═══════════════════════════════════════════════════════════════════════════

class TestSnapshot:
    def test_full_snapshot(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=10)
        btc_rets, eth_rets = _generate_correlated_returns(50, beta=1.3, btc_std=0.01)
        _feed_model(model, btc_rets, eth_rets, "ETH", "15m")

        snap = model.snapshot("ETH", "15m")
        assert snap.beta.asset == "ETH"
        assert snap.beta.timeframe == "15m"
        assert not snap.beta.is_prior
        assert snap.btc_vol_annualized > 0
        assert snap.alt_vol_annualized > 0
        assert -1.0 <= snap.correlation <= 1.0
        assert snap.correlation > 0.5  # Should be strongly positive

    def test_snapshot_to_dict(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=10)
        btc_rets, sol_rets = _generate_correlated_returns(50, beta=1.6)
        _feed_model(model, btc_rets, sol_rets, "SOL", "1h")

        d = model.snapshot("SOL", "1h").to_dict()
        assert "beta" in d
        assert "conditional_bands" in d
        assert "btc_vol_ann" in d
        assert "alt_vol_ann" in d
        assert "correlation" in d
        assert isinstance(d["beta"]["beta"], float)

    def test_all_betas_snapshot(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel, SUPPORTED_ASSETS

        model = BtcAnchoredMoveModel(window=200, min_obs=20)
        # Feed data for all assets
        for i in range(30):
            returns = {
                "BTC": random.gauss(0, 0.005),
                "ETH": random.gauss(0, 0.007),
                "SOL": random.gauss(0, 0.010),
                "XRP": random.gauss(0, 0.008),
                "DOGE": random.gauss(0, 0.012),
            }
            model.record_returns(returns, "15m")

        snap = model.all_betas_snapshot("15m")
        assert set(snap.keys()) == set(SUPPORTED_ASSETS)
        assert snap["BTC"]["beta"] == 1.0


# ═══════════════════════════════════════════════════════════════════════════
# Tests — Singleton & Module Structure
# ═══════════════════════════════════════════════════════════════════════════

class TestModuleStructure:
    def test_singleton(self):
        from merid.signals.btc_anchored_move import get_btc_anchored_model

        m1 = get_btc_anchored_model()
        m2 = get_btc_anchored_model()
        assert m1 is m2

    def test_supported_assets(self):
        from merid.signals.btc_anchored_move import SUPPORTED_ASSETS

        assert "BTC" in SUPPORTED_ASSETS
        assert "ETH" in SUPPORTED_ASSETS
        assert "SOL" in SUPPORTED_ASSETS
        assert "XRP" in SUPPORTED_ASSETS
        assert "DOGE" in SUPPORTED_ASSETS

    def test_prior_betas_all_assets(self):
        from merid.signals.btc_anchored_move import PRIOR_BETAS, SUPPORTED_ASSETS

        for asset in SUPPORTED_ASSETS:
            assert asset in PRIOR_BETAS, f"Missing prior for {asset}"
            for tf in ("15m", "1h", "daily", "weekly"):
                assert tf in PRIOR_BETAS[asset], f"Missing prior for {asset}/{tf}"

    def test_move_buckets_contiguous(self):
        from merid.signals.btc_anchored_move import MOVE_BUCKETS

        assert len(MOVE_BUCKETS) >= 4
        # Buckets should be contiguous
        for i in range(len(MOVE_BUCKETS) - 1):
            assert MOVE_BUCKETS[i][1] == MOVE_BUCKETS[i + 1][0], \
                f"Gap between bucket {i} and {i+1}"
        # Last bucket should go to infinity
        assert MOVE_BUCKETS[-1][1] == float("inf")

    def test_observation_counts(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel()
        model.record_returns({"BTC": 0.01, "ETH": 0.015}, "15m")
        model.record_returns({"BTC": 0.02, "SOL": 0.03}, "1h")

        counts = model.observation_counts
        assert counts["15m"]["BTC"] == 1
        assert counts["15m"]["ETH"] == 1
        assert counts["1h"]["BTC"] == 1
        assert counts["1h"]["SOL"] == 1

    def test_reset_clears_all(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel()
        model.record_returns({"BTC": 0.01, "ETH": 0.015}, "15m")
        model.reset()
        assert model.observation_counts == {}


# ═══════════════════════════════════════════════════════════════════════════
# Tests — Thread Safety
# ═══════════════════════════════════════════════════════════════════════════

class TestThreadSafety:
    def test_concurrent_writes_and_reads(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=500, min_obs=5)
        errors: List[str] = []

        def writer(asset, seed):
            rng = random.Random(seed)
            try:
                for _ in range(100):
                    model.record_returns(
                        {"BTC": rng.gauss(0, 0.005), asset: rng.gauss(0, 0.008)},
                        "15m",
                    )
            except Exception as e:
                errors.append(f"Writer {asset}: {e}")

        def reader():
            try:
                for _ in range(50):
                    model.get_beta("ETH", "15m")
                    model.get_beta("SOL", "15m")
                    model.snapshot("DOGE", "15m")
            except Exception as e:
                errors.append(f"Reader: {e}")

        threads = [
            threading.Thread(target=writer, args=("ETH", 1)),
            threading.Thread(target=writer, args=("SOL", 2)),
            threading.Thread(target=writer, args=("DOGE", 3)),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"


# ═══════════════════════════════════════════════════════════════════════════
# Tests — Record Prices (convenience)
# ═══════════════════════════════════════════════════════════════════════════

class TestRecordPrices:
    def test_auto_derives_returns(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=100, min_obs=5)

        # First call: stores prices, no returns yet
        model.record_prices({"BTC": 84000.0, "ETH": 2100.0}, "15m")
        assert model.observation_counts.get("15m", {}).get("BTC", 0) == 0

        # Second call: computes returns
        model.record_prices({"BTC": 84840.0, "ETH": 2121.0}, "15m")  # +1%, +1%
        assert model.observation_counts["15m"]["BTC"] == 1
        assert model.observation_counts["15m"]["ETH"] == 1

    def test_multi_price_feeds_build_beta(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=200, min_obs=10)
        rng = random.Random(99)

        btc_price = 84000.0
        eth_price = 2100.0
        true_beta = 1.5

        for _ in range(30):
            btc_ret = rng.gauss(0, 0.003)
            eth_ret = true_beta * btc_ret + rng.gauss(0, 0.0005)
            btc_price *= (1 + btc_ret)
            eth_price *= (1 + eth_ret)
            model.record_prices({"BTC": btc_price, "ETH": eth_price}, "15m")

        est = model.get_beta("ETH", "15m")
        # After 30 price updates → 29 return observations
        assert est.sample_count >= 20
        assert abs(est.beta - 1.5) < 0.3
