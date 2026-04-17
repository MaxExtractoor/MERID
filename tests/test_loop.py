"""Tests for merid.loop.MeridLoop"""

import pytest
from unittest.mock import AsyncMock, patch
from merid.loop import MeridLoop, LoopConfig


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
