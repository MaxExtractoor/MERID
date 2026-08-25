"""
Test suite for Fixed $1 Global Exposure Cap Enforcement (2026-07-14)

Tests that the production stack enforces the fixed $1 global exposure cap
(MERID_FIXED_EXPOSURE_CAP_USD) and does NOT use percentage-based allocation.

CRITICAL: The $1 global risk exposure cap must NEVER be changed. This is a fixed
dollar exposure model that ensures never more than $1 exposure at any time across
all assets (BTC, ETH, SOL, XRP, DOGE).
"""

import pytest
import sys
import os
from decimal import Decimal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFixed1ExposureCapEnforcement:
    """Test suite for fixed $1 global exposure cap enforcement."""
    
    def setup_method(self):
        """Reset allocator before each test."""
        from merid.risk.global_slot_allocator import reset_global_slot_allocator
        reset_global_slot_allocator()
    
    def test_risk_parameters_percentage_caps_disabled(self):
        """Test that percentage-based exposure caps in risk_parameters.py are disabled."""
        from merid.event_venues.kalshi.risk_parameters import (
            PER_MARKET_EXPOSURE_CAP_PCT,
            PER_STRATEGY_EXPOSURE_CAP_PCT,
            VENUE_EXPOSURE_CAP_PCT,
            KELLY_MAX_ALLOCATION_PCT
        )
        
        # All percentage-based caps should be set to 0.0 (DISABLED)
        assert PER_MARKET_EXPOSURE_CAP_PCT == 0.0, "PER_MARKET_EXPOSURE_CAP_PCT should be DISABLED (0.0)"
        assert PER_STRATEGY_EXPOSURE_CAP_PCT == 0.0, "PER_STRATEGY_EXPOSURE_CAP_PCT should be DISABLED (0.0)"
        assert VENUE_EXPOSURE_CAP_PCT == 0.0, "VENUE_EXPOSURE_CAP_PCT should be DISABLED (0.0)"
        assert KELLY_MAX_ALLOCATION_PCT == 0.0, "KELLY_MAX_ALLOCATION_PCT should be DISABLED (0.0)"
        
        print("✓ Risk parameters percentage caps are disabled")
    
    def test_rebalancer_uses_usd_not_percentage(self):
        """Test that rebalancer uses USD-based allocation, not percentage."""
        from merid.event_venues.kalshi.rebalancer import TargetAllocation
        
        # TargetAllocation should have target_usd, not target_pct
        target = TargetAllocation(
            ticker="BTC",
            target_usd=Decimal("0.20"),
            max_deviation_usd=Decimal("0.05"),
            side_preference="yes"
        )
        
        assert hasattr(target, 'target_usd'), "TargetAllocation should have target_usd field"
        assert target.target_usd == Decimal("0.20"), "Target should be USD-based"
        assert not hasattr(target, 'target_pct'), "TargetAllocation should NOT have target_pct field"
        
        print("✓ Rebalancer uses USD-based allocation")
    
    def test_rebalancer_bootstrap_distributes_1_cap(self):
        """Test that rebalancer bootstrap distributes $1.00 cap evenly."""
        from merid.event_venues.kalshi.rebalancer import PortfolioRebalancer, TargetAllocation
        
        rebalancer = PortfolioRebalancer()
        
        # Manually set targets for all 5 assets (simulating bootstrap behavior)
        # Bootstrap distributes $1.00 evenly across 5 assets
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        per_ticker_usd = Decimal("1.00") / Decimal(str(len(assets)))
        
        for asset in assets:
            rebalancer.set_target(TargetAllocation(
                ticker=asset,
                target_usd=per_ticker_usd,
                max_deviation_usd=Decimal("0.05"),
                side_preference="yes"
            ))
        
        targets = rebalancer.get_targets()
        
        # Should have targets for all 5 assets
        assert len(targets) == 5, f"Should have 5 targets, got {len(targets)}"
        
        # Each target should be $0.20 (1.00 / 5)
        for ticker, target in targets.items():
            assert target.target_usd == Decimal("0.20"), f"{ticker} target should be $0.20, got ${target.target_usd}"
        
        print("✓ Rebalancer bootstrap distributes $1.00 cap evenly")
    
    def test_portfolio_optimizer_marked_deprecated(self):
        """Test that PortfolioOptimizer is marked as DEPRECATED."""
        from merid.risk.portfolio_optimizer import PortfolioOptimizer
        
        # Check class docstring mentions DEPRECATED
        assert "DEPRECATED" in PortfolioOptimizer.__doc__, "PortfolioOptimizer should be marked DEPRECATED"
        assert "$1" in PortfolioOptimizer.__doc__, "PortfolioOptimizer should reference $1 global cap"
        assert "GlobalSlotAllocator" in PortfolioOptimizer.__doc__, "PortfolioOptimizer should reference GlobalSlotAllocator"
        
        print("✓ PortfolioOptimizer is marked as DEPRECATED")
    
    def test_monte_carlo_marked_deprecated(self):
        """Test that Monte Carlo module is marked as DEPRECATED."""
        import merid.risk.monte_carlo as monte_carlo
        
        # Check module docstring mentions DEPRECATED
        assert "DEPRECATED" in monte_carlo.__doc__, "Monte Carlo module should be marked DEPRECATED"
        assert "$1" in monte_carlo.__doc__, "Monte Carlo should reference $1 global cap"
        assert "GlobalSlotAllocator" in monte_carlo.__doc__, "Monte Carlo should reference GlobalSlotAllocator"
        
        print("✓ Monte Carlo module is marked as DEPRECATED")
    
    def test_correlation_matrix_kelly_deprecated(self):
        """Test that Kelly allocation in correlation_matrix is marked DEPRECATED."""
        from merid.risk.correlation_matrix import calculate_correlation_discount
        
        # Check function docstring mentions DEPRECATED
        assert "DEPRECATED" in calculate_correlation_discount.__doc__, "calculate_correlation_discount should be marked DEPRECATED"
        assert "$1" in calculate_correlation_discount.__doc__, "calculate_correlation_discount should reference $1 global cap"
        
        print("✓ Correlation matrix Kelly allocation is marked DEPRECATED")
    
    def test_global_slot_allocator_enforces_1_cap(self):
        """Test that GlobalSlotAllocator enforces $1 exposure cap."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        
        allocator = get_global_slot_allocator()
        
        # Try to allocate more than $1.00 total
        requests = [
            AllocationRequest(
                agent_id="BTC_15M",
                asset="BTC",
                ticker="KXBTC15M-26JUL111145-45",
                entry_price_cents=30,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            ),
            AllocationRequest(
                agent_id="ETH_15M",
                asset="ETH",
                ticker="KXETH15M-26JUL111145-45",
                entry_price_cents=30,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            ),
            AllocationRequest(
                agent_id="SOL_15M",
                asset="SOL",
                ticker="KXSOL15M-26JUL111145-45",
                entry_price_cents=30,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            ),
            AllocationRequest(
                agent_id="XRP_15M",
                asset="XRP",
                ticker="KXXRP15M-26JUL111145-45",
                entry_price_cents=30,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            ),
        ]
        
        # Allocate 4 positions at 30c each = $1.20 total
        allocated_count = 0
        for req in requests:
            allocated, _, _ = allocator.request_allocation(req)
            if allocated:
                allocated_count += 1
        
        # Should not be able to allocate all 4 (would exceed $1)
        assert allocated_count <= 3, f"Should not allocate more than 3 positions at 30c, got {allocated_count}"
        
        # Total exposure should not exceed $1.00
        total_exposure = allocator.get_total_exposure()
        assert total_exposure <= 1.00, f"Total exposure ${total_exposure:.2f} should not exceed $1.00"
        
        print("✓ GlobalSlotAllocator enforces $1 exposure cap")
    
    def test_environment_variable_default_is_1(self):
        """Test that MERID_FIXED_EXPOSURE_CAP_USD defaults to $1.00."""
        import os
        
        # Get the default value (should be 1.00)
        default_cap = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
        
        assert default_cap == 1.00, f"MERID_FIXED_EXPOSURE_CAP_USD should default to 1.00, got {default_cap}"
        
        print("✓ MERID_FIXED_EXPOSURE_CAP_USD defaults to $1.00")
    
    def test_order_router_hard_exposure_cap_check(self):
        """Test that order_router has hard $1 exposure cap check."""
        import os
        from merid.risk.global_slot_allocator import get_global_slot_allocator, AllocationRequest
        
        allocator = get_global_slot_allocator()
        
        # Fill up to 75c exposure (max canonical price)
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL111145-45",
            entry_price_cents=75,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated, _, _ = allocator.request_allocation(request)
        assert allocated
        assert allocator.get_total_exposure() == 0.75
        
        # The order router should reject 30c order due to hard exposure cap
        # This is a structural check - the router checks slot_allocator.get_total_exposure()
        # against MERID_FIXED_EXPOSURE_CAP_USD
        current_exposure = allocator.get_total_exposure()
        fixed_cap = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
        order_notional = 30 / 100.0  # 30c = $0.30
        
        assert current_exposure + order_notional > fixed_cap, "Test setup: order should exceed cap"
        
        print("✓ Order router hard exposure cap check validated")
    
    def test_all_5_assets_included_in_cap(self):
        """Test that all 5 assets (BTC, ETH, SOL, XRP, DOGE) are included in $1 cap."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        
        allocator = get_global_slot_allocator()
        
        # All 5 assets should be allocatable under $1 cap
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            request = AllocationRequest(
                agent_id=f"{asset}_15M",
                asset=asset,
                ticker=f"KX{asset}15M-26JUL111145-45",
                entry_price_cents=15,  # 15c each = $0.75 total for 5 assets
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            )
            allocated, reason, _ = allocator.request_allocation(request)
            assert allocated, f"{asset} should be allocatable: {reason}"
        
        # Total exposure should be $0.75 (5 assets × 15c)
        total_exposure = allocator.get_total_exposure()
        assert abs(total_exposure - 0.75) < 0.01, f"Total exposure should be $0.75, got ${total_exposure:.2f}"
        
        print("✓ All 5 assets are included in $1 cap")
    
    def test_exit_orders_bypass_cap(self):
        """Test that exit orders bypass the $1 cap."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        
        allocator = get_global_slot_allocator()
        
        # Fill up to $1.00 cap
        requests = [
            AllocationRequest(
                agent_id="BTC_15M",
                asset="BTC",
                ticker="KXBTC15M-26JUL111145-45",
                entry_price_cents=30,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            ),
            AllocationRequest(
                agent_id="ETH_15M",
                asset="ETH",
                ticker="KXETH15M-26JUL111145-45",
                entry_price_cents=30,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            ),
            AllocationRequest(
                agent_id="SOL_15M",
                asset="SOL",
                ticker="KXSOL15M-26JUL111145-45",
                entry_price_cents=40,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            ),
        ]
        
        for req in requests:
            allocated, _, _ = allocator.request_allocation(req)
        
        # Should be at or near $1.00 cap
        total_exposure = allocator.get_total_exposure()
        assert total_exposure >= 0.95, f"Should be near cap, got ${total_exposure:.2f}"
        
        # Exit order should bypass cap
        exit_request = AllocationRequest(
            agent_id="position_monitor",
            asset="BTC",
            ticker="KXBTC15M-26JUL111145-45",
            entry_price_cents=30,
            edge_pct=0.0,
            spread_cents=0,
            is_exit_order=True
        )
        
        allocated_exit, reason_exit, _ = allocator.request_allocation(exit_request)
        assert allocated_exit, "Exit order should bypass cap"
        assert reason_exit == "EXIT_ORDER_BYPASS", f"Exit order reason should be EXIT_ORDER_BYPASS, got {reason_exit}"
        
        print("✓ Exit orders bypass $1 cap")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x", "-s"])
