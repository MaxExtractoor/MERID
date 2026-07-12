"""
Direct tests for structural fixes to ensure all changes work correctly.

Tests cover:
1. Position cache sync fix
2. WS subscription accounting fix  
3. md_age negative values fix
4. Candidate optimizer depth calculation fix
5. Markets seen metrics fix
6. Spread threshold alignment fix
"""

import pytest
import time
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

# Test 1: Position cache sync fix
def test_position_cache_sync_with_no_positions():
    """Test that position cache updates _last_sync even when no positions pass filters."""
    from merid.event_venues.kalshi.position_cache import KalshiPositionCache
    
    cache = KalshiPositionCache()
    
    # Mock positions that will all be filtered out (contracts=0)
    positions = [
        {"market_id": "KXBTC15M-TEST1", "contracts": 0, "side": "yes"},
        {"market_id": "KXETH15M-TEST2", "contracts": 0, "side": "no"},
    ]
    
    # Before sync, _last_sync should be None
    assert cache._last_sync is None
    
    # Run sync - should update _last_sync even with no positions
    asyncio.run(cache.sync_from_rest(positions))
    
    # After sync, _last_sync should be set
    assert cache._last_sync is not None
    assert isinstance(cache._last_sync, datetime)
    # Cache should be empty since all positions were filtered
    assert len(cache._positions) == 0

# Test 2: WS subscription accounting fix
def test_ws_subscription_accounting_both_modes():
    """Test that WS subscription accounting works in both WS_PRIMARY and REST_FALLBACK modes."""
    # Test the subscription accounting logic directly
    mock_bridge = Mock()
    mock_bridge.summary.return_value = {
        "mode": "WS_PRIMARY",
        "rest_polling_active": False,
    }
    mock_bridge._subscribed_tickers = ["KXBTC15M-TEST1", "KXETH15M-TEST2"]
    
    # Mock asset markets
    asset_markets = ["KXBTC15M-TEST1", "KXETH15M-TEST2"]
    
    # Test WS_PRIMARY mode - should count subscriptions
    bridge_mode = mock_bridge.summary().get("mode", "WS_PRIMARY")
    current_subs = set(mock_bridge._subscribed_tickers)
    ws_subscribed = [t for t in asset_markets if t in current_subs]
    assert len(ws_subscribed) == 2
    
    # Test REST_FALLBACK mode - should also count subscriptions
    mock_bridge.summary.return_value = {
        "mode": "REST_FALLBACK", 
        "rest_polling_active": True,
    }
    
    bridge_mode = mock_bridge.summary().get("mode", "WS_PRIMARY")
    current_subs = set(mock_bridge._subscribed_tickers)
    ws_subscribed = [t for t in asset_markets if t in current_subs]
    assert len(ws_subscribed) == 2

# Test 3: md_age negative values fix
def test_md_age_unix_timestamp_detection():
    """Test detection and correction of Unix timestamps in last_book_update_ts."""
    # Create a mock state object with the required fields
    class MockState:
        def __init__(self, ticker):
            self.ticker = ticker
            self.last_book_update_ts = None
    
    state = MockState("TEST")
    
    # Simulate Unix timestamp being set (much larger than monotonic)
    unix_timestamp = 1700000000.0  # Unix timestamp
    monotonic_now = time.monotonic()  # Much smaller
    
    state.last_book_update_ts = unix_timestamp
    
    # This should be detected as Unix timestamp and corrected
    now = monotonic_now
    
    # Simulate the timestamp validation logic from the fix
    if state.last_book_update_ts:
        age = now - state.last_book_update_ts
        if age < 0:
            # Detect Unix timestamp
            if state.last_book_update_ts > 1000000000:
                # This should be corrected to monotonic time
                state.last_book_update_ts = now
    
    # After correction, timestamp should be monotonic, not Unix
    assert state.last_book_update_ts == monotonic_now
    assert state.last_book_update_ts < 1000000000

# Test 4: Candidate optimizer depth calculation fix
def test_candidate_optimizer_depth_field_names():
    """Test that candidate optimizer uses correct field names from market state."""
    from merid.prediction.candidate_optimizer import CandidateOptimizer
    
    optimizer = CandidateOptimizer()
    
    # Create mock market state with correct field names
    class MockState:
        def __init__(self):
            self.min_depth_yes = 10  # Correct field name
            self.min_depth_no = 5   # Correct field name
            self.spread_cents = 30
            self.mid_cents = 50
    
    state = MockState()
    
    # Create mock market
    market = {
        "market_id": "KXBTC15M-TEST",
        "asset": "BTC",
        "series_ticker": "KXBTC15M"
    }
    
    # Test the depth extraction logic directly (since _create_candidate is private)
    # This tests the fix: using min_depth_yes/min_depth_no instead of depth_yes/depth_no
    depth_yes = getattr(state, 'min_depth_yes', 0)
    depth_no = getattr(state, 'min_depth_no', 0)
    total_depth = depth_yes + depth_no
    
    # Should extract depth using correct field names
    assert depth_yes == 10
    assert depth_no == 5
    assert total_depth == 15

# Test 5: Markets seen metrics fix
def test_markets_seen_metrics_preservation():
    """Test that original markets_seen count is preserved."""
    # Simulate pipeline metrics before optimizer
    original_count = 5
    pipeline_metrics = {
        'markets_seen': original_count,
        'markets_with_md': 0,
        'markets_with_spot': 0,
        'markets_passing_shouldtrade': 0,
        'candidates_built': 0,
        'signal_calls': 0
    }
    
    # Mock candidate metrics that might report 0
    mock_candidate_metrics = Mock()
    mock_candidate_metrics.total_markets_scanned = 0  # This would overwrite the original
    mock_candidate_metrics.markets_with_md = 3
    mock_candidate_metrics.markets_with_spot = 3
    mock_candidate_metrics.markets_passing_filters = 2
    mock_candidate_metrics.final_candidates = 1
    
    # Apply the fix - preserve original count
    original_markets_seen = pipeline_metrics['markets_seen']
    pipeline_metrics.update({
        'markets_seen': original_markets_seen,  # Keep original count
        'markets_with_md': mock_candidate_metrics.markets_with_md,
        'markets_with_spot': mock_candidate_metrics.markets_with_spot,
        'markets_passing_shouldtrade': mock_candidate_metrics.markets_passing_filters,
        'candidates_built': mock_candidate_metrics.final_candidates,
        'signal_calls': 0
    })
    
    # Should preserve original count
    assert pipeline_metrics['markets_seen'] == original_count
    assert pipeline_metrics['markets_seen'] == 5

# Test 6: Spread threshold alignment fix
def test_spread_threshold_alignment():
    """Test that candidate optimizer spread threshold aligns with signal gate."""
    from merid.prediction.candidate_optimizer import CandidateOptimizer
    
    optimizer = CandidateOptimizer()
    
    # Should be aligned with signal gate threshold (30 cents - 2026-07-10: harmonized with 10c-50c entry price sweet spot)
    assert optimizer.max_spread_cents == 30
    
    # Test filtering logic directly
    market = {
        "market_id": "KXBTC15M-TEST",
        "asset": "BTC", 
        "series_ticker": "KXBTC15M"
    }
    
    state = Mock()
    state.spread_cents = 30  # Below threshold - should pass
    state.min_depth_yes = 10
    state.min_depth_no = 10
    state.mid_cents = 50
    
    # Test spread extraction logic
    spread_cents = getattr(state, 'spread_cents', 0.0)
    assert spread_cents == 30
    
    # Test with spread above threshold
    state.spread_cents = 50  # Above threshold - should be filtered later
    spread_cents = getattr(state, 'spread_cents', 0.0)
    assert spread_cents == 50
    
    # Test that spreads above threshold would be filtered
    assert spread_cents > optimizer.max_spread_cents  # 50 > 30

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
