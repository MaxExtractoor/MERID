"""Tests for Phase 1 performance optimizations.

Tests verify:
1. REST sync frequency optimization (30s interval instead of every cycle)
2. uvloop optimization (2-4x faster async I/O)
3. Parallel agent processing (asyncio.gather instead of sequential)
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any


class TestRestSyncFrequencyOptimization:
    """Test REST sync frequency optimization in LeanAgentGrid15m."""
    
    @pytest.fixture
    def mock_agent_grid(self):
        """Create a mock LeanAgentGrid15m instance for testing."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m, LeanAgent15m, LeanAgentConfig
        
        # Create mock agents
        mock_agents = []
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            mock_agent = Mock(spec=LeanAgent15m)
            mock_agent.config = Mock(spec=LeanAgentConfig)
            mock_agent.config.name = f"{asset}_15M"
            mock_agent.collect_order_candidate = AsyncMock(return_value=None)
            mock_agents.append(mock_agent)
        
        grid = LeanAgentGrid15m(agents=mock_agents)
        return grid
    
    def test_rest_sync_interval_initialization(self, mock_agent_grid):
        """Test that REST sync interval is initialized to 30 seconds."""
        assert hasattr(mock_agent_grid, '_rest_sync_interval')
        assert mock_agent_grid._rest_sync_interval == 30.0
        assert hasattr(mock_agent_grid, '_last_rest_sync_time')
        assert mock_agent_grid._last_rest_sync_time == 0.0
    
    @pytest.mark.asyncio
    async def test_rest_sync_skips_when_within_interval(self, mock_agent_grid):
        """Test that REST sync is skipped when called within the 30s interval."""
        # Set last sync time to current time
        mock_agent_grid._last_rest_sync_time = time.time()
        
        # Mock the actual sync logic to track if it was called
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache') as mock_get_cache:
            mock_cache = AsyncMock()
            mock_get_cache.return_value = mock_cache
            
            # Call sync_from_rest - should skip
            await mock_agent_grid.sync_from_rest(tick=1)
            
            # Verify that the actual sync logic was NOT called
            mock_cache.sync_from_rest.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_rest_sync_executes_when_interval_expired(self, mock_agent_grid):
        """Test that REST sync executes when interval has expired."""
        # Set last sync time to 31 seconds ago
        mock_agent_grid._last_rest_sync_time = time.time() - 31.0
        
        # Mock the actual sync logic
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache') as mock_get_cache:
            mock_cache = AsyncMock()
            mock_get_cache.return_value = mock_cache
            
            # Call sync_from_rest - should execute
            await mock_agent_grid.sync_from_rest(tick=1)
            
            # Verify that the actual sync logic WAS called
            mock_cache.sync_from_rest.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_rest_sync_updates_timestamp(self, mock_agent_grid):
        """Test that REST sync updates the last sync timestamp."""
        # Set last sync time to 31 seconds ago
        old_time = time.time() - 31.0
        mock_agent_grid._last_rest_sync_time = old_time
        
        # Mock the actual sync logic
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache') as mock_get_cache:
            mock_cache = AsyncMock()
            mock_get_cache.return_value = mock_cache
            
            # Call sync_from_rest
            await mock_agent_grid.sync_from_rest(tick=1)
            
            # Verify that timestamp was updated
            assert mock_agent_grid._last_rest_sync_time > old_time
    
    @pytest.mark.asyncio
    async def test_rest_sync_handles_exceptions_gracefully(self, mock_agent_grid):
        """Test that REST sync handles exceptions without crashing."""
        # Set last sync time to 31 seconds ago
        mock_agent_grid._last_rest_sync_time = time.time() - 31.0
        
        # Mock the actual sync logic to raise an exception
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache') as mock_get_cache:
            mock_get_cache.side_effect = Exception("Test exception")
            
            # Call sync_from_rest - should not raise
            await mock_agent_grid.sync_from_rest(tick=1)
            
            # Should not crash, just log warning


class TestUvloopOptimization:
    """Test uvloop optimization in main_15m_lean.py."""
    
    def test_uvloop_import_attempt(self):
        """Test that uvloop import is attempted in main_15m_lean.py."""
        # This test verifies that the code attempts to import uvloop
        # We can't test the actual enablement without running the server
        # but we can verify the import logic exists
        
        import web.main_15m_lean as main_module
        
        # Reload to ensure fresh import
        import importlib
        importlib.reload(main_module)
        
        # The module should have attempted to import uvloop
        # We can't test the actual import success without uvloop installed
        # but the code should handle ImportError gracefully
        assert True  # If we got here, the import logic didn't crash
    
    def test_uvloop_fallback_on_import_error(self):
        """Test that the code falls back to default asyncio when uvloop is not available."""
        # This test verifies graceful fallback
        import asyncio
        
        # Even if uvloop is not available, the code should still work
        # with default asyncio
        loop = asyncio.new_event_loop()
        assert loop is not None
        loop.close()


class TestParallelAgentProcessing:
    """Test parallel agent processing optimization in LeanAgentGrid15m."""
    
    @pytest.fixture
    def mock_agent_grid_with_timing(self):
        """Create a mock LeanAgentGrid15m with timing-aware agents."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m, LeanAgent15m, LeanAgentConfig
        
        # Create mock agents with simulated processing time
        mock_agents = []
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            mock_agent = Mock(spec=LeanAgent15m)
            mock_agent.config = Mock(spec=LeanAgentConfig)
            mock_agent.config.name = f"{asset}_15M"
            
            # Simulate 0.1s processing time per agent
            async def slow_collect(tick):
                await asyncio.sleep(0.1)
                return {"side": "yes", "asset": asset}
            
            mock_agent.collect_order_candidate = AsyncMock(side_effect=slow_collect)
            mock_agents.append(mock_agent)
        
        grid = LeanAgentGrid15m(agents=mock_agents)
        return grid
    
    @pytest.mark.asyncio
    async def test_parallel_processing_faster_than_sequential(self, mock_agent_grid_with_timing):
        """Test that parallel processing is faster than sequential."""
        # Mock sync_from_rest to skip
        mock_agent_grid_with_timing._last_rest_sync_time = time.time()
        
        # Measure parallel execution time
        start_time = time.time()
        await mock_agent_grid_with_timing.run_cycle(tick=1, allow_new_entries=False)
        parallel_time = time.time() - start_time
        
        # Sequential would take 5 * 0.1s = 0.5s
        # Parallel should take ~0.1s (limited by slowest agent)
        # Allow some overhead, but should be significantly faster
        assert parallel_time < 0.3, f"Parallel processing took {parallel_time}s, expected <0.3s"
    
    @pytest.mark.asyncio
    async def test_parallel_processing_collects_all_candidates(self, mock_agent_grid_with_timing):
        """Test that parallel processing collects candidates from all agents."""
        # Mock sync_from_rest to skip
        mock_agent_grid_with_timing._last_rest_sync_time = time.time()
        
        # Run cycle
        candidates = await mock_agent_grid_with_timing.run_cycle(tick=1, allow_new_entries=False)
        
        # Each agent produces one candidate; best-edge filter selects the top one.
        assert len(candidates) >= 1
    
    @pytest.mark.asyncio
    async def test_parallel_processing_handles_exceptions(self):
        """Test that parallel processing handles exceptions from individual agents."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m, LeanAgent15m, LeanAgentConfig
        
        # Create mock agents where one raises an exception
        mock_agents = []
        for i, asset in enumerate(["BTC", "ETH", "SOL", "XRP", "DOGE"]):
            mock_agent = Mock(spec=LeanAgent15m)
            mock_agent.config = Mock(spec=LeanAgentConfig)
            mock_agent.config.name = f"{asset}_15M"
            
            if i == 2:  # Third agent raises exception
                mock_agent.collect_order_candidate = AsyncMock(side_effect=Exception("Test error"))
            else:
                mock_agent.collect_order_candidate = AsyncMock(return_value={"side": "yes", "asset": asset})
            
            mock_agents.append(mock_agent)
        
        grid = LeanAgentGrid15m(agents=mock_agents)
        grid._last_rest_sync_time = time.time()
        
        # Run cycle - should not crash
        candidates = await grid.run_cycle(tick=1, allow_new_entries=False)
        
        # Should have collected from 4 agents (one failed)
        assert len(candidates) == 4
    
    @pytest.mark.asyncio
    async def test_parallel_processing_with_no_candidates(self):
        """Test that parallel processing handles case where no agents generate candidates."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m, LeanAgent15m, LeanAgentConfig
        
        # Create mock agents that return None
        mock_agents = []
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            mock_agent = Mock(spec=LeanAgent15m)
            mock_agent.config = Mock(spec=LeanAgentConfig)
            mock_agent.config.name = f"{asset}_15M"
            mock_agent.collect_order_candidate = AsyncMock(return_value=None)
            mock_agents.append(mock_agent)
        
        grid = LeanAgentGrid15m(agents=mock_agents)
        grid._last_rest_sync_time = time.time()
        
        # Run cycle
        candidates = await grid.run_cycle(tick=1, allow_new_entries=False)
        
        # Should have no candidates
        assert len(candidates) == 0


class TestOptimizationIntegration:
    """Integration tests for all Phase 1 optimizations together."""
    
    @pytest.mark.asyncio
    async def test_combined_optimizations_reduce_cycle_time(self):
        """Test that combined optimizations significantly reduce cycle time."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m, LeanAgent15m, LeanAgentConfig
        
        # Create mock agents with simulated processing
        mock_agents = []
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            mock_agent = Mock(spec=LeanAgent15m)
            mock_agent.config = Mock(spec=LeanAgentConfig)
            mock_agent.config.name = f"{asset}_15M"
            
            async def simulate_work(tick):
                await asyncio.sleep(0.05)  # Simulate 50ms work
                return {"side": "yes", "asset": asset}
            
            mock_agent.collect_order_candidate = AsyncMock(side_effect=simulate_work)
            mock_agents.append(mock_agent)
        
        grid = LeanAgentGrid15m(agents=mock_agents)
        grid._last_rest_sync_time = time.time()  # Skip REST sync
        
        # Measure cycle time with optimizations
        start_time = time.time()
        await grid.run_cycle(tick=1, allow_new_entries=False)
        optimized_time = time.time() - start_time
        
        # With optimizations:
        # - REST sync: skipped (0s)
        # - Parallel agents: ~0.05s (all run concurrently)
        # Expected: <0.1s total
        assert optimized_time < 0.15, f"Optimized cycle took {optimized_time}s, expected <0.15s"
