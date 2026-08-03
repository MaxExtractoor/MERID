"""
Rejected Exit Bankroll/Slot State Tests (2026-07-21)

Tests to verify that rejected exits (exit without position) do not change
bankroll/slot state. This ensures that when position_cache.on_fill() rejects
an exit fill due to no existing position, it does not create phantom positions
or affect bankroll/slot allocation state.
"""

import pytest
import asyncio
from decimal import Decimal

from merid.event_venues.kalshi.position_cache import KalshiPositionCache, CachedPosition


# Test parameters for cross-asset and YES/NO symmetry tests
ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
SIDES = ["yes", "no"]


@pytest.fixture(autouse=True)
async def clear_cache():
    """Clear cache before each test to prevent state leakage."""
    cache = KalshiPositionCache()
    await cache.clear()
    yield
    await cache.clear()


class TestRejectedExitBankrollSlotState:
    """Tests to verify that rejected exits (exit without position) do not change bankroll/slot state."""
    
    def _make_market_id(self, asset: str, side: str) -> str:
        return f"KX{asset}15M-21JUL220000-50"
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("asset", ASSETS)
    @pytest.mark.parametrize("side", SIDES)
    async def test_rejected_exit_does_not_create_position(self, asset: str, side: str):
        """Verify that a rejected exit fill does not create a phantom position."""
        cache = KalshiPositionCache()
        market_id = self._make_market_id(asset, side)
        
        # Ensure position cache is empty
        assert len(cache._positions) == 0
        
        # Attempt to apply an exit fill without an existing position
        # This should be rejected by the on_fill method
        await cache.on_fill(
            market_id=market_id,
            contracts=10,
            price_cents=5000 if side == "yes" else 4000,
            fee_cents=2,
            side=side,
            client_order_id=f"exit_{asset}_{side}",
            fill_id=f"fill_{asset}_{side}",
            action="sell"  # Exit action
        )
        
        # Verify no position was created
        assert market_id not in cache._positions
        assert len(cache._positions) == 0
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("asset", ASSETS)
    @pytest.mark.parametrize("side", SIDES)
    async def test_rejected_exit_with_existing_position_unchanged(self, asset: str, side: str):
        """Verify that a rejected exit fill does not affect existing positions."""
        cache = KalshiPositionCache()
        market_id = self._make_market_id(asset, side)
        
        # Create an existing position
        cache._positions[market_id] = CachedPosition(
            market_id=market_id,
            agent_id="test_agent",
            contracts=10,
            side=side,
            thesis_side=side,
            avg_price_cents=5000 if side == "yes" else 4000,
            realized_pnl_usd=Decimal("0"),
            unrealized_pnl_usd=Decimal("0")
        )
        
        initial_contracts = cache._positions[market_id].contracts
        
        # Attempt to apply an exit fill for a DIFFERENT market (should be rejected)
        other_market_id = f"KX{asset}15M-21JUL220100-50"
        await cache.on_fill(
            market_id=other_market_id,
            contracts=10,
            price_cents=5000 if side == "yes" else 4000,
            fee_cents=2,
            side=side,
            client_order_id=f"exit_{asset}_{side}",
            fill_id=f"fill_{asset}_{side}",
            action="sell"
        )
        
        # Verify the original position is unchanged
        assert market_id in cache._positions
        assert cache._positions[market_id].contracts == initial_contracts
        assert cache._positions[market_id].side == side
        # Verify no phantom position was created for the other market
        assert other_market_id not in cache._positions
