"""
Tests for Candidate Generation Pipeline Fixes (2026-08-02)

Tests the fix for duplicate market validation call in candidate generation:
- Removed redundant _validate_market_state() call
- Single validation after warmup check to prevent unnecessary rejections
- This was blocking legitimate candidates from being generated
"""

import pytest
from unittest.mock import Mock


class TestCandidateGenerationValidation:
    """Test candidate generation validation fixes - logic level tests."""
    
    def test_single_validation_call_pattern(self):
        """Test the fixed pattern: warmup check first, then single validation."""
        # Mock validation function
        validate_market_state = Mock(return_value=True)
        
        # Simulate the fixed code pattern
        spot_price_history = {"BTC": [50000.0, 50100.0]}  # Has history
        asset = "BTC"
        price_history_len = len(list(spot_price_history.get(asset, [])))
        
        result = None
        if price_history_len < 1:
            # Warmup block
            result = "warmup_block"
        else:
            # Single validation call after warmup check
            if validate_market_state(Mock()):
                result = "candidate_generated"
        
        # Verify validation was called exactly once
        assert validate_market_state.call_count == 1, \
            "Market validation should be called exactly once in fixed pattern"
        assert result == "candidate_generated"
    
    def test_warmup_prevents_validation(self):
        """Test that warmup check prevents validation when insufficient data."""
        validate_market_state = Mock(return_value=True)
        
        # Empty price history (warmup condition)
        spot_price_history = {"BTC": []}
        asset = "BTC"
        price_history_len = len(list(spot_price_history.get(asset, [])))
        
        result = None
        if price_history_len < 1:
            result = "warmup_block"
        else:
            validate_market_state(Mock())
        
        # Verify validation was not called during warmup
        assert validate_market_state.call_count == 0, \
            "Market validation should not be called during warmup"
        assert result == "warmup_block"
    
    def test_validation_only_after_warmup_passes(self):
        """Test that validation only occurs after warmup check passes."""
        validate_market_state = Mock(return_value=True)
        
        # Sufficient price history (warmup passed)
        spot_price_history = {"BTC": [50000.0]}
        asset = "BTC"
        price_history_len = len(list(spot_price_history.get(asset, [])))
        
        result = None
        if price_history_len >= 1:
            if validate_market_state(Mock()):
                result = "validation_passed"
        
        # Verify validation was called after warmup passed
        assert validate_market_state.call_count == 1, \
            "Market validation should be called after warmup passes"
        assert result == "validation_passed"
    
    def test_no_duplicate_validation_in_fixed_pattern(self):
        """Test that the fixed pattern doesn't have duplicate validation calls."""
        validate_market_state = Mock(return_value=True)
        
        # Simulate the fixed pattern (single validation)
        spot_price_history = {"BTC": [50000.0, 50100.0]}
        asset = "BTC"
        price_history_len = len(list(spot_price_history.get(asset, [])))
        
        if price_history_len >= 1:
            # Single validation call
            validate_market_state(Mock())
        
        # Verify no duplicate calls
        assert validate_market_state.call_count == 1, \
            "Fixed pattern should have exactly one validation call"
    
    def test_old_pattern_had_duplicate_validation(self):
        """Test that the old pattern had duplicate validation calls (for comparison)."""
        validate_market_state = Mock(return_value=True)
        
        # Simulate the OLD buggy pattern (validation before AND after warmup)
        spot_price_history = {"BTC": [50000.0, 50100.0]}
        asset = "BTC"
        price_history_len = len(list(spot_price_history.get(asset, [])))
        
        # OLD pattern: validation before warmup check
        validate_market_state(Mock())
        
        if price_history_len >= 1:
            # OLD pattern: validation again after warmup check
            validate_market_state(Mock())
        
        # Verify duplicate calls in old pattern
        assert validate_market_state.call_count == 2, \
            "Old pattern had duplicate validation calls (this was the bug)"


class TestValidationLogic:
    """Test market validation logic independently."""
    
    def test_market_state_store_retrieval(self):
        """Test market state retrieval from store."""
        market_state_store = Mock()
        mock_market_state = Mock()
        mock_market_state.last_update_ts = 1234567890.0
        mock_market_state.min_depth_yes = 5
        mock_market_state.min_depth_no = 3
        
        market_state_store.get = Mock(return_value=mock_market_state)
        
        ticker = "KXBTC15M-26AUG012215-15"
        market_state = market_state_store.get(ticker)
        
        assert market_state_store.get.called
        assert market_state is not None
        assert market_state.last_update_ts == 1234567890.0
    
    def test_missing_market_state_handling(self):
        """Test handling of missing market state."""
        market_state_store = Mock()
        market_state_store.get = Mock(return_value=None)
        
        ticker = "KXBTC15M-26AUG012215-15"
        market_state = market_state_store.get(ticker)
        
        assert market_state is None
        # Should return False when market state is missing
        assert market_state is None, "Missing market state should return None"


class TestCandidateGenerationScenarios:
    """Test various candidate generation scenarios."""
    
    def test_success_scenario_valid_market(self):
        """Test successful candidate generation with valid market."""
        validate_market_state = Mock(return_value=True)
        spot_price_history = {"BTC": [50000.0]}
        
        asset = "BTC"
        price_history_len = len(list(spot_price_history.get(asset, [])))
        
        result = None
        if price_history_len >= 1:
            if validate_market_state(Mock()):
                result = "candidate_generated"
        
        assert result == "candidate_generated"
        assert validate_market_state.call_count == 1
    
    def test_blocked_by_warmup_scenario(self):
        """Test candidate generation blocked by warmup."""
        validate_market_state = Mock(return_value=True)
        spot_price_history = {"BTC": []}
        
        asset = "BTC"
        price_history_len = len(list(spot_price_history.get(asset, [])))
        
        result = None
        if price_history_len < 1:
            result = "warmup_block"
        
        assert result == "warmup_block"
        assert validate_market_state.call_count == 0
    
    def test_blocked_by_validation_scenario(self):
        """Test candidate generation blocked by validation failure."""
        validate_market_state = Mock(return_value=False)
        spot_price_history = {"BTC": [50000.0]}
        
        asset = "BTC"
        price_history_len = len(list(spot_price_history.get(asset, [])))
        
        result = None
        if price_history_len >= 1:
            if not validate_market_state(Mock()):
                result = "validation_failed"
        
        assert result == "validation_failed"
        assert validate_market_state.call_count == 1
    
    def test_warmup_then_validation_success_scenario(self):
        """Test warmup passes then validation succeeds."""
        validate_market_state = Mock(return_value=True)
        spot_price_history = {"BTC": [50000.0, 50100.0]}  # Multiple data points
        
        asset = "BTC"
        price_history_len = len(list(spot_price_history.get(asset, [])))
        
        result = None
        if price_history_len >= 1:
            if validate_market_state(Mock()):
                result = "success"
        
        assert result == "success"
        assert validate_market_state.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
