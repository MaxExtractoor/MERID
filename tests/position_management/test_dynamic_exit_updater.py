"""
Tests for Dynamic Exit Policy Updater
"""

import pytest
from unittest.mock import Mock
from dataclasses import dataclass

from merid.position_management.dynamic_exit_updater import DynamicExitPolicyUpdater
from merid.position_management.unified_exit_policy_engine import ExitPolicyResolution


@dataclass
class MockPosition:
    """Mock position for testing."""
    position_id: str = "test_position"


class TestDynamicExitPolicyUpdater:
    """Tests for DynamicExitPolicyUpdater."""
    
    @pytest.fixture
    def updater(self):
        """Create an updater with default config."""
        config = {
            "time_decay_enabled": True,
            "atr_scaling_enabled": False,
            "regime_adaptation_enabled": True,
            "time_decay_interval_seconds": 300,
            "time_decay_sl_tightening_pct": 0.10,
        }
        return DynamicExitPolicyUpdater(config)
    
    @pytest.fixture
    def mock_position(self):
        """Create a mock position."""
        return MockPosition()
    
    @pytest.fixture
    def base_policy(self):
        """Create a base exit policy."""
        return ExitPolicyResolution(
            policy_id="test",
            asset="BTC",
            regime="normal",
            tp_r_multiple=1.0,
            tp_min_cents=3,
            sl_cents=10,
            sl_r_multiple=1.0,
            trailing_enabled=True,
            trailing_giveback_cents=5,
            max_hold_seconds=900,
        )
    
    def test_update_policy_no_changes(self, updater, mock_position, base_policy):
        """Test update with no dynamic adjustments needed."""
        updated = updater.update_policy(
            position=mock_position,
            current_policy=base_policy,
            current_price_cents=50,
            time_since_entry_seconds=100,  # Less than decay interval
        )
        
        # Should be unchanged
        assert updated.sl_cents == base_policy.sl_cents
        assert updated.tp_min_cents == base_policy.tp_min_cents
        assert updated.max_hold_seconds == base_policy.max_hold_seconds
    
    def test_apply_time_decay_single_interval(self, updater, base_policy):
        """Test time decay after one interval."""
        updated = updater.update_policy(
            position=MockPosition(),
            current_policy=base_policy,
            current_price_cents=50,
            time_since_entry_seconds=300,  # Exactly one interval
        )
        
        # SL should be tightened by 10%
        assert updated.sl_cents == int(10 * 0.9)  # 9 cents
        # Trailing giveback should be tightened by 10%
        assert updated.trailing_giveback_cents == int(5 * 0.9)  # 4 or 5 cents
    
    def test_apply_time_decay_multiple_intervals(self, updater, base_policy):
        """Test time decay after multiple intervals."""
        updated = updater.update_policy(
            position=MockPosition(),
            current_policy=base_policy,
            current_price_cents=50,
            time_since_entry_seconds=600,  # Two intervals
        )
        
        # SL should be tightened by 10% twice (0.9 * 0.9 = 0.81)
        assert updated.sl_cents == int(10 * 0.81)  # 8 cents
    
    def test_apply_time_decay_disabled(self, base_policy):
        """Test with time decay disabled."""
        config = {"time_decay_enabled": False}
        updater = DynamicExitPolicyUpdater(config)
        
        updated = updater.update_policy(
            position=MockPosition(),
            current_policy=base_policy,
            current_price_cents=50,
            time_since_entry_seconds=600,
        )
        
        # Should be unchanged
        assert updated.sl_cents == base_policy.sl_cents
    
    def test_apply_atr_scaling(self, base_policy):
        """Test ATR-based scaling."""
        config = {
            "time_decay_enabled": False,
            "atr_scaling_enabled": True,
            "regime_adaptation_enabled": False,
            "atr_stop_multiplier": 1.0,
            "atr_tp_multiplier": 2.0,
        }
        updater = DynamicExitPolicyUpdater(config)
        
        updated = updater.update_policy(
            position=MockPosition(),
            current_policy=base_policy,
            current_price_cents=50,
            time_since_entry_seconds=100,
            current_atr_pct=0.05,  # 5% ATR
        )
        
        # SL should be set based on ATR (5% of 100 = 5 cents * 1.0 = 5 cents)
        # But we had sl_cents=10, so it should remain since we only set if None
        # Actually, the logic sets it if sl_cents is None and sl_r_multiple exists
        # Let's test with sl_cents=None
        base_policy.sl_cents = None
        updated = updater.update_policy(
            position=MockPosition(),
            current_policy=base_policy,
            current_price_cents=50,
            time_since_entry_seconds=100,
            current_atr_pct=0.05,
        )
        
        assert updated.sl_cents == int(5 * 1.0)  # 5 cents
    
    def test_apply_regime_adjustment_conservative(self, updater, base_policy):
        """Test regime adjustment to conservative."""
        updated = updater.update_policy(
            position=MockPosition(),
            current_policy=base_policy,
            current_price_cents=50,
            time_since_entry_seconds=100,
            current_regime="conservative",
        )
        
        # Conservative: tighter TP, wider SL, longer hold
        assert updated.tp_r_multiple == 1.0 * 0.75
        assert updated.sl_cents == int(10 * 1.2)
        assert updated.max_hold_seconds == int(900 * 1.5)
        assert updated.regime == "conservative"
    
    def test_apply_regime_adjustment_aggressive(self, updater, base_policy):
        """Test regime adjustment to aggressive."""
        updated = updater.update_policy(
            position=MockPosition(),
            current_policy=base_policy,
            current_price_cents=50,
            time_since_entry_seconds=100,
            current_regime="aggressive",
        )
        
        # Aggressive: wider TP, tighter SL, shorter hold
        assert updated.tp_r_multiple == 1.0 * 1.2
        assert updated.sl_cents == int(10 * 0.8)
        assert updated.max_hold_seconds == int(900 * 0.67)
        assert updated.regime == "aggressive"
    
    def test_apply_regime_adjustment_no_change(self, updater, base_policy):
        """Test regime adjustment when regime doesn't change."""
        base_policy.regime = "normal"
        
        updated = updater.update_policy(
            position=MockPosition(),
            current_policy=base_policy,
            current_price_cents=50,
            time_since_entry_seconds=100,
            current_regime="normal",
        )
        
        # Should be unchanged
        assert updated.tp_r_multiple == base_policy.tp_r_multiple
        assert updated.sl_cents == base_policy.sl_cents
        assert updated.max_hold_seconds == base_policy.max_hold_seconds
    
    def test_combined_adjustments(self, updater, base_policy):
        """Test combined time decay and regime adjustment."""
        updated = updater.update_policy(
            position=MockPosition(),
            current_policy=base_policy,
            current_price_cents=50,
            time_since_entry_seconds=300,  # One decay interval
            current_regime="conservative",
        )
        
        # Should have both time decay and regime adjustment
        # Time decay: 10 * 0.9 = 9, then conservative regime: 9 * 1.2 = 10.8 -> 10
        # The regime adjustment widens SL, which can offset time decay
        assert updated.regime == "conservative"  # Regime change
        assert updated.max_hold_seconds > base_policy.max_hold_seconds  # Conservative
        assert updated.tp_r_multiple < base_policy.tp_r_multiple  # Conservative tightens TP
        assert updated.trailing_giveback_cents < base_policy.trailing_giveback_cents  # Time decay
    
    def test_updater_with_no_config(self):
        """Test updater with no config (defaults)."""
        updater = DynamicExitPolicyUpdater()
        
        assert updater._time_decay_enabled is True
        assert updater._atr_scaling_enabled is False
        assert updater._regime_adaptation_enabled is True
