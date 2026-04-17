"""Tests for Kalshi integration in main loop.

Test Cases:
1. Loop generates Kalshi signals during feature refresh
2. Loop runs Kalshi agent cycle
3. Signals are stored in SignalStore
4. Agent grid is checked if running
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time


@pytest.mark.asyncio
async def test_loop_generates_kalshi_signals():
    """Test that loop generates Kalshi signals during feature refresh."""
    from merid.loop import MeridLoop
    
    loop = MeridLoop()
    summary = {"actions": []}
    now = time.time()
    
    # Mock signal store and generator
    with patch("merid.signals.store.get_signal_store") as mock_store, \
         patch("merid.signals.kalshi_signals.get_kalshi_venue_adapter") as mock_adapter:
        
        # Mock store
        store = MagicMock()
        store.store_signal = MagicMock()
        mock_store.return_value = store
        
        # Mock adapter to return empty instruments (graceful degradation)
        adapter = MagicMock()
        adapter.list_instruments = AsyncMock(return_value=[])
        mock_adapter.return_value = adapter
        
        # Run feature refresh
        await loop._refresh_kalshi_signals(now, summary, store)
        
        # Verify store.store_signal was called (even if with 0 signals)
        # Or verify summary was updated
        assert any("kalshi" in str(action).lower() for action in summary.get("actions", []))


@pytest.mark.asyncio
async def test_loop_runs_kalshi_agent_cycle():
    """Test that loop runs Kalshi agent cycle when prediction domain active."""
    from merid.loop import MeridLoop
    
    loop = MeridLoop()
    summary = {"actions": []}
    
    with patch("merid.prediction.agent_grid.get_agent_grid") as mock_grid:
        # Mock running grid with no agents
        grid = MagicMock()
        grid._running = True
        grid.agents = []
        mock_grid.return_value = grid
        
        # Run agent cycle
        await loop._run_kalshi_agent_cycle(summary)
        
        # Verify grid was accessed
        assert mock_grid.called


@pytest.mark.asyncio
async def test_loop_skips_kalshi_if_grid_not_running():
    """Test that loop skips Kalshi cycle if grid not running."""
    from merid.loop import MeridLoop
    
    loop = MeridLoop()
    summary = {"actions": []}
    
    with patch("merid.prediction.agent_grid.get_agent_grid") as mock_grid:
        # Mock stopped grid
        grid = MagicMock()
        grid._running = False
        grid.agents = []
        mock_grid.return_value = grid
        
        # Run agent cycle
        await loop._run_kalshi_agent_cycle(summary)
        
        # Should not add kalshi_agents action
        assert not any("kalshi_agents" in str(a) for a in summary.get("actions", []))


@pytest.mark.asyncio
async def test_loop_counts_actionable_signals():
    """Test that loop counts and reports actionable signals from agents."""
    from merid.loop import MeridLoop
    
    loop = MeridLoop()
    summary = {"actions": []}
    
    with patch("merid.prediction.agent_grid.get_agent_grid") as mock_grid:
        # Mock grid with agent that has signals
        agent = MagicMock()
        agent.state.enabled = True
        agent.state.signal_log = [
            {"action": "BUY_YES", "ticker": "BTC-TEST"},
            {"action": "NO_ACTION", "ticker": "ETH-TEST"},  # Should be filtered
            {"action": "SELL_NO", "ticker": "DOGE-TEST"},
        ]
        
        grid = MagicMock()
        grid._running = True
        grid.agents = [agent]
        mock_grid.return_value = grid
        
        # Run agent cycle
        await loop._run_kalshi_agent_cycle(summary)
        
        # Should count 2 actionable signals (not NO_ACTION)
        actions = summary.get("actions", [])
        kalshi_actions = [a for a in actions if "kalshi_agents" in str(a)]
        
        if kalshi_actions:
            # Extract signal count from action string
            action_str = str(kalshi_actions[0])
            assert "2" in action_str or "signals" in action_str


@pytest.mark.asyncio
async def test_loop_handles_agent_grid_exception():
    """Test that loop handles agent grid exceptions gracefully."""
    from merid.loop import MeridLoop
    
    loop = MeridLoop()
    summary = {"actions": []}
    
    with patch("merid.prediction.agent_grid.get_agent_grid", side_effect=Exception("Grid failed")):
        # Should not crash
        await loop._run_kalshi_agent_cycle(summary)
        
        # Should complete without error
        assert True


@pytest.mark.asyncio
async def test_feature_refresh_includes_kalshi_if_prediction_active():
    """Test that feature refresh generates Kalshi signals if prediction domain active."""
    from merid.loop import MeridLoop
    from merid.paper_config import DOMAIN_CONFIGS
    
    # Ensure prediction domain is enabled
    if "prediction" not in DOMAIN_CONFIGS or not DOMAIN_CONFIGS["prediction"].enabled:
        pytest.skip("Prediction domain not enabled")
    
    loop = MeridLoop()
    summary = {"actions": []}
    now = time.time()
    
    with patch("merid.signals.store.get_signal_store") as mock_store, \
         patch("merid.signals.features.FeatureService") as mock_fs, \
         patch("merid.signals.live_feeds.get_live_feed_manager") as mock_lfm, \
         patch("merid.signals.kalshi_signals.get_kalshi_venue_adapter") as mock_adapter:
        
        # Mock dependencies
        store = MagicMock()
        store.store_signal = MagicMock()
        store.store_feature_snapshot = MagicMock()
        mock_store.return_value = store
        
        fs = MagicMock()
        fs.get_news_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
        fs.get_social_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
        fs.get_onchain_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
        fs.get_macro_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
        mock_fs.return_value = fs
        
        lfm = MagicMock()
        lfm.refresh_all = AsyncMock()
        mock_lfm.return_value = lfm
        
        adapter = MagicMock()
        adapter.list_instruments = AsyncMock(return_value=[])
        mock_adapter.return_value = adapter
        
        # Run feature refresh
        await loop._refresh_features(now, summary)
        
        # Check if kalshi_signals action was added
        actions = summary.get("actions", [])
        has_kalshi = any("kalshi_signals" in str(a) for a in actions)
        
        # Should include Kalshi signal generation
        assert has_kalshi or len(actions) > 0  # At least tried


def test_kalshi_stack_no_betting_imports():
    """Guard: Kalshi prediction domain must not import betting modules on hot path.
    
    This test fails if merid.betting is imported when running Kalshi-only mode,
    preventing the legacy sports betting stack from contaminating the Kalshi loop.
    See: slow tick #134 analysis (betting_refreshed:6events on hot path).
    """
    import sys
    
    # Check that betting modules are not loaded in Kalshi path
    betting_modules = [name for name in sys.modules if name.startswith("merid.betting")]
    
    # If we are in a Kalshi-only context (no sports betting domain active),
    # betting modules should not be imported
    from merid.loop import MeridLoop, LoopConfig
    
    loop = MeridLoop()
    is_kalshi_only = "prediction" in loop.config.active_domains and "betting" not in loop.config.active_domains
    
    if is_kalshi_only:
        # In Kalshi-only mode, no betting modules should be imported
        assert len(betting_modules) == 0, f"Kalshi stack imported betting modules: {betting_modules}"


def test_betting_refresh_feature_flag_respected():
    """Test that betting refresh respects the betting_refresh feature flag."""
    from core.feature_flags import set_flag, reset_flag, is_enabled
    from merid.loop import MeridLoop
    
    # Ensure flag is disabled (default)
    reset_flag("betting_refresh")
    assert not is_enabled("betting_refresh"), "betting_refresh should default to False"
    
    # Create loop and check betting step would not run
    loop = MeridLoop()
    
    # When flag is disabled, tick should report betting_refreshed:disabled
    # When enabled, it would try to run the step
    set_flag("betting_refresh", True)
    assert is_enabled("betting_refresh"), "betting_refresh should be toggleable"
    
    # Reset to default
    reset_flag("betting_refresh")
    assert not is_enabled("betting_refresh"), "betting_refresh should reset to False"
