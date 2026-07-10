"""Test edge thresholds in risk_parameters.py match moltbook research values.

This test verifies that the market entry and resting entry thresholds
in merid/event_venues/kalshi/risk_parameters.py are aligned with the
new pragmatic edge thresholds from moltbook research (2026-07-10).
"""

import pytest
from merid.event_venues.kalshi.risk_parameters import (
    EDGE_MARKET_ENTRY_BTC,
    EDGE_MARKET_ENTRY_ETH,
    EDGE_MARKET_ENTRY_SOL,
    EDGE_MARKET_ENTRY_XRP,
    EDGE_MARKET_ENTRY_DOGE,
    EDGE_RESTING_ENTRY_BTC,
    EDGE_RESTING_ENTRY_ETH,
    EDGE_RESTING_ENTRY_SOL,
    EDGE_RESTING_ENTRY_XRP,
    EDGE_RESTING_ENTRY_DOGE,
)


class TestRiskParametersEdgeThresholds:
    """Test that risk_parameters.py edge thresholds match moltbook research."""

    def test_market_entry_thresholds_match_moltbook(self):
        """Test that market entry thresholds match moltbook research values."""
        # Market entry (taker) thresholds - terminal edge values
        assert EDGE_MARKET_ENTRY_BTC == 0.0175, "BTC market entry should be 1.75%"
        assert EDGE_MARKET_ENTRY_ETH == 0.02, "ETH market entry should be 2.0%"
        assert EDGE_MARKET_ENTRY_SOL == 0.025, "SOL market entry should be 2.5%"
        assert EDGE_MARKET_ENTRY_XRP == 0.03, "XRP market entry should be 3.0%"
        assert EDGE_MARKET_ENTRY_DOGE == 0.035, "DOGE market entry should be 3.5%"

    def test_resting_entry_thresholds_match_moltbook(self):
        """Test that resting entry thresholds match moltbook research values."""
        # Resting entry (maker) thresholds - base edge values
        assert EDGE_RESTING_ENTRY_BTC == 0.0125, "BTC resting entry should be 1.25%"
        assert EDGE_RESTING_ENTRY_ETH == 0.015, "ETH resting entry should be 1.5%"
        assert EDGE_RESTING_ENTRY_SOL == 0.02, "SOL resting entry should be 2.0%"
        assert EDGE_RESTING_ENTRY_XRP == 0.0225, "XRP resting entry should be 2.25%"
        assert EDGE_RESTING_ENTRY_DOGE == 0.0275, "DOGE resting entry should be 2.75%"

    def test_edge_thresholds_increase_with_volatility(self):
        """Test that edge thresholds increase with asset volatility."""
        # Edge thresholds should scale: BTC < ETH < SOL < XRP < DOGE
        market_entries = [
            EDGE_MARKET_ENTRY_BTC,
            EDGE_MARKET_ENTRY_ETH,
            EDGE_MARKET_ENTRY_SOL,
            EDGE_MARKET_ENTRY_XRP,
            EDGE_MARKET_ENTRY_DOGE,
        ]
        
        resting_entries = [
            EDGE_RESTING_ENTRY_BTC,
            EDGE_RESTING_ENTRY_ETH,
            EDGE_RESTING_ENTRY_SOL,
            EDGE_RESTING_ENTRY_XRP,
            EDGE_RESTING_ENTRY_DOGE,
        ]
        
        # Verify monotonic increase
        for i in range(len(market_entries) - 1):
            assert market_entries[i] < market_entries[i + 1], \
                f"Market entry should increase with volatility: {market_entries[i]} < {market_entries[i + 1]}"
            assert resting_entries[i] < resting_entries[i + 1], \
                f"Resting entry should increase with volatility: {resting_entries[i]} < {resting_entries[i + 1]}"

    def test_market_entry_higher_than_resting(self):
        """Test that market entry thresholds are higher than resting (taker fee premium)."""
        assert EDGE_MARKET_ENTRY_BTC > EDGE_RESTING_ENTRY_BTC
        assert EDGE_MARKET_ENTRY_ETH > EDGE_RESTING_ENTRY_ETH
        assert EDGE_MARKET_ENTRY_SOL > EDGE_RESTING_ENTRY_SOL
        assert EDGE_MARKET_ENTRY_XRP > EDGE_RESTING_ENTRY_XRP
        assert EDGE_MARKET_ENTRY_DOGE > EDGE_RESTING_ENTRY_DOGE

    def test_edge_thresholds_not_legacy_values(self):
        """Regression test: ensure edge thresholds are NOT old Phase 1A values."""
        # Old values were 4% market, 2% resting
        assert EDGE_MARKET_ENTRY_BTC != 0.04, "BTC market entry should NOT be 4% (old Phase 1A)"
        assert EDGE_RESTING_ENTRY_BTC != 0.02, "BTC resting entry should NOT be 2% (old Phase 1A)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
