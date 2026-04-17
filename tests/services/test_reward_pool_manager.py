"""Tests for services/reward_pool_manager.py."""
import pytest
from decimal import Decimal
from datetime import datetime
from services.reward_pool_manager import (
    RewardPoolState, RewardPoolManager
)


class TestRewardPoolState:
    """Test RewardPoolState dataclass."""

    def test_creation(self):
        """Test RewardPoolState creation."""
        now = datetime.utcnow()
        state = RewardPoolState(
            pool_id="pool_123",
            base_emission_per_day=Decimal("1000.0"),
            multiplier=Decimal("1.0"),
            last_adjusted=now,
            participation_rate=Decimal("0.5")
        )
        assert state.pool_id == "pool_123"
        assert state.base_emission_per_day == Decimal("1000.0")
        assert state.multiplier == Decimal("1.0")
        assert state.participation_rate == Decimal("0.5")


class TestRewardPoolManager:
    """Test RewardPoolManager class."""

    def test_initialization(self):
        """Test manager initialization."""
        manager = RewardPoolManager()
        assert manager._pools == {}

    def test_register_pool(self):
        """Test registering a pool."""
        manager = RewardPoolManager()
        manager.register_pool("pool_1", Decimal("1000.0"))
        
        assert "pool_1" in manager._pools
        pool = manager._pools["pool_1"]
        assert pool.pool_id == "pool_1"
        assert pool.base_emission_per_day == Decimal("1000.0")
        assert pool.multiplier == Decimal("1.0")
        assert pool.participation_rate == Decimal("0.0")

    def test_update_participation(self):
        """Test updating participation rate."""
        manager = RewardPoolManager()
        manager.register_pool("pool_1", Decimal("1000.0"))
        manager.update_participation("pool_1", Decimal("0.75"))
        
        assert manager._pools["pool_1"].participation_rate == Decimal("0.75")

    def test_adjust_rewards_low_participation(self):
        """Test reward adjustment for low participation."""
        manager = RewardPoolManager()
        manager.register_pool("pool_1", Decimal("1000.0"))
        manager.update_participation("pool_1", Decimal("0.2"))
        
        state = manager.adjust_rewards("pool_1")
        
        assert state.multiplier == Decimal("1.2")

    def test_adjust_rewards_high_participation(self):
        """Test reward adjustment for high participation."""
        manager = RewardPoolManager()
        manager.register_pool("pool_1", Decimal("1000.0"))
        manager.update_participation("pool_1", Decimal("0.9"))
        
        state = manager.adjust_rewards("pool_1")
        
        assert state.multiplier == Decimal("0.9")

    def test_adjust_rewards_normal_participation(self):
        """Test reward adjustment for normal participation."""
        manager = RewardPoolManager()
        manager.register_pool("pool_1", Decimal("1000.0"))
        manager.update_participation("pool_1", Decimal("0.5"))
        
        state = manager.adjust_rewards("pool_1")
        
        assert state.multiplier == Decimal("1.0")

    def test_adjust_rewards_updates_timestamp(self):
        """Test that adjust_rewards updates last_adjusted timestamp."""
        manager = RewardPoolManager()
        manager.register_pool("pool_1", Decimal("1000.0"))
        old_time = manager._pools["pool_1"].last_adjusted
        
        # Small delay to ensure timestamp changes
        import time
        time.sleep(0.01)
        
        manager.adjust_rewards("pool_1")
        
        assert manager._pools["pool_1"].last_adjusted > old_time

    def test_current_emission(self):
        """Test calculating current emission."""
        manager = RewardPoolManager()
        manager.register_pool("pool_1", Decimal("1000.0"))
        manager.update_participation("pool_1", Decimal("0.2"))
        manager.adjust_rewards("pool_1")
        
        emission = manager.current_emission("pool_1")
        
        # 1000 * 1.2 = 1200
        assert emission == Decimal("1200.0")

    def test_current_emission_no_adjustment(self):
        """Test current emission without adjustment."""
        manager = RewardPoolManager()
        manager.register_pool("pool_1", Decimal("1000.0"))
        
        emission = manager.current_emission("pool_1")
        
        # 1000 * 1.0 = 1000
        assert emission == Decimal("1000.0")

    def test_multiple_pools(self):
        """Test managing multiple pools."""
        manager = RewardPoolManager()
        manager.register_pool("pool_1", Decimal("1000.0"))
        manager.register_pool("pool_2", Decimal("2000.0"))
        
        manager.update_participation("pool_1", Decimal("0.9"))
        manager.update_participation("pool_2", Decimal("0.2"))
        
        manager.adjust_rewards("pool_1")
        manager.adjust_rewards("pool_2")
        
        emission_1 = manager.current_emission("pool_1")
        emission_2 = manager.current_emission("pool_2")
        
        assert emission_1 == Decimal("900.0")  # 1000 * 0.9
        assert emission_2 == Decimal("2400.0")  # 2000 * 1.2
