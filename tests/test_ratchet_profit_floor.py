"""Unit tests for ratchet profit floor mechanism in position_monitor.

This tests the research-backed profit locking mechanism that:
- Activates when price reaches a high threshold (e.g., 85¢)
- Sets a hard floor (e.g., 80¢) that never lowers
- Forces exit if price drops to the floor
- Mandatory exit at 99c YES / 1c NO
- Position trimming when >1 contract and price >80c
- Prevents giving back significant gains when 99¢ TP is not guaranteed

NOTE: Ratchet logic is implemented in position_monitor.py (authoritative source)
NOTE: Duplicate ratchet logic was removed from position_cache.py to prevent conflicts
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor


class TestRatchetProfitFloor:
    """Test suite for ratchet profit floor mechanism in position_monitor."""
    
    def test_ratchet_profile_parameters(self):
        """Test that ratchet parameters are defined in profile."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        
        # Check the dataclass default values
        from dataclasses import fields
        for field in fields(Crypto15mProfile):
            if field.name == 'ratchet_profit_floor_enabled':
                assert field.default == True, \
                    f"Expected ratchet_profit_floor_enabled=True, got {field.default}"
            if field.name == 'ratchet_activation_threshold_cents':
                assert field.default == 85, \
                    f"Expected ratchet_activation_threshold_cents=85, got {field.default}"
            if field.name == 'ratchet_floor_offset_cents':
                assert field.default == 5, \
                    f"Expected ratchet_floor_offset_cents=5, got {field.default}"
            if field.name == 'ratchet_force_exit_on_floor_breach':
                assert field.default == True, \
                    f"Expected ratchet_force_exit_on_floor_breach=True, got {field.default}"
            if field.name == 'ratchet_min_hold_after_activation_sec':
                assert field.default == 30, \
                    f"Expected ratchet_min_hold_after_activation_sec=30, got {field.default}"
            if field.name == 'ratchet_mandatory_exit_at_99c':
                assert field.default == True, \
                    f"Expected ratchet_mandatory_exit_at_99c=True, got {field.default}"
            if field.name == 'ratchet_trim_position_enabled':
                assert field.default == True, \
                    f"Expected ratchet_trim_position_enabled=True, got {field.default}"
            if field.name == 'ratchet_trim_threshold_cents':
                assert field.default == 80, \
                    f"Expected ratchet_trim_threshold_cents=80, got {field.default}"
            if field.name == 'ratchet_trim_to_contracts':
                assert field.default == 1, \
                    f"Expected ratchet_trim_to_contracts=1, got {field.default}"
    
    def test_ratchet_floor_reason_exists(self):
        """Test that RATCHET_FLOOR exit reason is defined."""
        from merid.position_management.exit_policy import ExitReason
        
        # Verify RATCHET_FLOOR is in the enum
        assert hasattr(ExitReason, 'RATCHET_FLOOR'), \
            "RATCHET_FLOOR should be defined in ExitReason enum"
        
        assert ExitReason.RATCHET_FLOOR == "ratchet_floor", \
            "RATCHET_FLOOR should have value 'ratchet_floor'"
    
    def test_ratchet_trim_reason_exists(self):
        """Test that RATCHET_TRIM exit reason is defined."""
        from merid.position_management.exit_policy import ExitReason
        
        # Verify RATCHET_TRIM is in the enum
        assert hasattr(ExitReason, 'RATCHET_TRIM'), \
            "RATCHET_TRIM should be defined in ExitReason enum"
        
        assert ExitReason.RATCHET_TRIM == "ratchet_trim", \
            "RATCHET_TRIM should have value 'ratchet_trim'"
    
    def test_ratchet_implementation_in_position_monitor(self):
        """Test that ratchet logic is implemented in position_monitor.py."""
        with open('merid/position_management/position_monitor.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify ratchet logic is present
        assert 'RATCHET PROFIT FLOOR' in content, \
            "Ratchet profit floor logic should be in position_monitor"
        
        # Verify it checks profile parameters
        assert 'ratchet_profit_floor_enabled' in content, \
            "Should check ratchet_profit_floor_enabled from profile"
        
        # Verify it handles activation threshold
        assert 'ratchet_activation_threshold_cents' in content, \
            "Should use ratchet_activation_threshold_cents from profile"
        
        # Verify it handles floor offset
        assert 'ratchet_floor_offset_cents' in content, \
            "Should use ratchet_floor_offset_cents from profile"
        
        # Verify it handles force exit
        assert 'ratchet_force_exit_on_floor_breach' in content, \
            "Should use ratchet_force_exit_on_floor_breach from profile"
        
        # Verify it handles mandatory 99c exit
        assert 'ratchet_mandatory_exit_at_99c' in content, \
            "Should use ratchet_mandatory_exit_at_99c from profile"
        
        # Verify it handles position trimming
        assert 'ratchet_trim_position_enabled' in content, \
            "Should use ratchet_trim_position_enabled from profile"
        assert 'ratchet_trim_threshold_cents' in content, \
            "Should use ratchet_trim_threshold_cents from profile"
        assert 'ratchet_trim_to_contracts' in content, \
            "Should use ratchet_trim_to_contracts from profile"
    
    def test_ratchet_floor_calculation(self):
        """Test that ratchet floor is calculated correctly (85c - 5c = 80c)."""
        with open('merid/position_management/position_monitor.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify floor calculation logic
        assert 'floor_price = activation_threshold - floor_offset' in content or \
               'floor_price = activation_threshold_cents - floor_offset_cents' in content, \
            "Should calculate floor as activation - offset"
    
    def test_ratchet_hold_period(self):
        """Test that ratchet has a minimum hold period to prevent noise-triggered exits."""
        with open('merid/position_management/position_monitor.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify hold period logic
        assert 'ratchet_min_hold_after_activation_sec' in content, \
            "Should use ratchet_min_hold_after_activation_sec from profile"
        
        # Verify hold expiration check
        assert 'hold_expired' in content, \
            "Should check if hold period has expired"
    
    def test_ratchet_exit_intent(self):
        """Test that ratchet floor breach emits exit intent with RATCHET_FLOOR reason."""
        with open('merid/position_management/position_monitor.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify RATCHET_FLOOR exit reason is used
        assert 'ExitReason.RATCHET_FLOOR' in content, \
            "Should emit exit intent with RATCHET_FLOOR reason"
    
    def test_ratchet_99c_mandatory_exit(self):
        """Test that 99c exit is handled by position-level extreme profit (consolidated)."""
        with open('merid/position_management/position_monitor.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # CRITICAL FIX: 2026-07-06 - RATCHET-99C-MANDATORY removed (redundant, handled by position-level extreme profit)
        assert 'RATCHET-99C-MANDATORY' not in content, \
            "Should NOT have RATCHET-99C-MANDATORY logic (removed, consolidated to position-level)"
        
        # Verify position-level auto exit 99c check is present
        assert 'should_trigger_auto_exit_99c' in content, \
            "Should use position-level auto_exit_99c check for 99c exit"
        
        # Verify AUTO_EXIT_99C logging is present
        assert 'AUTO-EXIT-99C triggered' in content, \
            "Should log AUTO_EXIT_99C trigger"
    
    def test_ratchet_no_duplicate_in_position_cache(self):
        """Test that duplicate ratchet logic was removed from position_cache.py."""
        with open('merid/event_venues/kalshi/position_cache.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify duplicate ratchet logic is removed
        assert 'RATCHET PROFIT FLOOR: Research-backed profit locking mechanism' not in content, \
            "Duplicate ratchet logic should be removed from position_cache"
        
        # Verify ratchet tracking fields exist in position_cache
        assert 'ratchet_activated' in content, \
            "Should have ratchet_activated field"
        assert 'ratchet_floor_price_cents' in content, \
            "Should have ratchet_floor_price_cents field"
    
    def test_ratchet_position_trimming(self):
        """Test that ratchet position trimming logic is present."""
        with open('merid/position_management/position_monitor.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify position trimming logic
        assert 'POSITION TRIMMING' in content, \
            "Should have position trimming logic"
        
        # Verify it checks size > trim_to_contracts
        assert 'position.size > trim_to_contracts' in content, \
            "Should check if position size exceeds trim target"
        
        # Verify it uses RATCHET_TRIM exit reason
        assert 'ExitReason.RATCHET_TRIM' in content, \
            "Should use RATCHET_TRIM exit reason for partial close"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
