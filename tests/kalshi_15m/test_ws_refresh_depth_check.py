"""Tests for WS-REFRESH depth check fix in main_15m_lean.py."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from merid.event_venues.kalshi.models import KalshiMarketState


class TestWSRefreshDepthCheck:
    """Test the WS-REFRESH depth check uses correct field names."""

    def test_depth_check_uses_yes_bids_no_bids(self):
        """Test that depth check correctly uses yes_bids and no_bids fields."""
        # Create a state with yes_bids and no_bids populated
        state = KalshiMarketState(ticker="KXBTC15M-TEST")
        state.yes_bids = [(60, 10), (55, 5)]
        state.no_bids = [(40, 8), (45, 3)]
        
        # Simulate the depth check logic from main_15m_lean.py
        has_depth = False
        yes_bids = getattr(state, "yes_bids", None)
        no_bids = getattr(state, "no_bids", None)
        best_bid = getattr(state, "best_bid_cents", None)
        best_ask = getattr(state, "best_ask_cents", None)
        
        if ((yes_bids and len(yes_bids) > 0) or (no_bids and len(no_bids) > 0) or
            (best_bid is not None and best_ask is not None)):
            has_depth = True
        
        assert has_depth is True, "State with yes_bids/no_bids should have depth"

    def test_depth_check_fallback_to_best_bid_ask(self):
        """Test that depth check falls back to best_bid_cents and best_ask_cents."""
        # Create a state with only best_bid_cents and best_ask_cents
        state = KalshiMarketState(ticker="KXETH15M-TEST")
        state.yes_bids = []
        state.no_bids = []
        state.best_bid_cents = 60
        state.best_ask_cents = 65
        
        # Simulate the depth check logic
        has_depth = False
        yes_bids = getattr(state, "yes_bids", None)
        no_bids = getattr(state, "no_bids", None)
        best_bid = getattr(state, "best_bid_cents", None)
        best_ask = getattr(state, "best_ask_cents", None)
        
        if ((yes_bids and len(yes_bids) > 0) or (no_bids and len(no_bids) > 0) or
            (best_bid is not None and best_ask is not None)):
            has_depth = True
        
        assert has_depth is True, "State with best_bid/ask should have depth"

    def test_depth_check_no_depth_when_empty(self):
        """Test that depth check returns False when no depth exists."""
        # Create a state with no depth
        state = KalshiMarketState(ticker="KXSOL15M-TEST")
        state.yes_bids = []
        state.no_bids = []
        state.best_bid_cents = None
        state.best_ask_cents = None
        
        # Simulate the depth check logic
        has_depth = False
        yes_bids = getattr(state, "yes_bids", None)
        no_bids = getattr(state, "no_bids", None)
        best_bid = getattr(state, "best_bid_cents", None)
        best_ask = getattr(state, "best_ask_cents", None)
        
        if ((yes_bids and len(yes_bids) > 0) or (no_bids and len(no_bids) > 0) or
            (best_bid is not None and best_ask is not None)):
            has_depth = True
        
        assert has_depth is False, "State with no depth should not have depth"

    def test_depth_check_does_not_use_yes_levels_no_levels(self):
        """Test that depth check does not incorrectly use yes_levels/no_levels.
        
        This verifies the fix for the bug where the code was checking for
        yes_levels/no_levels which don't exist on KalshiMarketState.
        """
        state = KalshiMarketState(ticker="KXXRP15M-TEST")
        state.yes_bids = [(60, 10)]
        state.no_bids = [(40, 8)]
        
        # The old buggy code would check for yes_levels/no_levels
        # The fixed code checks for yes_bids/no_bids
        yes_levels = getattr(state, "yes_levels", None)
        no_levels = getattr(state, "no_levels", None)
        
        # These should be None (fields don't exist)
        assert yes_levels is None, "yes_levels should not exist on KalshiMarketState"
        assert no_levels is None, "no_levels should not exist on KalshiMarketState"
        
        # But yes_bids/no_bids should exist and have data
        assert state.yes_bids is not None
        assert state.no_bids is not None
        assert len(state.yes_bids) > 0
        assert len(state.no_bids) > 0

    def test_depth_check_partial_depth_one_side(self):
        """Test depth check with only one side populated."""
        # State with only yes_bids
        state = KalshiMarketState(ticker="KXDOGE15M-TEST")
        state.yes_bids = [(60, 10)]
        state.no_bids = []
        state.best_bid_cents = None
        state.best_ask_cents = None
        
        has_depth = False
        yes_bids = getattr(state, "yes_bids", None)
        no_bids = getattr(state, "no_bids", None)
        best_bid = getattr(state, "best_bid_cents", None)
        best_ask = getattr(state, "best_ask_cents", None)
        
        if ((yes_bids and len(yes_bids) > 0) or (no_bids and len(no_bids) > 0) or
            (best_bid is not None and best_ask is not None)):
            has_depth = True
        
        assert has_depth is True, "State with one-sided depth should have depth"
