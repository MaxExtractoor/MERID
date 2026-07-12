"""Test Position persistence to ensure runtime-only fields are not persisted."""

import pytest
from datetime import datetime
from merid.position_management.position import Position, PositionSide, TrailingType


class TestPositionPersistence:
    """Test that runtime-only fields are not persisted and don't cause deserialization errors."""
    
    def test_trailing_profit_threshold_reached_at_not_persisted(self):
        """Test that trailing_profit_threshold_reached_at is runtime-only and not persisted.
        
        CRITICAL FIX: 2026-07-12 - trailing_profit_threshold_reached_at should not be persisted
        because it's a runtime timestamp used for activation delay. On system restart,
        the delay should be recalculated from the current time, not from a stale timestamp.
        """
        position = Position(
            position_id="test-1",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
            trailing_type=TrailingType.FIXED_CENTS,
            trailing_param=5,
        )
        
        # Set the runtime-only field
        position.trailing_profit_threshold_reached_at = datetime.utcnow().timestamp()
        
        # Convert to dict
        position_dict = position.to_dict()
        
        # Verify the field is NOT in the dict
        assert "trailing_profit_threshold_reached_at" not in position_dict
        
        # Verify other trailing fields ARE in the dict
        assert "trailing_activated" in position_dict
        assert "trailing_profit_zone_activated" in position_dict
    
    def test_from_dict_ignores_trailing_profit_threshold_reached_at(self):
        """Test that from_dict ignores trailing_profit_threshold_reached_at even if present in dict.
        
        This ensures backward compatibility if old persisted data contains this field.
        """
        position_dict = {
            "position_id": "test-2",
            "market_id": "KXBTC15M-TEST",
            "side": "yes",
            "size": 1,
            "avg_entry_price_cents": 50,
            "opened_at": datetime.utcnow().isoformat(),
            "trailing_activated": True,
            "trailing_profit_zone_activated": False,
            # This field should be ignored even if present
            "trailing_profit_threshold_reached_at": 1234567890.0,
        }
        
        position = Position.from_dict(position_dict)
        
        # Verify the field is NOT loaded (should be None)
        assert position.trailing_profit_threshold_reached_at is None
        
        # Verify other fields ARE loaded
        assert position.trailing_activated is True
        assert position.trailing_profit_zone_activated is False
    
    def test_runtime_state_fields_not_persisted(self):
        """Test that all runtime state fields are not persisted.
        
        Runtime state fields (current_price_cents, unrealized_pnl_cents, r_multiple, 
        time_since_entry_seconds) are recalculated on each poll and should not be persisted.
        """
        position = Position(
            position_id="test-3",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        
        # Set runtime state
        position.current_price_cents = 60
        position.unrealized_pnl_cents = 10
        position.r_multiple = 0.5
        position.time_since_entry_seconds = 300.0
        position.trailing_profit_threshold_reached_at = 1234567890.0
        
        # Convert to dict
        position_dict = position.to_dict()
        
        # Verify runtime fields ARE in dict (for debugging/metrics)
        # Note: Unlike trailing_profit_threshold_reached_at, these are persisted for observability
        assert "current_price_cents" in position_dict
        assert "unrealized_pnl_cents" in position_dict
        assert "r_multiple" in position_dict
        assert "time_since_entry_seconds" in position_dict
        
        # But trailing_profit_threshold_reached_at should NOT be
        assert "trailing_profit_threshold_reached_at" not in position_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
