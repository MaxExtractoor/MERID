"""End-to-end smoke tests for Kalshi integration.

Test Cases:
1. Full pipeline: signal generation → reconciliation check
2. Signal store persistence
3. Venue adapter → reconciliation flow
4. Consensus bridge integration
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch








@pytest.mark.asyncio
async def test_kalshi_full_loop_integration():
    """End-to-end: Simulate full loop cycle with Kalshi."""
    from merid.loop import MeridLoop
    import time
    
    loop = MeridLoop()
    summary = {"actions": []}
    now = time.time()
    
    with patch("merid.signals.store.get_signal_store") as mock_store, \
         patch("merid.signals.features.FeatureService") as mock_fs, \
         patch("merid.signals.live_feeds.get_live_feed_manager") as mock_lfm, \
         patch("merid.prediction.agent_grid.get_agent_grid") as mock_grid, \
         patch("merid.signals.kalshi_signals.get_kalshi_venue_adapter") as mock_adapter:
        
        # Mock all dependencies
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
        
        grid = MagicMock()
        grid._running = True
        grid.agents = []
        mock_grid.return_value = grid
        
        adapter = MagicMock()
        adapter.list_instruments = AsyncMock(return_value=[])
        mock_adapter.return_value = adapter
        
        # Run full cycle steps
        await loop._refresh_features(now, summary)
        await loop._run_agent_cycles(summary)
        
        # Verify actions were recorded
        assert len(summary["actions"]) > 0
        
        # Should have feature refresh and potentially Kalshi signals
        actions_str = str(summary["actions"])
        assert "features_refreshed" in actions_str or "kalshi" in actions_str.lower()


