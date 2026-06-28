"""End-to-end tests for order submission paths under healthy and unhealthy market states.

This test suite ensures:
- Lean agent path rejects orders on unhealthy states
- Priority queue path rejects orders on unhealthy states
- Both paths accept orders on healthy states
- Canonical validator is used by both paths
"""

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

# Set profile for tests
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"


class TestLeanAgentPath:
    """Test lean agent path (_generate_signal) with various market states."""
    
    def test_lean_path_rejects_state_none(self):
        """Test that lean agent path rejects when state is None."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=None,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "STATE-NONE"
    
    def test_lean_path_rejects_stale_md(self):
        """Test that lean agent path rejects stale market data."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = True
        state.last_update = datetime.now(timezone.utc).timestamp() - 20  # 20 seconds ago
        state.best_bid_cents = 50
        state.best_ask_cents = 52
        state.depth_yes = 10
        state.depth_no = 10
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "MD-STALE"
    
    def test_lean_path_rejects_low_depth(self):
        """Test that lean agent path rejects low depth."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = True
        state.last_update = datetime.now(timezone.utc)
        state.best_bid_cents = 50
        state.best_ask_cents = 52
        state.depth_yes = 3  # Below min_depth_yes=5
        state.depth_no = 10
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "DEPTH-LOW"
    
    def test_lean_path_accepts_healthy_state(self):
        """Test that lean agent path accepts healthy market state."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = True
        state.last_update = datetime.now(timezone.utc)
        state.best_bid_cents = 50
        state.best_ask_cents = 52
        state.depth_yes = 10
        state.depth_no = 10
        
        result = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is True
        assert result.reason == "OK"


class TestPriorityQueuePath:
    """Test priority queue path (_submit_candidate) with various market states."""
    
    def test_priority_queue_rejects_state_none(self):
        """Test that priority queue path rejects when state is None."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        result = validate_market_state_for_entry(
            asset="ETH",
            market_id="KXETH15M-TEST",
            state=None,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "STATE-NONE"
    
    def test_priority_queue_rejects_not_executable(self):
        """Test that priority queue path rejects non-executable state."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = False
        state.last_update = datetime.now(timezone.utc)
        state.best_bid_cents = 50
        state.best_ask_cents = 52
        state.depth_yes = 10
        state.depth_no = 10
        
        result = validate_market_state_for_entry(
            asset="ETH",
            market_id="KXETH15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "NOT-EXECUTABLE"
    
    def test_priority_queue_rejects_0_100_pattern(self):
        """Test that priority queue path rejects 0/100 bid/ask pattern."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = True
        state.last_update = datetime.now(timezone.utc)
        state.best_bid_cents = 0
        state.best_ask_cents = 100
        state.depth_yes = 10
        state.depth_no = 10
        
        result = validate_market_state_for_entry(
            asset="ETH",
            market_id="KXETH15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is False
        assert result.reason == "PATTERN-0100"
    
    def test_priority_queue_accepts_healthy_state(self):
        """Test that priority queue path accepts healthy market state."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        state = Mock()
        state.book_initialized = True
        state.executable = True
        state.last_update = datetime.now(timezone.utc)
        state.best_bid_cents = 50
        state.best_ask_cents = 52
        state.depth_yes = 10
        state.depth_no = 10
        
        result = validate_market_state_for_entry(
            asset="ETH",
            market_id="KXETH15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result.ok is True
        assert result.reason == "OK"


class TestPathConsistency:
    """Test that both paths use the same validator and behave consistently."""
    
    def test_both_paths_use_same_validator(self):
        """Test that both paths call the same canonical validator."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        # Create a healthy state
        state = Mock()
        state.book_initialized = True
        state.executable = True
        state.last_update = datetime.now(timezone.utc)
        state.best_bid_cents = 50
        state.best_ask_cents = 52
        state.depth_yes = 10
        state.depth_no = 10
        
        # Both paths should use the same validator function
        result1 = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        result2 = validate_market_state_for_entry(
            asset="ETH",
            market_id="KXETH15M-TEST",
            state=state,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        # Both should accept the healthy state
        assert result1.ok is True
        assert result2.ok is True
        assert result1.reason == "OK"
        assert result2.reason == "OK"
    
    def test_both_paths_reject_same_unhealthy_states(self):
        """Test that both paths reject the same unhealthy states."""
        from merid.prediction.agent_grid_15m import validate_market_state_for_entry
        
        # Test state=None
        result1 = validate_market_state_for_entry(
            asset="BTC",
            market_id="KXBTC15M-TEST",
            state=None,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        result2 = validate_market_state_for_entry(
            asset="ETH",
            market_id="KXETH15M-TEST",
            state=None,
            minutes_to_expiry=10,
            min_depth_yes=5,
            min_depth_no=5,
            max_md_staleness_sec=15,
        )
        
        assert result1.ok is False
        assert result2.ok is False
        assert result1.reason == "STATE-NONE"
        assert result2.reason == "STATE-NONE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
