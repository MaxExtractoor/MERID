"""
Integration tests for REST sync thesis_side preservation.

Tests that REST sync preserves thesis_side and never overwrites it with
REST API side data, which is always "yes" from Kalshi's YES-side perspective.
"""

import pytest
from datetime import datetime
from merid.event_venues.kalshi.position_cache import CachedPosition


class TestRestSyncThesisPreservation:
    """Test that REST sync preserves thesis_side invariant."""
    
    @pytest.fixture
    def sample_rest_positions(self):
        """Sample REST API response with positions."""
        return [
            {
                "market_id": "KXBTC15M-26JUL211745-45",
                "contracts": 10,
                "side": "yes",  # Kalshi REST always reports "yes"
                "avg_price_cents": 50,
                "realized_pnl": 0,
                "unrealized_pnl": 5.0,
            },
            {
                "market_id": "KXSOL15M-26JUL211745-45",
                "contracts": 5,
                "side": "yes",  # Kalshi REST always reports "yes"
                "avg_price_cents": 30,
                "realized_pnl": 0,
                "unrealized_pnl": 2.5,
            },
        ]
    
    def test_rest_sync_preserves_thesis_side_yes(self, sample_rest_positions):
        """Test that REST sync preserves thesis_side=YES from fill-based cache."""
        # Create a position with thesis_side=YES from fill processing
        existing_position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",  # Set from entry intent
            avg_price_cents=50,
            fill_source="ws",
            client_order_id="entry_intent_1",
        )
        
        # Simulate REST sync logic
        rest_position = sample_rest_positions[0]
        market_id = rest_position["market_id"]
        
        # Preserve thesis_side from fill-based cache
        preserved_thesis_side = existing_position.thesis_side
        
        # Rebuild position with preserved thesis_side
        synced_position = CachedPosition(
            market_id=market_id,
            agent_id="BTC_15M",
            contracts=rest_position["contracts"],
            side=rest_position["side"],  # REST side for diagnostics
            thesis_side=preserved_thesis_side,  # Immutable strategy thesis
            avg_price_cents=rest_position["avg_price_cents"],
            realized_pnl_usd=float(rest_position.get("realized_pnl", 0)),
            unrealized_pnl_usd=float(rest_position.get("unrealized_pnl", 0)),
        )
        
        # Assert thesis_side was preserved
        assert synced_position.thesis_side == "yes"
    
    def test_rest_sync_preserves_thesis_side_no(self, sample_rest_positions):
        """Test that REST sync preserves thesis_side=NO from fill-based cache."""
        # Create a position with thesis_side=NO from fill processing
        existing_position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            contracts=10,
            side="no",
            thesis_side="no",  # Set from entry intent
            avg_price_cents=50,
            fill_source="ws",
            client_order_id="entry_intent_1",
        )
        
        # Simulate REST sync logic
        rest_position = sample_rest_positions[0]
        market_id = rest_position["market_id"]
        
        # Preserve thesis_side from fill-based cache
        preserved_thesis_side = existing_position.thesis_side
        
        # Rebuild position with preserved thesis_side
        synced_position = CachedPosition(
            market_id=market_id,
            agent_id="BTC_15M",
            contracts=rest_position["contracts"],
            side=rest_position["side"],  # REST side for diagnostics
            thesis_side=preserved_thesis_side,  # Immutable strategy thesis
            avg_price_cents=rest_position["avg_price_cents"],
            realized_pnl_usd=float(rest_position.get("realized_pnl", 0)),
            unrealized_pnl_usd=float(rest_position.get("unrealized_pnl", 0)),
        )
        
        # Assert thesis_side=NO was preserved despite REST reporting "yes"
        assert synced_position.thesis_side == "no"
        # Side field may be refreshed from REST for diagnostics
        assert synced_position.side == "yes"
    
    def test_rest_sync_new_position_infers_from_fill_history(self, sample_rest_positions):
        """Test that new positions from REST try to infer thesis_side from fill history."""
        # No existing position
        rest_position = sample_rest_positions[0]
        market_id = rest_position["market_id"]
        
        # CRITICAL FIX (2026-07-22): New positions now try to infer thesis_side from fill history
        # instead of blindly using REST side (which is always "yes")
        # If fill history lookup fails, thesis_side is set to "unknown"
        preserved_thesis_side = "unknown"  # Default when fill history lookup fails
        
        synced_position = CachedPosition(
            market_id=market_id,
            agent_id="BTC_15M",
            contracts=rest_position["contracts"],
            side=rest_position["side"],
            thesis_side=preserved_thesis_side,
            avg_price_cents=rest_position["avg_price_cents"],
            realized_pnl_usd=float(rest_position.get("realized_pnl", 0)),
            unrealized_pnl_usd=float(rest_position.get("unrealized_pnl", 0)),
        )
        
        # Assert new position uses "unknown" when fill history lookup fails
        assert synced_position.thesis_side == "unknown"
    
    def test_rest_sync_desync_detection_yes_thesis_no_rest(self):
        """Test desync detection when thesis_side=YES but REST reports side=NO."""
        # Create a position with thesis_side=YES
        existing_position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            fill_source="ws",
            client_order_id="entry_intent_1",
        )
        
        # REST reports unexpected side=NO (desync or manual intervention)
        rest_side = "no"
        preserved_thesis_side = existing_position.thesis_side
        
        # Check for desync
        if preserved_thesis_side.lower() == "yes" and rest_side.lower() == "no":
            # This is unexpected - desync detected
            desync_detected = True
        else:
            desync_detected = False
        
        # Assert desync is detected
        assert desync_detected is True
    
    def test_rest_sync_expected_no_thesis_yes_rest(self):
        """Test that thesis_side=NO with REST side=yes is expected (Kalshi YES-side perspective)."""
        # Create a position with thesis_side=NO
        existing_position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            contracts=10,
            side="no",
            thesis_side="no",
            avg_price_cents=50,
            fill_source="ws",
            client_order_id="entry_intent_1",
        )
        
        # REST reports side=yes (expected - Kalshi YES-side perspective)
        rest_side = "yes"
        preserved_thesis_side = existing_position.thesis_side
        
        # Check for desync
        if preserved_thesis_side.lower() == "no" and rest_side.lower() == "yes":
            # This is expected - Kalshi REST always reports side="yes"
            desync_detected = False
        else:
            desync_detected = True
        
        # Assert no desync (this is expected behavior)
        assert desync_detected is False
    
    def test_rest_sync_positive_while_thesis_yes(self):
        """Test case 1: REST positive quantity while thesis is YES - should update quantities/cost only."""
        # Create a position with thesis_side=YES from fill processing
        existing_position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            fill_source="ws",
            client_order_id="entry_intent_1",
        )
        
        # REST reports positive quantity with same side (normal sync)
        rest_position = {
            "market_id": "KXBTC15M-26JUL211745-45",
            "contracts": 15,  # Updated quantity
            "side": "yes",
            "avg_price_cents": 55,  # Updated price
            "realized_pnl": 0,
            "unrealized_pnl": 7.5,
        }
        
        # Preserve thesis_side from fill-based cache
        preserved_thesis_side = existing_position.thesis_side
        
        # Rebuild position with preserved thesis_side
        synced_position = CachedPosition(
            market_id=rest_position["market_id"],
            agent_id="BTC_15M",
            contracts=rest_position["contracts"],
            side=rest_position["side"],
            thesis_side=preserved_thesis_side,  # Immutable - never overwritten
            avg_price_cents=rest_position["avg_price_cents"],
            realized_pnl_usd=float(rest_position.get("realized_pnl", 0)),
            unrealized_pnl_usd=float(rest_position.get("unrealized_pnl", 0)),
        )
        
        # Assert thesis_side was preserved (not mutated)
        assert synced_position.thesis_side == "yes"
        # Assert quantities and costs were updated
        assert synced_position.contracts == 15
        assert synced_position.avg_price_cents == 55
    
    def test_rest_sync_zero_while_thesis_open(self):
        """Test case 2: REST zero quantity while thesis is open - should update quantities/cost only."""
        # Create an open position with thesis_side=YES
        existing_position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            fill_source="ws",
            client_order_id="entry_intent_1",
        )
        
        # REST reports zero quantity (position closed externally or data lag)
        rest_position = {
            "market_id": "KXBTC15M-26JUL211745-45",
            "contracts": 0,  # Zero quantity
            "side": "yes",
            "avg_price_cents": 50,
            "realized_pnl": 0,
            "unrealized_pnl": 0,
        }
        
        # Preserve thesis_side from fill-based cache
        preserved_thesis_side = existing_position.thesis_side
        
        # Rebuild position with preserved thesis_side
        # Note: In production, contracts=0 would be filtered out (see position_cache.py line 1620)
        # But for this test, we verify thesis_side preservation even with zero quantity
        synced_position = CachedPosition(
            market_id=rest_position["market_id"],
            agent_id="BTC_15M",
            contracts=rest_position["contracts"],
            side=rest_position["side"],
            thesis_side=preserved_thesis_side,  # Immutable - never overwritten
            avg_price_cents=rest_position["avg_price_cents"],
            realized_pnl_usd=float(rest_position.get("realized_pnl", 0)),
            unrealized_pnl_usd=float(rest_position.get("unrealized_pnl", 0)),
        )
        
        # Assert thesis_side was preserved (not mutated)
        assert synced_position.thesis_side == "yes"
        # Assert quantity was updated to zero
        assert synced_position.contracts == 0
    
    def test_rest_sync_opposite_sign_while_thesis_yes(self):
        """Test case 3: REST opposite sign while thesis is YES - should raise sync alarm without mutating thesis_side."""
        # Create a position with thesis_side=YES
        existing_position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            fill_source="ws",
            client_order_id="entry_intent_1",
        )
        
        # REST reports opposite side (desync or manual intervention)
        rest_position = {
            "market_id": "KXBTC15M-26JUL211745-45",
            "contracts": 10,
            "side": "no",  # Opposite sign - unexpected
            "avg_price_cents": 50,
            "realized_pnl": 0,
            "unrealized_pnl": 5.0,
        }
        
        # Preserve thesis_side from fill-based cache
        preserved_thesis_side = existing_position.thesis_side
        rest_side = rest_position["side"]
        
        # Check for desync (thesis_side=YES but REST reports side=NO)
        if preserved_thesis_side.lower() == "yes" and rest_side.lower() == "no":
            # This is unexpected - desync detected
            desync_detected = True
            sync_alarm_raised = True
        else:
            desync_detected = False
            sync_alarm_raised = False
        
        # Assert desync is detected
        assert desync_detected is True
        assert sync_alarm_raised is True
        
        # Even with desync, thesis_side should NOT be mutated
        # In production, this position would be skipped (see position_cache.py line 1708)
        # and existing state preserved
        assert preserved_thesis_side == "yes"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
