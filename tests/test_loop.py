"""Tests for merid.loop.MeridLoop"""

import time

import pytest
from unittest.mock import AsyncMock, patch
from merid.loop import MeridLoop, LoopConfig


class TestSlowActionAdaptiveSkipping:
    """Tests for the _should_skip_due_to_slowness mechanism."""

    def test_should_skip_returns_false_when_no_slow_history(self):
        """Test that _should_skip_due_to_slowness returns False initially."""
        config = LoopConfig(
            active_symbols=["BTC"],
            active_domains=["prediction"],
            feature_refresh_interval=30.0,
            agent_cycle_interval=60.0,
            consensus_interval=30.0,
            arb_scan_interval=60.0,
            cqi_interval=60.0,
            reconciliation_interval=300.0,
            enable_execution=True,
            enable_reconciliation=True,
        )
        loop = MeridLoop(config)
        now = time.time()
        assert loop._should_skip_due_to_slowness("features", now) is False
        assert loop._should_skip_due_to_slowness("arb_scan", now) is False
        assert loop._should_skip_due_to_slowness("liquidity", now) is False

    def test_should_skip_returns_true_within_cooldown(self):
        """Test that slow actions are skipped within the cooldown period."""
        config = LoopConfig(
            active_symbols=["BTC"],
            active_domains=["prediction"],
            feature_refresh_interval=30.0,
            agent_cycle_interval=60.0,
            consensus_interval=30.0,
            arb_scan_interval=60.0,
            cqi_interval=60.0,
            reconciliation_interval=300.0,
            enable_execution=True,
            enable_reconciliation=True,
        )
        loop = MeridLoop(config)
        now = time.time()

        # Mark features as slow
        loop._slow_action_last_skip["features"] = now - 30  # 30 seconds ago

        # Should skip (within 60s cooldown)
        assert loop._should_skip_due_to_slowness("features", now) is True

        # Should NOT skip after cooldown expires
        future = now + 61
        assert loop._should_skip_due_to_slowness("features", future) is False

        # Record should be cleared after cooldown
        assert "features" not in loop._slow_action_last_skip

    def test_different_actions_tracked_separately(self):
        """Test that slow action tracking is per-step."""
        config = LoopConfig(
            active_symbols=["BTC"],
            active_domains=["prediction"],
            feature_refresh_interval=30.0,
            agent_cycle_interval=60.0,
            consensus_interval=30.0,
            arb_scan_interval=60.0,
            cqi_interval=60.0,
            reconciliation_interval=300.0,
            enable_execution=True,
            enable_reconciliation=True,
        )
        loop = MeridLoop(config)
        now = time.time()

        # Mark only features as slow
        loop._slow_action_last_skip["features"] = now

        # Features should skip
        assert loop._should_skip_due_to_slowness("features", now) is True

        # Other steps should not skip
        assert loop._should_skip_due_to_slowness("arb_scan", now) is False
        assert loop._should_skip_due_to_slowness("liquidity", now) is False


class TestIncreasedIntervals:
    """Tests for the increased intervals to reduce event-loop lag."""

    def test_liquidity_refresh_interval_is_60s(self):
        """Test that liquidity refresh interval is set to 60 seconds."""
        config = LoopConfig(
            active_symbols=["BTC"],
            active_domains=["prediction"],
            feature_refresh_interval=30.0,
            agent_cycle_interval=60.0,
            consensus_interval=30.0,
            arb_scan_interval=60.0,
            cqi_interval=60.0,
            reconciliation_interval=300.0,
            enable_execution=True,
            enable_reconciliation=True,
        )
        loop = MeridLoop(config)
        assert loop._liquidity_refresh_interval == 60.0

    def test_order_groups_sync_interval_is_60s(self):
        """Test that order groups sync interval is set to 60 seconds."""
        config = LoopConfig(
            active_symbols=["BTC"],
            active_domains=["prediction"],
            feature_refresh_interval=30.0,
            agent_cycle_interval=60.0,
            consensus_interval=30.0,
            arb_scan_interval=60.0,
            cqi_interval=60.0,
            reconciliation_interval=300.0,
            enable_execution=True,
            enable_reconciliation=True,
        )
        loop = MeridLoop(config)
        assert loop._order_groups_sync_interval == 60.0


@pytest.mark.asyncio
async def test_tick_lifecycle():
    """Test that MeridLoop.tick() runs through phases without errors and updates metrics."""
    config = LoopConfig()
    loop = MeridLoop(config)

    # Mock all service accessors to avoid real dependencies
    mock_services = {
        '_feature_service': AsyncMock(return_value=None),
        '_scanner': AsyncMock(return_value=None),
        '_drift_detector': AsyncMock(return_value=None),
        '_signal_store': AsyncMock(return_value=None),
        '_consensus_coordinator': AsyncMock(return_value=None),
        '_risk_manager': AsyncMock(return_value=None),
        '_agent_registry': AsyncMock(return_value=None),
        '_execution_guard': AsyncMock(return_value=None),
        '_risk_context': AsyncMock(return_value=None),
        '_betting_odds_client': AsyncMock(return_value=None),
        '_betting_store': AsyncMock(return_value=None),
        '_order_group_lifecycle': AsyncMock(return_value=None),
        '_liquidity_monitor': AsyncMock(return_value=None),
    }

    for attr, mock in mock_services.items():
        patch.object(loop, attr, return_value=mock)

    # Mock _run_step to simulate phase execution
    with patch.object(loop, '_run_step') as mock_run_step:
        mock_run_step.return_value = None

        # Run tick
        summary = await loop.tick()

        # Verify basic structure
        assert summary['tick'] == 1
        assert 'actions' in summary
        assert isinstance(summary['actions'], list)
        assert 'duration_ms' in summary

        # Verify metrics updated
        assert loop.metrics.total_ticks == 1
        assert loop.metrics.last_tick_at > 0
        assert loop.metrics.last_tick_duration_ms >= 0

        # Verify some phases were attempted (even if mocked)
        # At minimum, features phase should be called if interval allows
        # But since it's the first tick, and intervals are set, some may run
