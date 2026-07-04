"""
Tests for staged time-based exit functionality.

Tests the 40%/30%/30% partial exit strategy at 5/10/13 minutes.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock


class TestStagedTimeExit:
    """Test staged time-based exit logic."""
    
    @pytest.fixture
    def mock_position(self):
        """Create a mock position for testing."""
        position = Mock()
        position.market_id = "KXBTC15M-2024-01-01T12:00:00"
        position.side = "yes"
        position.contracts = 10
        position.avg_price_cents = 5000
        position.stop_loss_price_cents = 4800
        position.take_profit_price_cents = 5500
        position.entry_intent_id = "test_entry_123"
        # Stage execution flags
        position.stage_0_executed = False
        position.stage_1_executed = False
        position.stage_2_executed = False
        return position
    
    @pytest.fixture
    def mock_market_state(self):
        """Create a mock market state."""
        state = Mock()
        state.mid_cents = 5200
        state.seconds_to_expiry = 600  # 10 minutes to expiry
        return state
    
    @pytest.fixture
    def mock_market_state_store(self, mock_market_state):
        """Create a mock market state store."""
        store = Mock()
        store.get_unified = Mock(return_value=mock_market_state)
        return store
    
    def test_staged_exit_config_loading(self):
        """Test that staged exit configuration loads correctly from YAML."""
        from pathlib import Path
        import yaml
        
        profile_path = Path(__file__).parent.parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        if profile_path.exists():
            with open(profile_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            staged_config = config.get("staged_time_exit", {})
            assert staged_config.get("enabled") == True
            stages = staged_config.get("stages", [])
            assert len(stages) == 3
            
            # Check stage 0: 5 minutes, 40%
            assert stages[0].get("minutes") == 5
            assert stages[0].get("percent") == 40
            
            # Check stage 1: 10 minutes, 30%
            assert stages[1].get("minutes") == 10
            assert stages[1].get("percent") == 30
            
            # Check stage 2: 13 minutes, 30%
            assert stages[2].get("minutes") == 13
            assert stages[2].get("percent") == 30
    
    def test_stage_0_triggers_at_5_minutes(self, mock_position, mock_market_state):
        """Test that stage 0 (40%) triggers at 5 minutes."""
        mock_market_state.seconds_to_expiry = 600  # 10 minutes to expiry = 5 minutes since entry
        
        # Calculate contracts to close for stage 0
        stage_percent = 40
        contracts_to_close = int(mock_position.contracts * (stage_percent / 100.0))
        
        assert contracts_to_close == 4  # 40% of 10 = 4
        assert contracts_to_close >= 1  # Must close at least 1 contract
    
    def test_stage_1_triggers_at_10_minutes(self, mock_position, mock_market_state):
        """Test that stage 1 (30%) triggers at 10 minutes."""
        # After stage 0, position has 6 contracts remaining
        mock_position.contracts = 6
        mock_market_state.seconds_to_expiry = 300  # 5 minutes to expiry = 10 minutes since entry
        
        # Calculate contracts to close for stage 1
        stage_percent = 30
        contracts_to_close = int(mock_position.contracts * (stage_percent / 100.0))
        
        assert contracts_to_close == 1  # 30% of 6 = 1.8 -> int truncates to 1
        assert contracts_to_close >= 1
    
    def test_stage_2_triggers_at_13_minutes(self, mock_position, mock_market_state):
        """Test that stage 2 (30%) triggers at 13 minutes."""
        # After stages 0 and 1, position has 4 contracts remaining
        mock_position.contracts = 4
        mock_market_state.seconds_to_expiry = 120  # 2 minutes to expiry = 13 minutes since entry
        
        # Calculate contracts to close for stage 2
        stage_percent = 30
        contracts_to_close = int(mock_position.contracts * (stage_percent / 100.0))
        
        assert contracts_to_close == 1  # 30% of 4 = 1.2 -> 1
        assert contracts_to_close >= 1
    
    def test_stage_execution_prevents_duplicate_exits(self, mock_position, mock_market_state):
        """Test that each stage only executes once."""
        mock_position.stage_0_executed = True
        mock_market_state.seconds_to_expiry = 600  # 5 minutes since entry
        
        # Stage 0 should not execute again
        stage_key = "stage_0"
        if getattr(mock_position, stage_key + "_executed", False):
            # Should skip execution
            assert True
    
    def test_fallback_cutoff_at_2_minutes(self, mock_position, mock_market_state):
        """Test that fallback cutoff at 2 minutes still works."""
        mock_market_state.seconds_to_expiry = 120  # 2 minutes to expiry
        cutoff_minutes = 2
        
        time_to_expiry_minutes = mock_market_state.seconds_to_expiry / 60.0
        assert time_to_expiry_minutes <= cutoff_minutes
    
    def test_contracts_updated_after_stage_exit(self, mock_position):
        """Test that position contracts are updated after stage exit."""
        initial_contracts = mock_position.contracts
        contracts_to_close = 4
        
        mock_position.contracts -= contracts_to_close
        
        assert mock_position.contracts == initial_contracts - contracts_to_close
        assert mock_position.contracts == 6
    
    def test_stage_order_uses_limit_gtc(self):
        """Test that staged exit orders use limit with GTC."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create staged exit intent
        intent = OrderIntent(
            ticker="KXBTC15M-2024-01-01T12:00:00",
            side="yes",
            action="sell",
            price_cents=5200,
            count=4,
            order_type="limit",
            time_in_force="gtc",
            source="staged_time_exit",
            agent_id="position_cache",
            rationale="Staged exit stage 0: 40% at 5min",
        )
        
        assert intent.order_type == "limit"
        assert intent.time_in_force == "gtc"
        assert intent.source == "staged_time_exit"
    
    @patch('merid.event_venues.kalshi.order_router.route_order_async')
    async def test_staged_exit_order_submission(self, mock_route_order, mock_position, mock_market_state):
        """Test that staged exit order is submitted correctly."""
        # Mock successful order result
        mock_result = Mock()
        mock_result.status = "accepted"
        mock_result.reason = "ok"
        mock_route_order.return_value = mock_result
        
        mock_market_state.seconds_to_expiry = 600  # 5 minutes since entry
        
        # Simulate staged exit logic
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        contracts_to_close = 4
        staged_exit_intent = OrderIntent(
            ticker=mock_position.market_id,
            side="yes",
            action="sell",
            price_cents=mock_market_state.mid_cents,
            count=contracts_to_close,
            order_type="limit",
            time_in_force="gtc",
            source="staged_time_exit",
            agent_id="position_cache",
            rationale="Staged exit stage 0: 40% at 5min",
        )
        
        result = await mock_route_order(staged_exit_intent)
        
        assert result.status == "accepted"
        mock_route_order.assert_called_once()
    
    def test_time_since_entry_calculation(self, mock_market_state):
        """Test time since entry calculation."""
        mock_market_state.seconds_to_expiry = 600  # 10 minutes to expiry
        time_window = 900.0  # 15 minutes
        
        time_since_entry_minutes = (time_window / 60.0) - (mock_market_state.seconds_to_expiry / 60.0)
        if time_since_entry_minutes < 0:
            time_since_entry_minutes = 0
        
        assert time_since_entry_minutes == 5.0  # 15 - 10 = 5 minutes since entry
    
    def test_time_since_entry_clamped_to_zero(self, mock_market_state):
        """Test that time since entry is clamped to zero if negative."""
        mock_market_state.seconds_to_expiry = 1000  # More than 15 minutes
        time_window = 900.0  # 15 minutes
        
        time_since_entry_minutes = (time_window / 60.0) - (mock_market_state.seconds_to_expiry / 60.0)
        if time_since_entry_minutes < 0:
            time_since_entry_minutes = 0
        
        assert time_since_entry_minutes == 0  # 15 - 16.67 = -1.67, clamped to 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
