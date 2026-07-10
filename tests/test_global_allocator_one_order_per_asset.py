"""
Test that GlobalAllocator enforces 1 order per asset per cycle (slot-based model).

This test validates the fix for the bug where multiple orders for the same asset
could be submitted in a single cycle, violating the slot-based model.
"""

import pytest
from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate


def test_global_allocator_one_order_per_asset():
    """Test that global allocator allows only 1 order per asset per cycle."""
    
    # Create allocator with $1.00 venue cap
    allocator = GlobalAllocator(venue_cap_usd=1.00, min_edge_pct=2.0)
    
    # Create multiple candidates for the same asset (ETH)
    candidates = [
        OrderCandidate(
            asset="ETH",
            ticker="KXETH15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=25,
            count=1,
            edge_pct=5.0,
            confidence=0.9,
            model_prob=0.75,
            agent_name="ETH_15M"
        ),
        OrderCandidate(
            asset="ETH",
            ticker="KXETH15M-26JUL092230-00",
            side="yes",
            action="buy",
            price_cents=25,
            count=1,
            edge_pct=4.0,
            confidence=0.8,
            model_prob=0.70,
            agent_name="ETH_15M"
        ),
        OrderCandidate(
            asset="BTC",
            ticker="KXBTC15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=25,
            count=1,
            edge_pct=6.0,
            confidence=0.95,
            model_prob=0.80,
            agent_name="BTC_15M"
        ),
    ]
    
    # Allocate orders
    chosen = allocator.allocate(candidates, current_positions={})
    
    # Should only choose 1 ETH order (the highest edge) and 1 BTC order
    assert len(chosen) == 2, f"Expected 2 orders (1 ETH + 1 BTC), got {len(chosen)}"
    
    # Verify only 1 ETH order was chosen
    eth_orders = [c for c in chosen if c.asset == "ETH"]
    assert len(eth_orders) == 1, f"Expected 1 ETH order, got {len(eth_orders)}"
    
    # Verify the chosen ETH order is the highest edge (5.0%)
    assert eth_orders[0].edge_pct == 5.0, f"Expected ETH edge 5.0%, got {eth_orders[0].edge_pct}%"
    
    # Verify BTC order was chosen
    btc_orders = [c for c in chosen if c.asset == "BTC"]
    assert len(btc_orders) == 1, f"Expected 1 BTC order, got {len(btc_orders)}"


def test_global_allocator_multiple_assets():
    """Test that global allocator allows 1 order per asset across multiple assets."""
    
    allocator = GlobalAllocator(venue_cap_usd=1.00, min_edge_pct=2.0)
    
    # Create candidates for multiple assets
    candidates = [
        OrderCandidate(
            asset="BTC",
            ticker="KXBTC15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=25,
            count=1,
            edge_pct=5.0,
            confidence=0.9,
            model_prob=0.75,
            agent_name="BTC_15M"
        ),
        OrderCandidate(
            asset="ETH",
            ticker="KXETH15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=25,
            count=1,
            edge_pct=4.0,
            confidence=0.8,
            model_prob=0.70,
            agent_name="ETH_15M"
        ),
        OrderCandidate(
            asset="SOL",
            ticker="KXSOL15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=25,
            count=1,
            edge_pct=3.0,
            confidence=0.7,
            model_prob=0.65,
            agent_name="SOL_15M"
        ),
    ]
    
    # Allocate orders
    chosen = allocator.allocate(candidates, current_positions={})
    
    # Should choose all 3 orders (1 per asset, under $1 cap)
    assert len(chosen) == 3, f"Expected 3 orders (1 per asset), got {len(chosen)}"
    
    # Verify 1 order per asset
    assets = [c.asset for c in chosen]
    assert len(set(assets)) == 3, f"Expected 3 unique assets, got {len(set(assets))}"


def test_global_allocator_respects_venue_cap():
    """Test that global allocator respects venue cap even with 1 order per asset limit."""
    
    allocator = GlobalAllocator(venue_cap_usd=1.00, min_edge_pct=2.0)
    
    # Create candidates that would exceed venue cap if all chosen
    candidates = [
        OrderCandidate(
            asset="BTC",
            ticker="KXBTC15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=50,  # $0.50 notional
            count=1,
            edge_pct=5.0,
            confidence=0.9,
            model_prob=0.75,
            agent_name="BTC_15M"
        ),
        OrderCandidate(
            asset="ETH",
            ticker="KXETH15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=50,  # $0.50 notional
            count=1,
            edge_pct=4.0,
            confidence=0.8,
            model_prob=0.70,
            agent_name="ETH_15M"
        ),
        OrderCandidate(
            asset="SOL",
            ticker="KXSOL15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=50,  # $0.50 notional (would exceed cap)
            count=1,
            edge_pct=3.0,
            confidence=0.7,
            model_prob=0.65,
            agent_name="SOL_15M"
        ),
    ]
    
    # Allocate orders
    chosen = allocator.allocate(candidates, current_positions={})
    
    # Should only choose 2 orders (BTC + ETH = $1.00), SOL should be skipped due to cap
    assert len(chosen) == 2, f"Expected 2 orders (venue cap limit), got {len(chosen)}"
    
    # Verify SOL was skipped
    sol_orders = [c for c in chosen if c.asset == "SOL"]
    assert len(sol_orders) == 0, f"Expected 0 SOL orders (cap exceeded), got {len(sol_orders)}"


def test_global_allocator_prioritizes_cheaper_when_cap_exceeded():
    """Test that global allocator finds cheaper alternative when first candidate exceeds cap."""
    
    allocator = GlobalAllocator(venue_cap_usd=1.00, min_edge_pct=2.0)
    
    # Create candidates where first (best edge) exceeds cap, but cheaper alternative exists
    candidates = [
        OrderCandidate(
            asset="ETH",
            ticker="KXETH15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=73,  # $0.73 notional (exceeds cap alone)
            count=1,
            edge_pct=4.0,
            confidence=0.54,
            model_prob=0.70,
            agent_name="ETH_15M"
        ),
        OrderCandidate(
            asset="BTC",
            ticker="KXBTC15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=64,  # $0.64 notional (fits under cap)
            count=1,
            edge_pct=4.865,
            confidence=0.55,
            model_prob=0.75,
            agent_name="BTC_15M"
        ),
    ]
    
    # Allocate orders
    chosen = allocator.allocate(candidates, current_positions={})
    
    # Should choose 1 order (the cheaper BTC that fits under cap)
    assert len(chosen) == 1, f"Expected 1 order (cheaper alternative), got {len(chosen)}"
    
    # Verify BTC was chosen (cheaper and fits under cap)
    btc_orders = [c for c in chosen if c.asset == "BTC"]
    assert len(btc_orders) == 1, f"Expected 1 BTC order (cheaper alternative), got {len(btc_orders)}"
    
    # Verify ETH was skipped (exceeds cap)
    eth_orders = [c for c in chosen if c.asset == "ETH"]
    assert len(eth_orders) == 0, f"Expected 0 ETH orders (exceeds cap), got {len(eth_orders)}"


def test_global_allocator_sorts_by_edge_then_price():
    """Test that global allocator sorts by edge first, then by price (cheaper first for same edge)."""
    
    allocator = GlobalAllocator(venue_cap_usd=1.00, min_edge_pct=2.0)
    
    # Create candidates with same edge but different prices
    candidates = [
        OrderCandidate(
            asset="BTC",
            ticker="KXBTC15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=70,  # $0.70 notional
            count=1,
            edge_pct=5.0,
            confidence=0.9,
            model_prob=0.75,
            agent_name="BTC_15M"
        ),
        OrderCandidate(
            asset="ETH",
            ticker="KXETH15M-26JUL092200-00",
            side="yes",
            action="buy",
            price_cents=60,  # $0.60 notional (cheaper)
            count=1,
            edge_pct=5.0,
            confidence=0.9,
            model_prob=0.70,
            agent_name="ETH_15M"
        ),
    ]
    
    # Allocate orders
    chosen = allocator.allocate(candidates, current_positions={})
    
    # Should choose 1 order (the cheaper ETH since edges are equal)
    assert len(chosen) == 1, f"Expected 1 order (cheaper of equal edges), got {len(chosen)}"
    
    # Verify ETH was chosen (cheaper with same edge)
    eth_orders = [c for c in chosen if c.asset == "ETH"]
    assert len(eth_orders) == 1, f"Expected 1 ETH order (cheaper), got {len(eth_orders)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
