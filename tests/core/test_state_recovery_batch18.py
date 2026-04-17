"""Tests for state recovery module - Batch 18 Coverage."""
import pytest
import asyncio
import json
from datetime import datetime
from pathlib import Path

from core.state_recovery import (
    StateStatus,
    StateSnapshot,
    RecoveryPoint,
    StateManager,
    GracefulDegradation,
    SelfHealing,
    get_state_manager,
    get_graceful_degradation,
    get_self_healing
)


class TestStateStatus:
    """Tests for StateStatus enum."""

    def test_status_values(self):
        assert StateStatus.HEALTHY.value == "healthy"
        assert StateStatus.DEGRADED.value == "degraded"
        assert StateStatus.CORRUPTED.value == "corrupted"
        assert StateStatus.RECOVERING.value == "recovering"


class TestStateSnapshot:
    """Tests for StateSnapshot dataclass."""

    def test_snapshot_creation(self):
        snapshot = StateSnapshot(
            component="test_component",
            timestamp=1234567890.0,
            state_data={"key": "value"},
            version="1.0",
            checksum="abc123"
        )
        assert snapshot.component == "test_component"
        assert snapshot.version == "1.0"


class TestRecoveryPoint:
    """Tests for RecoveryPoint dataclass."""

    def test_recovery_point_creation(self):
        snapshot = StateSnapshot(
            component="test",
            timestamp=1234567890.0,
            state_data={"key": "value"},
            version="1.0",
            checksum="abc123"
        )
        recovery = RecoveryPoint(
            recovery_id="recovery_123",
            timestamp=1234567890.0,
            component="test",
            state_snapshot=snapshot
        )
        assert recovery.recovery_id == "recovery_123"
        assert recovery.is_valid is True
        assert recovery.recovery_count == 0


class TestStateManager:
    """Tests for StateManager."""

    @pytest.fixture
    def tmp_path(self, tmp_path_factory):
        return tmp_path_factory.mktemp("state_test")

    @pytest.fixture
    def state_manager(self, tmp_path):
        return StateManager("test_component", persistence_dir=str(tmp_path))

    def test_initialization(self, state_manager, tmp_path):
        assert state_manager.component_name == "test_component"
        assert state_manager.current_state == {}
        assert state_manager.state_status == StateStatus.HEALTHY
        assert state_manager.persistence_dir.exists()

    @pytest.mark.asyncio
    async def test_update_state(self, state_manager):
        await state_manager.update_state({"key1": "value1"})
        assert state_manager.current_state == {"key1": "value1"}
        assert len(state_manager.state_history) == 1

    @pytest.mark.asyncio
    async def test_update_state_with_recovery_point(self, state_manager):
        await state_manager.update_state({"key": "value"}, create_recovery_point=True)
        assert len(state_manager.recovery_points) == 1

    @pytest.mark.asyncio
    async def test_get_state(self, state_manager):
        await state_manager.update_state({"key": "value"})
        state = await state_manager.get_state()
        assert state == {"key": "value"}

    @pytest.mark.asyncio
    async def test_history_limit(self, state_manager):
        state_manager._max_history = 5
        for i in range(10):
            await state_manager.update_state({"count": i})
        assert len(state_manager.state_history) == 5

    @pytest.mark.asyncio
    async def test_calculate_checksum(self, state_manager):
        checksum1 = state_manager._calculate_checksum({"a": 1, "b": 2})
        checksum2 = state_manager._calculate_checksum({"b": 2, "a": 1})
        assert checksum1 == checksum2  # Sorts keys

    @pytest.mark.asyncio
    async def test_save_and_load_state(self, state_manager):
        await state_manager.update_state({"key": "value"})
        await state_manager._save_state()
        
        # Create new manager with same component
        new_manager = StateManager("test_component", persistence_dir=str(state_manager.persistence_dir))
        await new_manager._load_state()
        
        assert new_manager.current_state == {"key": "value"}

    def test_get_status(self, state_manager):
        status = state_manager.get_status()
        assert status["component"] == "test_component"
        assert status["status"] == "healthy"
        assert "state_size" in status


class TestGracefulDegradation:
    """Tests for GracefulDegradation."""

    @pytest.fixture
    def degradation(self):
        return GracefulDegradation()

    @pytest.mark.asyncio
    async def test_set_degradation_level(self, degradation):
        await degradation.set_degradation_level("component1", 2)
        level = await degradation.get_degradation_level("component1")
        assert level == 2

    @pytest.mark.asyncio
    async def test_get_degradation_level_default(self, degradation):
        level = await degradation.get_degradation_level("unknown")
        assert level == 0

    @pytest.mark.asyncio
    async def test_execute_with_fallback_success(self, degradation):
        async def primary():
            return "primary_result"
        
        async def fallback():
            return "fallback_result"
        
        degradation.register_fallback("test", fallback)
        result = await degradation.execute_with_fallback("test", primary)
        assert result == "primary_result"

    @pytest.mark.asyncio
    async def test_execute_with_fallback_failure(self, degradation):
        async def primary():
            raise Exception("Primary failed")
        
        async def fallback():
            return "fallback_result"
        
        degradation.register_fallback("test", fallback)
        result = await degradation.execute_with_fallback("test", primary)
        assert result == "fallback_result"

    @pytest.mark.asyncio
    async def test_execute_with_fallback_both_fail(self, degradation):
        async def primary():
            raise Exception("Primary failed")
        
        async def fallback():
            raise Exception("Fallback failed")
        
        degradation.register_fallback("test", fallback)
        with pytest.raises(Exception):
            await degradation.execute_with_fallback("test", primary)

    def test_get_status(self, degradation):
        status = degradation.get_status()
        assert "degraded_components" in status
        assert "total_components" in status


class TestSelfHealing:
    """Tests for SelfHealing."""

    @pytest.fixture
    def healing(self):
        return SelfHealing()

    @pytest.mark.asyncio
    async def test_attempt_healing_success(self, healing):
        async def strategy(error):
            return True
        
        healing.register_healing_strategy("component1", strategy)
        result = await healing.attempt_healing("component1", Exception("Test error"))
        assert result is True
        assert len(healing.healing_history) == 1

    @pytest.mark.asyncio
    async def test_attempt_healing_failure(self, healing):
        async def strategy(error):
            return False
        
        healing.register_healing_strategy("component1", strategy)
        result = await healing.attempt_healing("component1", Exception("Test error"))
        assert result is False

    @pytest.mark.asyncio
    async def test_attempt_healing_no_strategy(self, healing):
        result = await healing.attempt_healing("unknown", Exception("Test"))
        assert result is False

    @pytest.mark.asyncio
    async def test_attempt_healing_exception(self, healing):
        async def strategy(error):
            raise Exception("Healing failed")
        
        healing.register_healing_strategy("component1", strategy)
        result = await healing.attempt_healing("component1", Exception("Test"))
        assert result is False

    def test_get_healing_stats_empty(self, healing):
        stats = healing.get_healing_stats()
        assert stats["total_attempts"] == 0
        assert stats["success_rate"] == 0

    @pytest.mark.asyncio
    async def test_get_healing_stats_with_attempts(self, healing):
        healing.healing_history = [
            {"success": True},
            {"success": False},
            {"success": True}
        ]
        stats = healing.get_healing_stats()
        assert stats["total_attempts"] == 3
        assert stats["successful"] == 2


class TestGetStateManager:
    """Tests for state manager singleton."""

    def test_singleton(self):
        manager1 = get_state_manager("component1")
        manager2 = get_state_manager("component1")
        assert manager1 is manager2

    def test_different_components(self):
        manager1 = get_state_manager("comp1")
        manager2 = get_state_manager("comp2")
        assert manager1 is not manager2


class TestGetGracefulDegradation:
    """Tests for graceful degradation singleton."""

    def test_singleton(self):
        gd1 = get_graceful_degradation()
        gd2 = get_graceful_degradation()
        assert gd1 is gd2


class TestGetSelfHealing:
    """Tests for self healing singleton."""

    def test_singleton(self):
        sh1 = get_self_healing()
        sh2 = get_self_healing()
        assert sh1 is sh2
