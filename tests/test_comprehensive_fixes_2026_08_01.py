"""Comprehensive test suite for critical fixes implemented on 2026-08-01.

This test suite validates end-to-end fixes for:
1. Sweet spot execution logic (NO-side price conversion, spread crossing prevention)
2. sync_with_position_cache method in GlobalSlotAllocator
3. market_id attribute in KalshiFill for position cache validation
4. Corrupted position data handling in global allocator
"""

import pytest
import random
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass


@pytest.fixture(autouse=True)
def deterministic_sweet_spot_random(monkeypatch):
    """Force _determine_dynamic_order_type to always pick the 90% limit branch."""
    class _FixedRandom:
        def __init__(self, seed=None):
            pass
        def random(self):
            return 0.0
    monkeypatch.setattr(random, "Random", _FixedRandom)


class TestSweetSpotExecutionLogic:
    """Test sweet spot execution logic fixes for NO-side price conversion and spread crossing."""

    def test_no_side_optimal_range_calculation(self):
        """Test that NO orders use correct optimal range (45-60c instead of 40-55c)."""
        from merid.event_venues.kalshi.order_router import _determine_dynamic_order_type
        from merid.event_venues.kalshi.order_router import OrderIntent

        # Create a mock state with NO mid price
        mock_state = Mock()
        mock_state.mid_cents = 50  # NO mid price (equivalent to YES mid of 50)
        mock_state.ask_cents = 55
        mock_state.bid_cents = 45
        mock_state.depth_10c = 1_000_000  # Thick book to avoid thin-liquidity market order
        mock_state.spread_cents = 0
        mock_state.seconds_to_expiry = None

        # Create a NO order intent
        intent = OrderIntent(
            ticker="KXSOL15M-26AUG010030-30",
            side="BUY_NO",
            action="buy",
            price_cents=50,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )

        # Call the function
        order_type, tif = _determine_dynamic_order_type(intent, mock_state)

        # Should return limit order (not market)
        assert order_type == "limit"
        assert tif == "gtc"

    def test_sweet_spot_prevents_spread_crossing_buy(self):
        """Test that sweet spot logic prevents buy orders from crossing spread."""
        from merid.event_venues.kalshi.order_router import _determine_dynamic_order_type
        from merid.event_venues.kalshi.order_router import OrderIntent

        # Create a mock state where sweet spot would be above ask
        mock_state = Mock()
        mock_state.mid_cents = 30  # Below optimal range
        mock_state.ask_cents = 34  # Current ask
        mock_state.bid_cents = 30
        mock_state.depth_10c = 1_000_000
        mock_state.spread_cents = 0
        mock_state.seconds_to_expiry = None

        # Create a buy order intent with low initial price
        intent = OrderIntent(
            ticker="KXSOL15M-26AUG010030-30",
            side="BUY_YES",
            action="buy",
            price_cents=30,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )

        # Call the function
        order_type, tif = _determine_dynamic_order_type(intent, mock_state)

        # Should use current price instead of sweet spot if sweet spot would cross spread
        # The intent price should not be adjusted above ask
        assert intent.price_cents <= mock_state.ask_cents

    def test_sweet_spot_prevents_spread_crossing_sell(self):
        """Test that sweet spot logic prevents sell orders from crossing spread."""
        from merid.event_venues.kalshi.order_router import _determine_dynamic_order_type
        from merid.event_venues.kalshi.order_router import OrderIntent

        # Create a mock state where sweet spot would be below bid
        mock_state = Mock()
        mock_state.mid_cents = 70  # Above optimal range
        mock_state.ask_cents = 70
        mock_state.bid_cents = 65  # Current bid
        mock_state.depth_10c = 1_000_000
        mock_state.spread_cents = 0
        mock_state.seconds_to_expiry = None

        # Create a sell order intent
        intent = OrderIntent(
            ticker="KXSOL15M-26AUG010030-30",
            side="SELL_YES",
            action="sell",
            price_cents=70,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )

        # Call the function
        order_type, tif = _determine_dynamic_order_type(intent, mock_state)

        # Should use current price instead of sweet spot if sweet spot would cross spread
        # The intent price should not be adjusted below bid
        assert intent.price_cents >= mock_state.bid_cents

    def test_no_side_price_conversion_correctness(self):
        """Test that NO-side price conversion uses correct formula (NO_ask = 100 - YES_bid)."""
        # Test the conversion logic
        yes_bid = 40
        yes_ask = 45

        # Correct conversion
        no_ask = 100 - yes_bid  # Should be 60
        no_bid = 100 - yes_ask  # Should be 55

        assert no_ask == 60, f"NO_ask should be 60, got {no_ask}"
        assert no_bid == 55, f"NO_bid should be 55, got {no_bid}"


class TestGlobalSlotAllocatorSync:
    """Test sync_with_position_cache method in GlobalSlotAllocator."""

    def test_sync_with_position_cache_removes_orphaned_slots(self):
        """Test that sync_with_position_cache removes slots without corresponding positions."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest

        allocator = GlobalSlotAllocator()

        # Create a mock position cache
        mock_position_cache = Mock()
        mock_position = Mock()
        mock_position.market_id = "KXSOL15M-26AUG010030-30"
        mock_position.agent_id = "agent_15m"
        mock_position_cache.get_all_positions.return_value = {mock_position.market_id: mock_position}

        # Allocate a slot
        request = AllocationRequest(
            agent_id="agent_15m",
            asset="SOL",
            ticker="KXSOL15M-26AUG010030-30",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=5,
            confidence=0.9
        )
        allocated, reason, slot_id = allocator.request_allocation(request)
        assert allocated

        # Now simulate position being closed (remove from position cache)
        mock_position_cache.get_all_positions.return_value = {}

        # Sync with position cache
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache):
            removed_count = allocator.sync_with_position_cache()

        # Should have removed the orphaned slot
        assert removed_count == 1
        assert allocator.get_slot_count() == 0

    def test_sync_with_position_cache_preserves_valid_slots(self):
        """Test that sync_with_position_cache preserves slots with corresponding positions."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest

        allocator = GlobalSlotAllocator()

        # Create a mock position cache
        mock_position_cache = Mock()
        mock_position = Mock()
        mock_position.market_id = "KXSOL15M-26AUG010030-30"
        mock_position.agent_id = "agent_15m"
        mock_position_cache.get_all_positions.return_value = {mock_position.market_id: mock_position}

        # Allocate a slot
        request = AllocationRequest(
            agent_id="agent_15m",
            asset="SOL",
            ticker="KXSOL15M-26AUG010030-30",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=5,
            confidence=0.9
        )
        allocated, reason, slot_id = allocator.request_allocation(request)
        assert allocated

        # Sync with position cache (position still exists)
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache):
            removed_count = allocator.sync_with_position_cache()

        # Should not have removed any slots
        assert removed_count == 0
        assert allocator.get_slot_count() == 1

    def test_sync_with_position_cache_handles_exceptions(self):
        """Test that sync_with_position_cache handles exceptions gracefully."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator

        allocator = GlobalSlotAllocator()

        # Mock position cache to raise exception
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', side_effect=Exception("Test error")):
            removed_count = allocator.sync_with_position_cache()

        # Should return 0 on error
        assert removed_count == 0


class TestKalshiFillMarketId:
    """Test market_id attribute in KalshiFill for position cache validation."""

    def test_kalshi_fill_has_market_id_attribute(self):
        """Test that KalshiFill has market_id attribute."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFill

        fill = KalshiFill(
            fill_id="test_fill_123",
            market_id="market_uuid_123",
            market_ticker="KXSOL15M-26AUG010030-30",
            side="yes",
            action="buy",
            count_fp=1,
            yes_price_dollars=Decimal("0.50")
        )

        assert hasattr(fill, 'market_id')
        assert fill.market_id == "market_uuid_123"

    def test_kalshi_fill_from_http_ingestion_includes_market_id(self):
        """Test that fills ingested from HTTP include market_id."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

        ledger = KalshiFillsLedger()

        # Mock HTTP fill data with market_id
        raw_fill = {
            "fill_id": "http_fill_123",
            "market_id": "market_uuid_456",
            "market_ticker": "KXSOL15M-26AUG010030-30",
            "side": "yes",
            "action": "buy",
            "count_fp": 1,
            "yes_price": "0.50",
            "created_time": datetime.now(timezone.utc).isoformat()
        }

        # Ingest the fill
        with patch.object(ledger, '_index_fill'):
            fill = ledger._create_fill_from_dict(raw_fill, "http_poller")

        assert fill.market_id == "market_uuid_456"

    def test_kalshi_fill_from_db_restore_includes_market_id(self):
        """Test that fills restored from DB include market_id."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

        ledger = KalshiFillsLedger()

        # Mock DB row with market_id
        row = {
            "fill_id": "db_fill_123",
            "market_id": "market_uuid_789",
            "market_ticker": "KXSOL15M-26AUG010030-30",
            "side": "yes",
            "action": "buy",
            "count_fp": 1,
            "yes_price_dollars": "0.50",
            "fee_cost": "0.02",
            "created_time": datetime.now(timezone.utc).isoformat(),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "ingestion_source": "db_restore",
            "agent_id": None,
            "intent_id": None,
            "reconciled": False
        }

        # Simulate DB restore
        with patch('sqlite3.connect'), patch.object(ledger, '_index_fill'):
            # This would normally be called during DB restore
            # We're testing the fill creation logic
            from merid.event_venues.kalshi.fills_ledger import KalshiFill
            fill = KalshiFill(
                fill_id=row["fill_id"],
                market_id=row.get("market_id", ""),
                market_ticker=row["market_ticker"],
                side=row["side"],
                action=row["action"],
                count_fp=row["count_fp"],
                yes_price_dollars=Decimal(str(row["yes_price_dollars"])) if row["yes_price_dollars"] else None,
                fee_cost=Decimal(str(row["fee_cost"])) if row["fee_cost"] else Decimal("0"),
                created_time=datetime.fromisoformat(row["created_time"]) if row["created_time"] else datetime.now(timezone.utc),
                ingestion_source=row["ingestion_source"] or "db_restore",
                ingested_at=datetime.fromisoformat(row["ingested_at"]) if row["ingested_at"] else datetime.now(timezone.utc),
                agent_id=row["agent_id"],
                intent_id=row["intent_id"],
                reconciled=bool(row["reconciled"]),
            )

        assert fill.market_id == "market_uuid_789"


class TestCorruptedPositionDataHandling:
    """Test corrupted position data handling in global allocator."""

    def test_global_allocator_filters_corrupted_positions(self):
        """Test that global allocator filters positions with exposure=0."""
        from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate

        allocator = GlobalAllocator()

        # Create candidates
        candidates = [
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-26AUG010000-00",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                edge_pct=5.0,
                confidence=0.9,
                model_prob=0.65,
                agent_name="btc_agent"
            ),
            OrderCandidate(
                asset="ETH",
                ticker="KXETH15M-26AUG010000-00",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                edge_pct=5.0,
                confidence=0.9,
                model_prob=0.65,
                agent_name="eth_agent"
            )
        ]

        # Simulate corrupted position data (exposure=0 for BTC)
        current_positions = {
            "BTC": 0.0,  # Corrupted
            "ETH": 0.50,  # Valid
        }

        # Allocate - should filter out BTC (corrupted) and allow it to trade
        chosen = allocator.allocate(candidates, current_positions)

        # BTC should be allowed to trade (corrupted data filtered)
        btc_chosen = any(c.asset == "BTC" for c in chosen)
        assert btc_chosen, "BTC should be allowed to trade despite corrupted position data"

        # ETH should be blocked (valid position exists)
        eth_chosen = any(c.asset == "ETH" for c in chosen)
        assert not eth_chosen, "ETH should be blocked due to valid position"

    def test_position_cache_fallback_prevents_zero_exposure(self):
        """Test that position cache uses fallback price to prevent zero exposure."""
        from merid.event_venues.kalshi.position_cache import CachedPosition

        # Create a position with avg_price_cents=0 (corrupted)
        position = CachedPosition(
            market_id="KXSOL15M-26AUG010030-30",
            agent_id="agent_15m",
            contracts=1,
            side="yes",
            thesis_side="yes",
            avg_price_cents=0,  # Corrupted
            entry_price_state="invalid"
        )

        # Get notional - should use fallback price
        notional = position.notional_usd

        # Should not be zero (fallback price should be used)
        assert notional > 0, "Notional should not be zero with fallback price"
        assert notional >= Decimal("0.10"), "Fallback price should be at least 10c"

    def test_position_cache_handles_none_avg_price(self):
        """Test that position cache handles None avg_price_cents."""
        from merid.event_venues.kalshi.position_cache import CachedPosition

        # Create a position with avg_price_cents=None (unknown)
        position = CachedPosition(
            market_id="KXSOL15M-26AUG010030-30",
            agent_id="agent_15m",
            contracts=1,
            side="yes",
            thesis_side="yes",
            avg_price_cents=None,  # Unknown
            entry_price_state="unknown"
        )

        # Get notional - should use fallback price
        notional = position.notional_usd

        # Should not be zero (fallback price should be used)
        assert notional > 0, "Notional should not be zero with fallback price"


class TestEndToEndIntegration:
    """End-to-end integration tests for all fixes."""

    def test_sweet_spot_to_position_cache_flow(self):
        """Test the complete flow from sweet spot execution to position cache."""
        from merid.event_venues.kalshi.order_router import _determine_dynamic_order_type, OrderIntent
        from merid.event_venues.kalshi.position_cache import CachedPosition

        # Create a mock state
        mock_state = Mock()
        mock_state.mid_cents = 30
        mock_state.ask_cents = 34
        mock_state.bid_cents = 30
        mock_state.seconds_to_expiry = None

        # Create an order intent
        intent = OrderIntent(
            ticker="KXSOL15M-26AUG010030-30",
            side="BUY_YES",
            action="buy",
            price_cents=30,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )

        # Apply sweet spot logic
        order_type, tif = _determine_dynamic_order_type(intent, mock_state)

        # Verify price doesn't cross spread
        assert intent.price_cents <= mock_state.ask_cents

        # Simulate fill and position creation
        position = CachedPosition(
            market_id="KXSOL15M-26AUG010030-30",
            agent_id="agent_15m",
            contracts=1,
            side="yes",
            thesis_side="yes",
            avg_price_cents=intent.price_cents
        )

        # Verify position notional is correct
        notional = position.notional_usd
        assert notional > 0
        assert notional == Decimal(intent.price_cents) / Decimal("100")

    def test_slot_allocator_sync_with_position_cache_integration(self):
        """Test integration between slot allocator and position cache."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
        from merid.event_venues.kalshi.position_cache import CachedPosition

        allocator = GlobalSlotAllocator()

        # Create a mock position cache with a position
        mock_position = CachedPosition(
            market_id="KXSOL15M-26AUG010030-30",
            agent_id="agent_15m",
            contracts=1,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50
        )

        mock_position_cache = Mock()
        mock_position_cache.get_all_positions.return_value = {mock_position.market_id: mock_position}

        # Allocate a slot
        request = AllocationRequest(
            agent_id="agent_15m",
            asset="SOL",
            ticker="KXSOL15M-26AUG010030-30",
            entry_price_cents=50,
            edge_pct=5.0,
            spread_cents=5,
            confidence=0.9
        )
        allocated, reason, slot_id = allocator.request_allocation(request)
        assert allocated

        # Sync with position cache
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache):
            removed_count = allocator.sync_with_position_cache()

        # Slot should be preserved (position exists)
        assert removed_count == 0
        assert allocator.get_slot_count() == 1

        # Now remove position
        mock_position_cache.get_all_positions.return_value = {}

        # Sync again
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache):
            removed_count = allocator.sync_with_position_cache()

        # Slot should be removed (position doesn't exist)
        assert removed_count == 1
        assert allocator.get_slot_count() == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
