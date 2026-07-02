"""
Tests for MD Age Computation Helpers

Tests the centralized MD age computation with proper timebase handling
and status classification. Covers edge cases and timebase consistency.
"""

import time
import pytest
from unittest.mock import Mock

from merid.core.md_age_helpers import compute_md_age, MDAgeResult, validate_md_timebase_consistency


class TestMDAgeComputation:
    """Test MD age computation with various states and edge cases."""
    
    def test_no_state(self):
        """Test when no market state is available."""
        result = compute_md_age(None)
        
        assert result.status == "no_data"
        assert result.reason == "NO_STATE"
        assert result.age_s == -1.0
        assert result.is_stale() is True
        assert result.has_data() is False
    
    def test_no_timestamp_field(self):
        """Test when state exists but has no timestamp field."""
        state = Mock(spec=[])  # Mock with no attributes
        
        result = compute_md_age(state)
        
        assert result.status == "no_data"
        assert result.reason == "NO_TIMESTAMP_FIELD"
        assert result.age_s == -1.0
        assert result.is_stale() is True
        assert result.has_data() is False
    
    def test_never_updated(self):
        """Test when timestamp field exists but never set (zero)."""
        state = Mock()
        state.last_book_update_ts = 0.0
        
        result = compute_md_age(state)
        
        assert result.status == "no_data"
        assert result.reason == "NEVER_UPDATED"
        assert result.age_s == -1.0
        assert result.is_stale() is True
        assert result.has_data() is False
    
    def test_fresh_data(self):
        """Test fresh market data within stale threshold."""
        now = time.monotonic()
        state = Mock()
        state.last_book_update_ts = now - 10.0  # 10 seconds ago
        
        result = compute_md_age(state, now_mono=now)
        
        assert result.status == "fresh"
        assert result.reason == "FRESH"
        assert result.age_s == 10.0
        assert result.is_stale() is False
        assert result.has_data() is True
        assert result.is_fresh() is True
    
    def test_stale_data(self):
        """Test stale market data exceeding threshold."""
        now = time.monotonic()
        state = Mock()
        state.last_book_update_ts = now - 150.0  # 150 seconds ago
        
        result = compute_md_age(state, now_mono=now, stale_threshold=120.0)
        
        assert result.status == "stale"
        assert "AGE_150.0s > 120.0s" in result.reason
        assert result.age_s == 150.0
        assert result.is_stale() is True
        assert result.has_data() is True
        assert result.is_fresh() is False
    
    def test_negative_age_impossible(self):
        """Test impossible negative age (timebase mismatch)."""
        now = time.monotonic()
        state = Mock()
        state.last_book_update_ts = now + 100.0  # Future timestamp
        
        result = compute_md_age(state, now_mono=now)
        
        assert result.status == "impossible"
        assert "IMPOSSIBLE_AGE" in result.reason
        assert result.age_s >= 0  # Should be clamped
        assert result.is_stale() is True
        assert result.has_data() is True
    
    def test_too_large_age_impossible(self):
        """Test impossible large age (corrupted timestamp)."""
        now = time.monotonic()
        state = Mock()
        state.last_book_update_ts = now - 5000.0  # 5000 seconds ago
        
        result = compute_md_age(state, now_mono=now)
        
        assert result.status == "impossible"
        assert "IMPOSSIBLE_AGE" in result.reason
        assert result.age_s <= 3600.0  # Should be clamped to max
        assert result.is_stale() is True
        assert result.has_data() is True
    
    def test_custom_stale_threshold(self):
        """Test custom stale threshold."""
        now = time.monotonic()
        state = Mock()
        state.last_book_update_ts = now - 30.0  # 30 seconds ago
        
        # With default threshold (120s), should be fresh
        result = compute_md_age(state, now_mono=now)
        assert result.status == "fresh"
        
        # With custom threshold (20s), should be stale
        result = compute_md_age(state, now_mono=now, stale_threshold=20.0)
        assert result.status == "stale"
    
    def test_monotonic_timebase_consistency(self):
        """Test that both timestamps are monotonic and consistent."""
        now = time.monotonic()
        state = Mock()
        state.last_book_update_ts = now - 50.0
        
        result = compute_md_age(state, now_mono=now)
        
        assert validate_md_timebase_consistency(result) is True
        assert 0 <= result.now_mono < 1_000_000_000
        assert 0 <= result.last_update_mono < 1_000_000_000
    
    def test_timebase_validation_failures(self):
        """Test timebase validation with invalid inputs."""
        # Test with infinite values
        result = MDAgeResult(
            age_s=10.0,
            status="fresh",
            reason="FRESH",
            now_mono=float('inf'),
            last_update_mono=time.monotonic()
        )
        assert validate_md_timebase_consistency(result) is False
        
        # Test with non-numeric values
        result = MDAgeResult(
            age_s=10.0,
            status="fresh", 
            reason="FRESH",
            now_mono="not_a_number",
            last_update_mono=time.monotonic()
        )
        assert validate_md_timebase_consistency(result) is False
        
        # Test with Unix timestamp (too large for monotonic)
        result = MDAgeResult(
            age_s=10.0,
            status="fresh",
            reason="FRESH",
            now_mono=time.monotonic(),
            last_update_mono=1_750_000_000.0  # Unix timestamp
        )
        assert validate_md_timebase_consistency(result) is False


class TestMDAgeResultMethods:
    """Test MDAgeResult helper methods."""
    
    def test_is_fresh(self):
        """Test is_fresh() method."""
        result = MDAgeResult(10.0, "fresh", "FRESH", 100.0, 90.0)
        assert result.is_fresh() is True
        
        result = MDAgeResult(150.0, "stale", "STALE", 100.0, 90.0)
        assert result.is_fresh() is False
    
    def test_is_stale(self):
        """Test is_stale() method."""
        # Fresh data should not be stale
        result = MDAgeResult(10.0, "fresh", "FRESH", 100.0, 90.0)
        assert result.is_stale() is False
        
        # Stale data should be stale
        result = MDAgeResult(150.0, "stale", "STALE", 100.0, 90.0)
        assert result.is_stale() is True
        
        # Impossible age should be stale
        result = MDAgeResult(-10.0, "impossible", "IMPOSSIBLE", 100.0, 110.0)
        assert result.is_stale() is True
        
        # No data should be stale
        result = MDAgeResult(-1.0, "no_data", "NO_STATE", 100.0, 0.0)
        assert result.is_stale() is True
    
    def test_has_data(self):
        """Test has_data() method."""
        # Fresh data should have data
        result = MDAgeResult(10.0, "fresh", "FRESH", 100.0, 90.0)
        assert result.has_data() is True
        
        # Stale data should have data
        result = MDAgeResult(150.0, "stale", "STALE", 100.0, 90.0)
        assert result.has_data() is True
        
        # No data should not have data
        result = MDAgeResult(-1.0, "no_data", "NO_STATE", 100.0, 0.0)
        assert result.has_data() is False


if __name__ == "__main__":
    pytest.main([__file__])
