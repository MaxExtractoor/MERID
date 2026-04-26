"""Tests for Kalshi Macro Overlay module.

Validates:
- Macro market categorization
- Regime classification
- Conviction score computation
- Asset sensitivity mapping
- State update and caching
"""

import time
import pytest
from typing import Dict, List

from merid.kalshi.macro_models import (
    AssetMacroSensitivity,
    MacroCategory,
    MacroConvictionScore,
    MacroMarketState,
    MacroRegime,
    MacroState,
    VolatilityRegime,
    DEFAULT_ASSET_SENSITIVITIES,
)
from merid.kalshi.macro_overlay import (
    KalshiMacroOverlay,
    MacroConvictionScorer,
    get_kalshi_macro_overlay,
    reset_kalshi_macro_overlay,
    MACRO_CATEGORY_PATTERNS,
)


class TestMacroModels:
    """Test macro data model behaviors."""
    
    def test_macro_market_state_liquidity(self):
        """Test liquidity detection."""
        # Liquid market
        liquid = MacroMarketState(
            ticker="KXFRHR-25JAN",
            category=MacroCategory.FINANCIALS,
            title="Fed rate hike Jan 2025",
            yes_prob=0.3,
            yes_prob_24h_ago=0.35,
            yes_prob_7d_ago=0.4,
            spread_cents=2,
            volume_24h=500,
            open_interest=1000,
            last_update_ts=time.time(),
            seconds_to_expiry=86400,
        )
        assert liquid.is_liquid
        assert abs(liquid.prob_change_24h - (-0.05)) < 0.0001
        
        # Illiquid market (low volume)
        illiquid_vol = MacroMarketState(
            ticker="KXTEST-ILQ",
            category=MacroCategory.ECONOMICS,
            title="Test",
            yes_prob=0.5,
            yes_prob_24h_ago=0.5,
            yes_prob_7d_ago=0.5,
            spread_cents=2,
            volume_24h=10,  # Too low
            open_interest=100,
            last_update_ts=time.time(),
        )
        assert not illiquid_vol.is_liquid
        
        # Illiquid market (wide spread)
        illiquid_spread = MacroMarketState(
            ticker="KXTEST-ILQ2",
            category=MacroCategory.ECONOMICS,
            title="Test",
            yes_prob=0.5,
            yes_prob_24h_ago=0.5,
            yes_prob_7d_ago=0.5,
            spread_cents=15,  # Too wide
            volume_24h=200,
            open_interest=100,
            last_update_ts=time.time(),
        )
        assert not illiquid_spread.is_liquid
    
    def test_asset_sensitivity_validation(self):
        """Test sensitivity config validation."""
        valid = AssetMacroSensitivity(
            asset="BTC",
            risk_on_sensitivity=0.7,
            rate_cut_sensitivity=0.6,
            cpi_surprise_sensitivity=-0.4,
            recession_sensitivity=-0.5,
            tech_sentiment_sensitivity=0.3,
        )
        assert valid.validate()
        
        invalid = AssetMacroSensitivity(
            asset="INVALID",
            risk_on_sensitivity=1.5,  # Out of range
        )
        assert not invalid.validate()
    
    def test_default_sensitivities(self):
        """Test default asset sensitivities exist for tracked assets."""
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert asset in DEFAULT_ASSET_SENSITIVITIES
            sens = DEFAULT_ASSET_SENSITIVITIES[asset]
            assert sens.validate()
            assert sens.asset == asset
        
        # Verify expected relationships
        assert DEFAULT_ASSET_SENSITIVITIES["SOL"].risk_on_sensitivity > \
               DEFAULT_ASSET_SENSITIVITIES["BTC"].risk_on_sensitivity
        # Alts more sensitive to risk-on than BTC


class TestMacroConvictionScorer:
    """Test conviction score computation."""
    
    @pytest.fixture
    def scorer(self):
        return MacroConvictionScorer()
    
    @pytest.fixture
    def risk_on_state(self):
        """Create a risk-on macro state."""
        return MacroState(
            timestamp=time.time(),
            financials={
                "KXFRHR-25JAN": MacroMarketState(
                    ticker="KXFRHR-25JAN",
                    category=MacroCategory.FINANCIALS,
                    title="Fed hike Jan 2025",
                    yes_prob=0.1,  # Low hike prob = dovish = risk-on
                    yes_prob_24h_ago=0.2,
                    yes_prob_7d_ago=0.3,
                    spread_cents=2,
                    volume_24h=1000,
                    open_interest=2000,
                    last_update_ts=time.time(),
                )
            },
            economics={
                "KXRECES-25Q1": MacroMarketState(
                    ticker="KXRECES-25Q1",
                    category=MacroCategory.ECONOMICS,
                    title="Recession 2025 Q1",
                    yes_prob=0.2,  # Low recession prob = growth = risk-on
                    yes_prob_24h_ago=0.25,
                    yes_prob_7d_ago=0.3,
                    spread_cents=3,
                    volume_24h=500,
                    open_interest=1000,
                    last_update_ts=time.time(),
                )
            },
            macro_regime=MacroRegime.RISK_ON,
            vol_regime=VolatilityRegime.CONTRACTING,
            event_risk_score=0.2,
            fed_hike_prob=0.1,
            recession_prob=0.2,
        )
    
    @pytest.fixture
    def risk_off_state(self):
        """Create a risk-off macro state."""
        return MacroState(
            timestamp=time.time(),
            financials={
                "KXFRHR-25JAN": MacroMarketState(
                    ticker="KXFRHR-25JAN",
                    category=MacroCategory.FINANCIALS,
                    title="Fed hike Jan 2025",
                    yes_prob=0.8,  # High hike prob = hawkish = risk-off
                    yes_prob_24h_ago=0.7,
                    yes_prob_7d_ago=0.6,
                    spread_cents=2,
                    volume_24h=1000,
                    open_interest=2000,
                    last_update_ts=time.time(),
                )
            },
            economics={
                "KXRECES-25Q1": MacroMarketState(
                    ticker="KXRECES-25Q1",
                    category=MacroCategory.ECONOMICS,
                    title="Recession 2025 Q1",
                    yes_prob=0.7,  # High recession prob = risk-off
                    yes_prob_24h_ago=0.6,
                    yes_prob_7d_ago=0.5,
                    spread_cents=3,
                    volume_24h=500,
                    open_interest=1000,
                    last_update_ts=time.time(),
                )
            },
            macro_regime=MacroRegime.RISK_OFF,
            vol_regime=VolatilityRegime.EXPANDING,
            event_risk_score=0.8,
            fed_hike_prob=0.8,
            recession_prob=0.7,
        )
    
    def test_score_risk_on_bullish(self, scorer, risk_on_state):
        """Test that risk-on produces bullish scores."""
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            score = scorer.compute_score(asset, risk_on_state)
            assert score.score > 0.5, f"{asset} should be bullish in risk-on"
            assert score.confidence > 0.4
            assert score.recommended_modifier > 1.0, f"{asset} should have positive modifier"
            assert score.is_bullish
            assert not score.is_bearish
    
    def test_score_risk_off_bearish(self, scorer, risk_off_state):
        """Test that risk-off produces bearish scores."""
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            score = scorer.compute_score(asset, risk_off_state)
            assert score.score < 0.5, f"{asset} should be bearish in risk-off"
            assert score.confidence > 0.4
            assert score.recommended_modifier < 1.0, f"{asset} should have negative modifier"
            assert score.is_bearish
            assert not score.is_bullish
    
    def test_score_neutral_state(self, scorer):
        """Test neutral state produces neutral scores."""
        neutral_state = MacroState(
            timestamp=time.time(),
            macro_regime=MacroRegime.NEUTRAL,
            vol_regime=VolatilityRegime.STABLE,
            event_risk_score=0.3,
        )
        
        for asset in ["BTC", "ETH", "SOL"]:
            score = scorer.compute_score(asset, neutral_state)
            assert 0.4 <= score.score <= 0.6, f"{asset} should be neutral"
            assert score.recommended_modifier == 1.0
    
    def test_score_unknown_asset(self, scorer, risk_on_state):
        """Test unknown asset returns neutral with low confidence."""
        score = scorer.compute_score("UNKNOWN", risk_on_state)
        assert score.score == 0.5
        assert score.confidence < 0.4
        assert score.recommended_modifier == 1.0
    
    def test_contributions_sum_correctly(self, scorer, risk_on_state):
        """Test that contribution breakdown sums approximately to total."""
        score = scorer.compute_score("BTC", risk_on_state)
        total_contrib = (
            score.risk_on_contribution +
            score.monetary_policy_contribution +
            score.inflation_contribution +
            score.recession_contribution +
            score.tech_sentiment_contribution
        )
        # Score = 0.5 + total_contribution (clamped to [0, 1])
        expected_base = 0.5 + total_contrib
        assert abs(score.score - max(0.0, min(1.0, expected_base))) < 0.01


class TestKalshiMacroOverlay:
    """Test the main macro overlay service."""
    
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        reset_kalshi_macro_overlay()
        yield
        reset_kalshi_macro_overlay()
    
    def test_singleton_pattern(self):
        """Test singleton returns same instance."""
        overlay1 = get_kalshi_macro_overlay()
        overlay2 = get_kalshi_macro_overlay()
        assert overlay1 is overlay2
    
    def test_initial_state_none(self):
        """Test initial state is None."""
        overlay = KalshiMacroOverlay()
        assert overlay.get_macro_state() is None
    
    def test_update_from_markets(self):
        """Test updating from market data."""
        overlay = KalshiMacroOverlay()
        
        markets = [
            {
                "ticker": "KXFRHR-25JAN",
                "title": "Fed rate hike Jan 2025",
                "yes_ask": 0.15,  # Low hike probability
                "spread_cents": 2,
                "volume_24h": 1000,
                "open_interest": 2000,
                "seconds_to_expiry": 86400,
            },
            {
                "ticker": "KXRECES-25Q1",
                "title": "Recession Q1 2025",
                "yes_ask": 0.25,  # Low recession probability
                "spread_cents": 3,
                "volume_24h": 500,
                "open_interest": 1000,
            },
        ]
        
        overlay.update_from_markets(markets)
        
        state = overlay.get_macro_state()
        assert state is not None
        assert state.macro_regime == MacroRegime.RISK_ON
        assert len(state.financials) == 1
        assert len(state.economics) == 1
    
    def test_ticker_categorization(self):
        """Test ticker to category mapping."""
        overlay = KalshiMacroOverlay()
        
        assert overlay._categorize_ticker("KXFRHR-25JAN") == MacroCategory.FINANCIALS
        assert overlay._categorize_ticker("KXCPI-25JAN") == MacroCategory.FINANCIALS
        assert overlay._categorize_ticker("KXGEOP-25JAN") == MacroCategory.ELECTIONS
        assert overlay._categorize_ticker("KXWTI-25JAN") == MacroCategory.COMMODITIES
        assert overlay._categorize_ticker("KXGLD-25JAN") == MacroCategory.COMMODITIES
        assert overlay._categorize_ticker("KXGDP-25Q1") == MacroCategory.ECONOMICS
        assert overlay._categorize_ticker("KXTECH-25JAN") == MacroCategory.TECH_SCIENCE
        assert overlay._categorize_ticker("UNKNOWN") is None
    
    def test_conviction_scores_after_update(self):
        """Test conviction scores after state update."""
        overlay = KalshiMacroOverlay()
        
        # Risk-on markets
        markets = [
            {
                "ticker": "KXFRHR-25JAN",
                "title": "Fed rate hike",
                "yes_ask": 0.1,  # Dovish
                "spread_cents": 2,
                "volume_24h": 1000,
                "open_interest": 2000,
            },
            {
                "ticker": "KXRECES-25Q1",
                "title": "Recession",
                "yes_ask": 0.2,  # Low recession fear
                "spread_cents": 3,
                "volume_24h": 500,
                "open_interest": 1000,
            },
        ]
        
        overlay.update_from_markets(markets)
        scores = overlay.get_conviction_scores()
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert asset in scores
            assert scores[asset].score > 0.5
            assert scores[asset].is_bullish
    
    def test_conviction_scores_no_state(self):
        """Test conviction scores when no state available."""
        overlay = KalshiMacroOverlay()
        scores = overlay.get_conviction_scores()
        
        for asset in overlay.tracked_assets:
            assert asset in scores
            assert scores[asset].score == 0.5  # Neutral
            assert scores[asset].confidence < 0.4  # Low confidence
            assert scores[asset].recommended_modifier == 1.0
    
    def test_callback_registration(self):
        """Test callback registration and invocation."""
        overlay = KalshiMacroOverlay()
        callback_calls = []
        
        def callback(state: MacroState):
            callback_calls.append(state)
        
        overlay.register_callback(callback)
        
        markets = [{
            "ticker": "KXFRHR-25JAN",
            "title": "Fed rate hike",
            "yes_ask": 0.5,
            "spread_cents": 2,
            "volume_24h": 1000,
            "open_interest": 2000,
        }]
        
        overlay.update_from_markets(markets)
        
        assert len(callback_calls) == 1
        assert callback_calls[0] is not None
    
    def test_stale_data_pruning(self):
        """Test that stale market data is pruned."""
        overlay = KalshiMacroOverlay()
        
        # Create old market data
        old_time = time.time() - 400  # > 300 second max age
        overlay._market_cache["OLD"] = MacroMarketState(
            ticker="OLD",
            category=MacroCategory.FINANCIALS,
            title="Old market",
            yes_prob=0.5,
            yes_prob_24h_ago=0.5,
            yes_prob_7d_ago=0.5,
            spread_cents=2,
            volume_24h=1000,
            open_interest=1000,
            last_update_ts=old_time,
        )
        
        # Update with fresh data
        markets = [{
            "ticker": "KXFRHR-25JAN",
            "title": "Fed rate hike",
            "yes_ask": 0.5,
            "spread_cents": 2,
            "volume_24h": 1000,
            "open_interest": 2000,
        }]
        
        overlay.update_from_markets(markets)
        
        # Old data should be pruned
        assert "OLD" not in overlay._market_cache
        assert "KXFRHR-25JAN" in overlay._market_cache


class TestRegimeClassification:
    """Test macro regime classification logic."""
    
    def test_risk_on_classification(self):
        """Test risk-on regime detection."""
        overlay = KalshiMacroOverlay()
        
        # Dovish Fed + low recession fear = risk-on
        state = MacroState(
            timestamp=time.time(),
            financials={
                "KXFRHR": MacroMarketState(
                    ticker="KXFRHR",
                    category=MacroCategory.FINANCIALS,
                    title="Fed hike",
                    yes_prob=0.1,  # Very low hike probability
                    yes_prob_24h_ago=0.1,
                    yes_prob_7d_ago=0.1,
                    spread_cents=2,
                    volume_24h=1000,
                    open_interest=1000,
                    last_update_ts=time.time(),
                )
            },
            economics={
                "KXRECES": MacroMarketState(
                    ticker="KXRECES",
                    category=MacroCategory.ECONOMICS,
                    title="Recession",
                    yes_prob=0.1,  # Very low recession probability
                    yes_prob_24h_ago=0.1,
                    yes_prob_7d_ago=0.1,
                    spread_cents=2,
                    volume_24h=1000,
                    open_interest=1000,
                    last_update_ts=time.time(),
                )
            },
            event_risk_score=0.1,
        )
        
        regime = overlay._classify_regime(state)
        assert regime == MacroRegime.RISK_ON
    
    def test_risk_off_classification(self):
        """Test risk-off regime detection."""
        overlay = KalshiMacroOverlay()
        
        # Hawkish Fed + high recession fear = risk-off
        state = MacroState(
            timestamp=time.time(),
            financials={
                "KXFRHR": MacroMarketState(
                    ticker="KXFRHR",
                    category=MacroCategory.FINANCIALS,
                    title="Fed hike",
                    yes_prob=0.8,  # High hike probability
                    yes_prob_24h_ago=0.8,
                    yes_prob_7d_ago=0.8,
                    spread_cents=2,
                    volume_24h=1000,
                    open_interest=1000,
                    last_update_ts=time.time(),
                )
            },
            economics={
                "KXRECES": MacroMarketState(
                    ticker="KXRECES",
                    category=MacroCategory.ECONOMICS,
                    title="Recession",
                    yes_prob=0.7,  # High recession probability
                    yes_prob_24h_ago=0.7,
                    yes_prob_7d_ago=0.7,
                    spread_cents=2,
                    volume_24h=1000,
                    open_interest=1000,
                    last_update_ts=time.time(),
                )
            },
            event_risk_score=0.3,
        )
        
        regime = overlay._classify_regime(state)
        assert regime == MacroRegime.RISK_OFF
    
    def test_event_risk_classification(self):
        """Test high event risk regime."""
        overlay = KalshiMacroOverlay()
        
        # Uncertain election outcome = event risk
        state = MacroState(
            timestamp=time.time(),
            elections={
                "KXGEOP": MacroMarketState(
                    ticker="KXGEOP",
                    category=MacroCategory.ELECTIONS,
                    title="Election",
                    yes_prob=0.5,  # Exactly uncertain
                    yes_prob_24h_ago=0.5,
                    yes_prob_7d_ago=0.5,
                    spread_cents=2,
                    volume_24h=1000,
                    open_interest=1000,
                    last_update_ts=time.time(),
                )
            },
            event_risk_score=0.8,
        )
        
        regime = overlay._classify_regime(state)
        assert regime == MacroRegime.EVENT_RISK_HIGH


class TestCategoryPatterns:
    """Test ticker categorization patterns."""
    
    def test_all_patterns_exist(self):
        """Test that required category patterns exist."""
        required = {
            "KXFR": MacroCategory.FINANCIALS,
            "KXCPI": MacroCategory.FINANCIALS,
            "KXGEOP": MacroCategory.ELECTIONS,
            "KXWTI": MacroCategory.COMMODITIES,
            "KXGLD": MacroCategory.COMMODITIES,
            "KXGDP": MacroCategory.ECONOMICS,
            "KXRECES": MacroCategory.ECONOMICS,
            "KXTECH": MacroCategory.TECH_SCIENCE,
        }
        
        for prefix, expected_cat in required.items():
            assert prefix in MACRO_CATEGORY_PATTERNS
            assert MACRO_CATEGORY_PATTERNS[prefix] == expected_cat
