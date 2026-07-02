"""
Tests for 2026 profitability optimizations

Tests for new 2026 best practice features:
- Confidence threshold gate (0.75)
- Per-asset min_decision_minute
- Multi-timeframe trend filter (1h alignment)
- Walk-forward optimization framework
"""

import pytest
from datetime import datetime, timedelta
from merid.prediction.walk_forward_optimizer import (
    WalkForwardOptimizer,
    HyperparameterCombo,
    OptimizationMode,
)


class TestConfidenceThreshold:
    """Test confidence threshold gate configuration."""
    
    def test_confidence_threshold_in_profile(self):
        """Test that confidence threshold is configured in profile."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check confidence section exists
        assert "confidence" in profile
        assert "min_confidence_threshold" in profile["confidence"]
        
        # Check value is 0.75 (industry standard)
        threshold = profile["confidence"]["min_confidence_threshold"]
        assert threshold == 0.75, f"Expected 0.75, got {threshold}"
    
    def test_confidence_threshold_is_float(self):
        """Test that confidence threshold is a float."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        threshold = profile["confidence"]["min_confidence_threshold"]
        assert isinstance(threshold, float), f"Expected float, got {type(threshold)}"


class TestMinDecisionMinute:
    """Test per-asset min_decision_minute configuration."""
    
    def test_min_decision_minute_in_profile(self):
        """Test that min_decision_minute is configured in profile."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check min_decision_minute section exists
        assert "min_decision_minute" in profile
        
        # Check all 5 assets are present
        mdm = profile["min_decision_minute"]
        assert "BTC" in mdm
        assert "ETH" in mdm
        assert "SOL" in mdm
        assert "XRP" in mdm
        assert "DOGE" in mdm
    
    def test_min_decision_minute_values(self):
        """Test that min_decision_minute values are reasonable."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        mdm = profile["min_decision_minute"]
        
        # BTC/ETH should have lower values (deeper markets)
        assert mdm["BTC"] >= 2, f"BTC min_decision_minute too low: {mdm['BTC']}"
        assert mdm["ETH"] >= 2, f"ETH min_decision_minute too low: {mdm['ETH']}"
        
        # SOL/XRP should have higher values (thinner books)
        assert mdm["SOL"] >= 3, f"SOL min_decision_minute too low: {mdm['SOL']}"
        assert mdm["XRP"] >= 3, f"XRP min_decision_minute too low: {mdm['XRP']}"
        
        # DOGE should have highest value (thinnest book)
        assert mdm["DOGE"] >= 4, f"DOGE min_decision_minute too low: {mdm['DOGE']}"
        
        # All values should be <= 15 (max window size)
        for asset, value in mdm.items():
            assert value <= 15, f"{asset} min_decision_minute too high: {value}"


class TestMultiTimeframeFilter:
    """Test multi-timeframe trend filter configuration."""
    
    def test_multi_timeframe_filter_in_profile(self):
        """Test that multi_timeframe_filter is configured in profile."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check multi_timeframe_filter section exists
        assert "multi_timeframe_filter" in profile
        
        mtf = profile["multi_timeframe_filter"]
        
        # Check required fields
        assert "enabled" in mtf
        assert "higher_timeframe" in mtf
        assert "alignment_mode" in mtf
        assert "neutral_size_multiplier" in mtf
    
    def test_multi_timeframe_filter_values(self):
        """Test that multi_timeframe_filter values are correct."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        mtf = profile["multi_timeframe_filter"]
        
        # Should be enabled
        assert mtf["enabled"] is True, "multi_timeframe_filter should be enabled"
        
        # Higher timeframe should be 1h
        assert mtf["higher_timeframe"] == "1h", f"Expected 1h, got {mtf['higher_timeframe']}"
        
        # Alignment mode should be strict or relaxed
        assert mtf["alignment_mode"] in ["strict", "relaxed"], \
            f"Invalid alignment_mode: {mtf['alignment_mode']}"
        
        # Neutral size multiplier should be between 0 and 1
        assert 0 < mtf["neutral_size_multiplier"] <= 1, \
            f"Invalid neutral_size_multiplier: {mtf['neutral_size_multiplier']}"


class TestStrategyAgentRRRatio:
    """Test strategy agent minimum reward:risk ratio."""
    
    def test_min_rr_ratio_increased(self):
        """Test that MIN_REWARD_RISK_RATIO is 2.5."""
        # Read the file directly to check the constant value
        with open("agents/core/strategy_agent.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        assert "MIN_REWARD_RISK_RATIO = 2.5" in content, \
            "MIN_REWARD_RISK_RATIO should be 2.5 in strategy_agent.py"
    
    def test_min_rr_ratio_is_float(self):
        """Test that MIN_REWARD_RISK_RATIO is a float."""
        # Read the file directly to check the constant value
        with open("agents/core/strategy_agent.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check that it's defined as a float (2.5 not 2)
        assert "MIN_REWARD_RISK_RATIO = 2.5" in content, \
            "MIN_REWARD_RISK_RATIO should be defined as 2.5 (float)"


class TestWalkForwardOptimizer:
    """Test walk-forward optimization framework."""
    
    def test_optimizer_initialization(self):
        """Test that optimizer can be initialized."""
        optimizer = WalkForwardOptimizer(
            n_folds=4,
            fold_duration_days=7,
            optimization_mode=OptimizationMode.PNL_BASED,
        )
        
        assert optimizer._n_folds == 4
        assert optimizer._fold_duration_days == 7
        assert optimizer._optimization_mode == OptimizationMode.PNL_BASED
    
    def test_time_fold_generation(self):
        """Test that time folds are generated correctly."""
        optimizer = WalkForwardOptimizer(n_folds=4, fold_duration_days=7)
        
        # Use a longer date range to accommodate 4 folds
        # Each fold needs 2 * 7 = 14 days (train + test)
        # 4 folds need 4 * 14 = 56 days minimum
        start_date = datetime(2026, 1, 1)
        end_date = datetime(2026, 3, 1)  # 59 days, enough for 4 folds
        
        folds = optimizer.generate_time_folds(start_date, end_date)
        
        # Should generate 4 folds
        assert len(folds) == 4, f"Expected 4 folds, got {len(folds)}"
        
        # Check fold structure
        for train_start, train_end, test_start, test_end in folds:
            assert isinstance(train_start, datetime)
            assert isinstance(train_end, datetime)
            assert isinstance(test_start, datetime)
            assert isinstance(test_end, datetime)
            
            # Test should start after train ends
            assert test_start >= train_end
            
            # Duration should be 7 days
            assert (train_end - train_start).days == 7
            assert (test_end - test_start).days == 7
    
    def test_hyperparameter_combo_creation(self):
        """Test that hyperparameter combos can be created."""
        combo = HyperparameterCombo(
            combo_id="test_combo_1",
            params={"threshold": 0.75, "min_dm": 2},
            description="Test combo",
        )
        
        assert combo.combo_id == "test_combo_1"
        assert combo.params["threshold"] == 0.75
        assert combo.params["min_dm"] == 2
    
    def test_optimization_mode_enum(self):
        """Test that optimization mode enum works."""
        assert OptimizationMode.PNL_BASED.value == "pnl_based"
        assert OptimizationMode.SHARPE_BASED.value == "sharpe_based"
        assert OptimizationMode.WINRATE_BASED.value == "winrate_based"
    
    def test_optimizer_results_summary(self):
        """Test that optimizer can generate results summary."""
        optimizer = WalkForwardOptimizer()
        
        # Empty results
        summary = optimizer.get_results_summary()
        assert summary["total_combos"] == 0
        assert summary["results"] == []
        
        # Add a mock result
        from merid.prediction.walk_forward_optimizer import OptimizationResult, FoldResult
        
        result = OptimizationResult(
            combo_id="test_combo",
            params={"threshold": 0.75},
            avg_oos_pnl=100.0,
            avg_oos_sharpe=1.5,
            avg_oos_win_rate=0.6,
            fold_results=[],
        )
        optimizer._results.append(result)
        
        summary = optimizer.get_results_summary()
        assert summary["total_combos"] == 1
        assert len(summary["results"]) == 1
        assert summary["results"][0]["combo_id"] == "test_combo"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
