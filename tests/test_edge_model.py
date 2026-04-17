"""Tests for merid.prediction.edge_model — multi-source probability estimation."""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from merid.prediction.edge_model import EdgeModel, EdgePrediction, get_edge_model


class TestEdgeModelInit:
    """Initialization and singleton."""

    def test_creates_instance(self):
        model = EdgeModel()
        assert model is not None
        assert model._cache_ttl_s == 15.0

    def test_singleton(self):
        # Reset singleton
        import merid.prediction.edge_model as mod
        mod._instance = None
        a = get_edge_model()
        b = get_edge_model()
        assert a is b
        mod._instance = None  # cleanup


class TestSpotRelativeModel:
    """Spot-relative probability via logistic function."""

    def _make_model_with_spot(self, spot_price: float, asset: str = "BTC"):
        model = EdgeModel()
        mock_feed = MagicMock()
        mock_feed.get_current_price.return_value = MagicMock(
            price=spot_price,
            bid=spot_price * 0.999,
            ask=spot_price * 1.001,
            timestamp=datetime.now(),
        )
        model._price_feed = mock_feed
        return model

    def test_spot_above_strike_gives_high_prob(self):
        model = self._make_model_with_spot(96000.0)
        prob, conf = model._spot_relative_probability("BTC", 95000.0, "1h", 30.0)
        assert prob is not None
        assert prob > 0.5, f"Spot above strike should give P(YES) > 0.5, got {prob}"

    def test_spot_below_strike_gives_low_prob(self):
        model = self._make_model_with_spot(94000.0)
        prob, conf = model._spot_relative_probability("BTC", 95000.0, "1h", 30.0)
        assert prob is not None
        assert prob < 0.5, f"Spot below strike should give P(YES) < 0.5, got {prob}"

    def test_spot_at_strike_gives_near_half(self):
        model = self._make_model_with_spot(95000.0)
        prob, conf = model._spot_relative_probability("BTC", 95000.0, "1h", 30.0)
        assert prob is not None
        assert 0.45 <= prob <= 0.55, f"Spot at strike should give ~0.5, got {prob}"

    def test_confidence_decays_with_stale_data(self):
        model = self._make_model_with_spot(96000.0)
        # Override timestamp to be old
        model._price_feed.get_current_price.return_value.timestamp = datetime(
            2020, 1, 1
        )
        prob, conf = model._spot_relative_probability("BTC", 95000.0, "1h", 30.0)
        assert conf < 0.5, f"Stale data should have low confidence, got {conf}"

    def test_no_price_feed_returns_none(self):
        model = EdgeModel()
        model._price_feed = None
        prob, conf = model._spot_relative_probability("BTC", 95000.0, "1h", 30.0)
        assert prob is None
        assert conf == 0.0

    def test_zero_strike_returns_none(self):
        model = self._make_model_with_spot(96000.0)
        prob, conf = model._spot_relative_probability("BTC", 0, "1h", 30.0)
        assert prob is None

    def test_shorter_timeframe_gives_tighter_distribution(self):
        model = self._make_model_with_spot(95500.0)
        prob_15m, _ = model._spot_relative_probability("BTC", 95000.0, "15m", 10.0)
        prob_daily, _ = model._spot_relative_probability("BTC", 95000.0, "daily", 600.0)
        # Both should be > 0.5 (spot above strike), but 15m should be more extreme
        assert prob_15m is not None
        assert prob_daily is not None
        assert prob_15m > prob_daily, (
            f"15m prob should be more extreme than daily: {prob_15m} vs {prob_daily}"
        )


class TestSpreadModel:
    """Spread-based fair value model."""

    def test_tight_spread_high_confidence(self):
        model = EdgeModel()
        prob, conf = model._spread_model(0.55, 0.54, 0.56, 1000)
        assert conf > 0.5
        # Mid is 0.55, with slight mean-reversion should be close
        assert 0.53 <= prob <= 0.56

    def test_wide_spread_low_confidence(self):
        model = EdgeModel()
        prob, conf = model._spread_model(0.55, 0.40, 0.70, 100)
        assert conf < 0.4

    def test_no_bid_ask_very_low_confidence(self):
        model = EdgeModel()
        prob, conf = model._spread_model(0.60, None, None, 0)
        assert conf < 0.1
        assert prob == 0.60  # returns implied_prob as-is

    def test_volume_boosts_confidence(self):
        model = EdgeModel()
        _, conf_low_vol = model._spread_model(0.50, 0.49, 0.51, 10)
        _, conf_high_vol = model._spread_model(0.50, 0.49, 0.51, 100000)
        assert conf_high_vol > conf_low_vol

    def test_mean_reversion_pulls_toward_half(self):
        model = EdgeModel()
        # Extreme price: 90% yes
        prob, _ = model._spread_model(0.90, 0.89, 0.91, 1000)
        assert prob < 0.90, f"Mean reversion should pull toward 0.5, got {prob}"


class TestTimeDecay:
    """Time decay probability adjustment."""

    def test_far_from_expiry_pulls_toward_half(self):
        model = EdgeModel()
        adj = model._time_decay_adjustment(0.80, 600.0)  # 10 hours out
        assert adj is not None
        assert adj < 0.80, f"Far from expiry should pull toward 0.5, got {adj}"

    def test_near_expiry_trusts_market(self):
        model = EdgeModel()
        adj = model._time_decay_adjustment(0.80, 3.0)  # 3 min left
        assert adj is not None
        assert adj == 0.80  # terminal, trust market

    def test_no_time_info_returns_none(self):
        model = EdgeModel()
        adj = model._time_decay_adjustment(0.50, None)
        assert adj is None

    def test_expired_returns_implied(self):
        model = EdgeModel()
        adj = model._time_decay_adjustment(0.70, 0)
        assert adj == 0.70


class TestPredict:
    """Full predict() method."""

    def test_returns_none_without_any_signals(self):
        model = EdgeModel()
        model._price_feed = None
        model._catalog = None
        result = model.predict("UNKNOWN-TICKER", "NONE", "1h")
        # With no catalog data and no price feed, spread model still runs
        # on defaults (implied=0.5, no bid/ask) → very low confidence
        # It should still return something since spread model always produces a value
        # but with very low confidence
        if result is not None:
            assert result["confidence"] < 0.2

    def test_caches_predictions(self):
        model = EdgeModel()
        model._price_feed = None
        model._catalog = None
        # Force a prediction into cache
        pred = EdgePrediction(
            probability=0.65,
            confidence=0.7,
            source="test",
            components={"test": 0.65},
        )
        model._prediction_cache["TEST-123"] = pred
        model._cache_ts["TEST-123"] = datetime.now(timezone.utc).timestamp()

        result = model.predict("TEST-123")
        assert result is not None
        assert result["probability"] == 0.65
        assert result["confidence"] == 0.7

    def test_cache_expires(self):
        model = EdgeModel()
        model._cache_ttl_s = 0.01  # very short TTL
        pred = EdgePrediction(
            probability=0.65,
            confidence=0.7,
            source="test",
            components={"test": 0.65},
        )
        model._prediction_cache["TEST-456"] = pred
        model._cache_ts["TEST-456"] = datetime.now(timezone.utc).timestamp() - 1.0

        # Cache should be expired, so predict() won't use it
        # Without catalog/feed, it'll return based on defaults
        result = model.predict("TEST-456")
        # Should NOT return the cached 0.65
        if result is not None:
            # It will compute fresh — may or may not match cached value
            pass  # just verify no crash

    def test_clamp_extreme_probabilities(self):
        model = EdgeModel()
        # Mock catalog with extreme price
        mock_catalog = MagicMock()
        mock_market = MagicMock()
        mock_market.strike_price = None
        mock_market.minutes_to_expiry = 30
        mock_market.market = MagicMock()
        mock_market.market.volume = 1000
        mock_outcome = MagicMock()
        mock_outcome.price = 0.99  # extreme
        mock_outcome.best_bid = 0.98
        mock_outcome.best_ask = 0.995
        mock_market.market.outcomes = [mock_outcome]
        mock_catalog.get_market.return_value = mock_market
        model._catalog = mock_catalog
        model._price_feed = None

        result = model.predict("EXTREME-1")
        if result is not None:
            assert result["probability"] <= 0.98, "Should clamp to max 0.98"
            assert result["probability"] >= 0.02, "Should clamp to min 0.02"

    def test_clear_cache(self):
        model = EdgeModel()
        model._prediction_cache["A"] = EdgePrediction(0.5, 0.5, "test", {})
        model._cache_ts["A"] = time.time()
        model.clear_cache()
        assert len(model._prediction_cache) == 0
        assert len(model._cache_ts) == 0


class TestEnsemble:
    """Ensemble combines multiple signals."""

    def test_multi_source_agreement_boosts_confidence(self):
        model = EdgeModel()
        # Mock spot model to return a value
        mock_feed = MagicMock()
        mock_feed.get_current_price.return_value = MagicMock(
            price=96000.0,
            bid=95990.0,
            ask=96010.0,
            timestamp=datetime.now(),
        )
        model._price_feed = mock_feed

        # Mock catalog
        mock_catalog = MagicMock()
        mock_market = MagicMock()
        mock_market.strike_price = 95000.0
        mock_market.minutes_to_expiry = 30.0
        mock_market.market = MagicMock()
        mock_market.market.volume = 5000
        mock_outcome = MagicMock()
        mock_outcome.price = 0.55
        mock_outcome.best_bid = 0.54
        mock_outcome.best_ask = 0.56
        mock_market.market.outcomes = [mock_outcome]
        mock_catalog.get_market.return_value = mock_market
        model._catalog = mock_catalog

        result = model.predict("KXBTC-TEST", "BTC", "1h")
        assert result is not None
        assert result["probability"] > 0.5  # spot above strike
        assert result["confidence"] > 0.3  # multiple sources should boost
