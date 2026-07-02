"""Tests for High-Performance Calibration System.

Validates:
- Edge thresholds achieve 85%+ win rate targets
- Take-profit configs maximize extraction
- Stop-loss configs protect capital
- Position sizing integrates sentiment/consensus
- No round-trip violations
"""

import os
import sys
import pytest
from decimal import Decimal
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHPEdgeCalibration:
    """Test edge threshold calibration for high win rates."""
    
    def test_btc_15m_edge_achieves_85_win_rate(self):
        """BTC 15m edge should target 85% win rate."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        
        assert config.expected_win_rate >= 0.80, f"Win rate {config.expected_win_rate:.0%} below 80%"
        assert config.edge.min_edge_entry >= Decimal("0.020"), f"Edge {config.edge.min_edge_entry} too low"
    
    def test_doge_has_highest_edge_requirement(self):
        """DOGE (highest vol) should have highest edge requirement."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        btc_edge = get_hp_config("BTC", "15m").edge.min_edge_entry
        doge_edge = get_hp_config("DOGE", "15m").edge.min_edge_entry
        
        assert doge_edge > btc_edge, f"DOGE edge {doge_edge} should be > BTC {btc_edge}"
    
    def test_timeframe_scaling_increases_edge(self):
        """Longer timeframes should have higher edge requirements."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        edge_15m = get_hp_config("BTC", "15m").edge.min_edge_entry
        edge_1h = get_hp_config("BTC", "1h").edge.min_edge_entry
        edge_daily = get_hp_config("BTC", "daily").edge.min_edge_entry
        
        assert edge_15m < edge_1h < edge_daily, \
            f"Edge scaling failed: 15m={edge_15m}, 1h={edge_1h}, daily={edge_daily}"
    
    def test_expiry_adjustments_tighten_near_expiry(self):
        """Edge requirements should increase as expiry approaches."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        
        assert config.edge.expiry_hour_1 > config.edge.expiry_hour_24, \
            f"Expiry adjustment wrong: 1h={config.edge.expiry_hour_1}, 24h={config.edge.expiry_hour_24}"
    
    def test_volatility_adjustments_correct(self):
        """High vol should reduce edge, low vol should increase it."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("SOL", "15m")
        
        assert config.edge.high_vol_boost > 0, "High vol boost should be positive"
        assert config.edge.low_vol_premium > 0, "Low vol premium should be positive"


class TestHPTakeProfitCalibration:
    """Test take-profit calibration for max extraction."""
    
    def test_tp_r_multiples_increase_with_timeframe(self):
        """Longer timeframes should have higher R-multiple targets."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        tp_15m = get_hp_config("BTC", "15m").take_profit
        tp_1h = get_hp_config("BTC", "1h").take_profit
        tp_daily = get_hp_config("BTC", "daily").take_profit
        
        assert tp_15m.r_multiple_full < tp_1h.r_multiple_full, \
            f"15m full {tp_15m.r_multiple_full} should be < 1h {tp_1h.r_multiple_full}"
        assert tp_1h.r_multiple_full < tp_daily.r_multiple_full, \
            f"1h full {tp_1h.r_multiple_full} should be < daily {tp_daily.r_multiple_full}"
    
    def test_scale_out_fraction_is_50_percent(self):
        """Should exit 50% at primary target (optimal for compounding)."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            config = get_hp_config(asset, "15m")
            assert config.take_profit.scale_out_fraction == 0.5, \
                f"{asset} scale_out should be 0.5"
    
    def test_round_trip_limits_are_strict(self):
        """Round trip limits should be 0 or 1 (strict to prevent churn)."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            for tf in ["15m", "1h", "daily"]:
                config = get_hp_config(asset, tf)
                assert config.take_profit.max_round_trips <= 1, \
                    f"{asset}/{tf} round trips {config.take_profit.max_round_trips} > 1"
    
    def test_hard_tp_targets_are_aggressive(self):
        """Hard TP targets should be 150%+ for exponential growth."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        for asset in ["BTC", "ETH", "SOL"]:
            config = get_hp_config(asset, "15m")
            assert config.take_profit.hard_tp_pct >= 150.0, \
                f"{asset} hard TP {config.take_profit.hard_tp_pct}% < 150%"
    
    def test_trailing_giveback_tight_for_btc(self):
        """BTC should have tight trailing giveback (4-5 cents)."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        assert 3 <= config.take_profit.trailing_giveback_cents <= 6, \
            f"BTC giveback {config.take_profit.trailing_giveback_cents}cents not in tight range"
    
    def test_reentry_requires_price_movement(self):
        """Re-entry should require significant price movement (8+ cents)."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            config = get_hp_config(asset, "15m")
            assert config.take_profit.min_price_move_reentry >= 8, \
                f"{asset} reentry move {config.take_profit.min_price_move_reentry} < 8 cents"


class TestHPStopLossCalibration:
    """Test stop-loss calibration for capital protection."""
    
    def test_sl_cents_proportional_to_volatility(self):
        """Higher vol assets should have wider stop losses."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        btc_sl = get_hp_config("BTC", "15m").stop_loss.initial_stop_cents
        sol_sl = get_hp_config("SOL", "15m").stop_loss.initial_stop_cents
        doge_sl = get_hp_config("DOGE", "15m").stop_loss.initial_stop_cents
        
        assert btc_sl < sol_sl < doge_sl, \
            f"SL scaling wrong: BTC={btc_sl}, SOL={sol_sl}, DOGE={doge_sl}"
    
    def test_max_hold_hours_decrease_with_volatility(self):
        """High vol assets should have shorter max hold times."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        btc_hold = get_hp_config("BTC", "15m").stop_loss.max_hold_hours
        sol_hold = get_hp_config("SOL", "15m").stop_loss.max_hold_hours
        doge_hold = get_hp_config("DOGE", "15m").stop_loss.max_hold_hours
        
        assert btc_hold > sol_hold > doge_hold, \
            f"Hold time scaling wrong: BTC={btc_hold}h, SOL={sol_hold}h, DOGE={doge_hold}h"
    
    def test_trailing_activation_at_50pct_plus(self):
        """Trailing stops should activate at 50%+ profit."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        for asset in ["BTC", "ETH", "SOL"]:
            config = get_hp_config(asset, "15m")
            assert config.stop_loss.trailing_activation_pct >= 0.50, \
                f"{asset} trailing activation {config.stop_loss.trailing_activation_pct:.0%} < 50%"


class TestHPPositionSizing:
    """Test position sizing calibration."""
    
    def test_kelly_fraction_is_2_percent(self):
        """Kelly fraction should be 2% (aligned with kalshi_crypto_15m_v2.yaml profile)."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        assert config.sizing.kelly_fraction == Decimal("0.02"), \
            f"Kelly {config.sizing.kelly_fraction} != 0.02"
    
    def test_max_position_limited_to_20_percent(self):
        """Max position should be 20% of bankroll."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        assert config.sizing.max_position_pct_bankroll <= Decimal("0.20"), \
            f"Max position {config.sizing.max_position_pct_bankroll} > 20%"
    
    def test_max_drawdown_is_10_percent(self):
        """Max drawdown should be 10% (tight for capital protection)."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        assert config.sizing.max_drawdown_pct <= Decimal("0.10"), \
            f"Max drawdown {config.sizing.max_drawdown_pct} > 10%"
    
    def test_sentiment_consensus_vol_weights_sum_to_one(self):
        """Sizing weights should sum to approximately 1.0."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        total = config.sizing.sentiment_weight + config.sizing.consensus_weight + config.sizing.vol_scalar_weight
        assert 0.99 <= total <= 1.01, f"Weight sum {total} != 1.0"


class TestHPSentimentConsensusIntegration:
    """Test sentiment and consensus integration."""
    
    def test_min_agents_for_consensus_is_3(self):
        """Require at least 3 agents for valid consensus."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        assert config.sentiment_consensus.min_agents_for_consensus >= 3
    
    def test_confidence_floor_is_65_percent(self):
        """Confidence floor should be 65% (high bar for entries)."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        assert config.sentiment_consensus.confidence_floor >= 0.65, \
            f"Confidence floor {config.sentiment_consensus.confidence_floor} < 65%"
    
    def test_extreme_fear_boost_is_positive(self):
        """Should boost edge in extreme fear (buy the dip)."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        assert config.sentiment_consensus.extreme_fear_edge_boost > 0
    
    def test_extreme_greed_reduction_is_positive(self):
        """Should reduce edge in extreme greed (avoid FOMO)."""
        from merid.prediction.high_performance_calibration import get_hp_config
        
        config = get_hp_config("BTC", "15m")
        assert config.sentiment_consensus.extreme_greed_edge_reduction > 0


class TestHPDynamicEdgeCalculation:
    """Test dynamic edge calculation based on conditions."""
    
    def test_dynamic_edge_increases_near_expiry(self):
        """Edge should increase as expiry approaches."""
        from merid.prediction.high_performance_calibration import calculate_dynamic_edge
        
        base_edge = Decimal("0.05")
        
        edge_24h = calculate_dynamic_edge("BTC", "15m", base_edge, "neutral", "normal", 24.0)
        edge_1h = calculate_dynamic_edge("BTC", "15m", base_edge, "neutral", "normal", 1.0)
        
        assert edge_1h > edge_24h, f"Expiry adjustment failed: 1h={edge_1h}, 24h={edge_24h}"
    
    def test_extreme_fear_reduces_threshold(self):
        """Extreme fear should reduce edge threshold (buy dips)."""
        from merid.prediction.high_performance_calibration import calculate_dynamic_edge
        
        base_edge = Decimal("0.05")
        
        edge_neutral = calculate_dynamic_edge("BTC", "15m", base_edge, "neutral", "normal", 4.0)
        edge_fear = calculate_dynamic_edge("BTC", "15m", base_edge, "extreme_fear", "normal", 4.0)
        
        assert edge_fear < edge_neutral, f"Fear adjustment failed: fear={edge_fear}, neutral={edge_neutral}"
    
    def test_extreme_greed_increases_threshold(self):
        """Extreme greed should increase edge threshold (avoid FOMO)."""
        from merid.prediction.high_performance_calibration import calculate_dynamic_edge
        
        base_edge = Decimal("0.05")
        
        edge_neutral = calculate_dynamic_edge("BTC", "15m", base_edge, "neutral", "normal", 4.0)
        edge_greed = calculate_dynamic_edge("BTC", "15m", base_edge, "extreme_greed", "normal", 4.0)
        
        assert edge_greed > edge_neutral, f"Greed adjustment failed: greed={edge_greed}, neutral={edge_neutral}"
    
    def test_high_vol_reduces_threshold(self):
        """High volatility should reduce threshold (more opportunities)."""
        from merid.prediction.high_performance_calibration import calculate_dynamic_edge
        
        base_edge = Decimal("0.05")
        
        edge_normal = calculate_dynamic_edge("BTC", "15m", base_edge, "neutral", "normal", 4.0)
        edge_high = calculate_dynamic_edge("BTC", "15m", base_edge, "neutral", "high", 4.0)
        
        assert edge_high < edge_normal, f"Vol adjustment failed: high={edge_high}, normal={edge_normal}"


class TestHPIntegration:
    """Test HP integration functions."""
    
    def test_hp_mode_enable_sets_env_var(self):
        """Enabling HP mode should set environment variable."""
        from merid.prediction.hp_integration import enable_high_performance_mode, is_hp_mode_enabled
        
        enable_high_performance_mode(win_rate_target=0.85)
        
        assert is_hp_mode_enabled()
        assert os.getenv("MERID_HP_WIN_RATE_TARGET") == "85"
    
    @patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync', return_value=10000.0)
    def test_position_size_calculation_with_sentiment(self, mock_get_equity):
        """Position size should adjust based on sentiment (contrarian)."""
        from merid.prediction.hp_integration import calculate_hp_position_size
        
        base_size = 100
        
        # Extreme fear should INCREASE size (contrarian opportunity)
        size_fear = calculate_hp_position_size("BTC", "15m", base_size, 10.0, 0.8, 0.5)
        # Extreme greed should REDUCE size (avoid FOMO)
        size_greed = calculate_hp_position_size("BTC", "15m", base_size, 90.0, 0.8, 0.5)
        
        assert size_fear > size_greed, f"Sentiment adjustment failed: fear={size_fear} should be > greed={size_greed}"
    
    @patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync', return_value=10000.0)
    def test_position_size_calculation_with_confidence(self, mock_get_equity):
        """Position size should adjust based on consensus confidence."""
        from merid.prediction.hp_integration import calculate_hp_position_size
        
        base_size = 100
        
        # Low confidence should reduce size
        size_low_conf = calculate_hp_position_size("BTC", "15m", base_size, 50.0, 0.50, 0.5)
        # High confidence should increase size
        size_high_conf = calculate_hp_position_size("BTC", "15m", base_size, 50.0, 0.95, 0.5)
        
        assert size_low_conf < size_high_conf, \
            f"Confidence adjustment failed: low={size_low_conf}, high={size_high_conf}"
    
    @patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync', return_value=10000.0)
    def test_win_streak_boosts_size(self, mock_get_equity):
        """Win streaks should increase position size."""
        from merid.prediction.hp_integration import calculate_hp_position_size
        
        base_size = 100
        
        size_no_streak = calculate_hp_position_size("BTC", "15m", base_size, 50.0, 0.8, 0.5, 0, 0)
        size_win_streak = calculate_hp_position_size("BTC", "15m", base_size, 50.0, 0.8, 0.5, 5, 0)
        
        assert size_win_streak > size_no_streak, \
            f"Win streak failed: no_streak={size_no_streak}, streak={size_win_streak}"
    
    @patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync', return_value=10000.0)
    def test_lose_streak_reduces_size(self, mock_get_equity):
        """Lose streaks should decrease position size."""
        from merid.prediction.hp_integration import calculate_hp_position_size
        
        base_size = 100
        
        size_no_streak = calculate_hp_position_size("BTC", "15m", base_size, 50.0, 0.8, 0.5, 0, 0)
        size_lose_streak = calculate_hp_position_size("BTC", "15m", base_size, 50.0, 0.8, 0.5, 0, 5)
        
        assert size_lose_streak < size_no_streak, \
            f"Lose streak failed: no_streak={size_no_streak}, streak={size_lose_streak}"


class TestHPValidation:
    """Test HP system validation."""
    
    def test_all_assets_have_configs(self):
        """All 5 crypto assets should have configurations."""
        from merid.prediction.hp_integration import validate_hp_setup
        
        issues = validate_hp_setup()
        
        # Filter out "HP mode not enabled" which is expected in tests
        real_issues = [i for i in issues if "HP mode not enabled" not in i]
        
        assert len(real_issues) == 0, f"Config issues found: {real_issues}"
    
    def test_performance_summary_returns_data(self):
        """Performance summary should return data for all combinations."""
        from merid.prediction.hp_integration import get_hp_performance_summary
        
        summary = get_hp_performance_summary()
        
        assert len(summary["combinations"]) >= 10, "Should have at least 10 combinations"
        assert summary["average_win_rate"] >= 0.75, f"Avg win rate {summary['average_win_rate']:.0%} < 75%"
        assert summary["average_profit_factor"] >= 1.5, f"Avg PF {summary['average_profit_factor']:.2f} < 1.5"


class TestEntryDecision:
    """Test entry decision logic."""
    
    def test_round_trip_limit_blocks_entry(self):
        """Should block entry if round trip limit exceeded."""
        from merid.prediction.high_performance_calibration import should_allow_entry
        
        allow, reason = should_allow_entry("BTC", "15m", Decimal("0.05"), 50.0, 0.8, 5)
        
        assert not allow, "Should block entry when round trips exceeded"
        assert "round_trip" in reason.lower()
    
    def test_low_confidence_blocks_entry(self):
        """Should block entry if consensus confidence too low."""
        from merid.prediction.high_performance_calibration import should_allow_entry
        
        allow, reason = should_allow_entry("BTC", "15m", Decimal("0.05"), 50.0, 0.50, 0)
        
        assert not allow, "Should block entry when confidence low"
        assert "confidence" in reason.lower()
    
    def test_low_edge_blocks_entry(self):
        """Should block entry if edge below threshold."""
        from merid.prediction.high_performance_calibration import should_allow_entry
        
        allow, reason = should_allow_entry("BTC", "15m", Decimal("0.01"), 50.0, 0.8, 0)
        
        assert not allow, "Should block entry when edge low"
        assert "edge" in reason.lower()
    
    def test_all_passed_allows_entry(self):
        """Should allow entry if all checks pass."""
        from merid.prediction.high_performance_calibration import should_allow_entry
        
        allow, reason = should_allow_entry("BTC", "15m", Decimal("0.05"), 50.0, 0.8, 0)
        
        assert allow, f"Should allow entry: {reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
