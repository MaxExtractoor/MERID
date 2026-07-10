"""
Unit Tests for Global Allocator

Tests the shared $1 pool allocation model with the following scenarios:
- 5 assets at 20c each → all allowed, total risk = $1.00
- One asset at 50c, two at 30c each → only some can trade; total risk never exceeds $1.00
- 3 assets at 40c each → either top two (80c total) or one (40c), but never 3 (120c)
"""

import sys
import os
# Add repository root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import pytest
from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate


class TestGlobalAllocator:
    """Test suite for GlobalAllocator with shared $1 pool model."""
    
    def test_five_assets_20c_all_allowed(self):
        """
        Scenario: 5 assets, all at 20c, all edges valid.
        Expected: All 5 selected, total risk = $1.00, 5 contracts.
        """
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=2.0,  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units
            min_confidence=0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
            min_price_cents=5,  # 2026-07-10: Expanded from 10c to 5c for skewed markets
            max_price_cents=95  # 2026-07-10: Expanded from 50c to 95c for skewed markets
        )
        
        candidates = [
            OrderCandidate(
                asset="BTC", ticker="KXBTC15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=3.0, confidence=0.55,
                model_prob=0.85, agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH", ticker="KXETH15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.9, confidence=0.55,
                model_prob=0.84, agent_name="ETH_15M"
            ),
            OrderCandidate(
                asset="SOL", ticker="KXSOL15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.8, confidence=0.55,
                model_prob=0.83, agent_name="SOL_15M"
            ),
            OrderCandidate(
                asset="XRP", ticker="KXXRP15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.7, confidence=0.55,
                model_prob=0.82, agent_name="XRP_15M"
            ),
            OrderCandidate(
                asset="DOGE", ticker="KXDOGE15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.6, confidence=0.55,
                model_prob=0.81, agent_name="DOGE_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # All 5 should be selected
        assert len(chosen) == 5, f"Expected 5 chosen, got {len(chosen)}"
        
        # Total risk should be exactly $1.00 (5 * 20c = 100c = $1.00)
        total_risk = sum(c.notional_usd for c in chosen)
        assert total_risk == 1.00, f"Expected total_risk=$1.00, got ${total_risk:.2f}"
        
        # Each asset should have exactly 1 contract
        assets = [c.asset for c in chosen]
        assert len(assets) == len(set(assets)), "Duplicate assets found"
        
        print(f"[PASS] Test passed: 5 assets at 20c -> all selected, total_risk=${total_risk:.2f}")
    
    def test_mixed_prices_cap_enforcement(self):
        """
        Scenario: 5 assets, prices [50c, 30c, 30c, 25c, 20c], all edges valid.
        Expected: Sorted by edge, watch which subset is selected.
        Ensure total risk ≤ $1.00 and no per-asset cap rescaling.
        """
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=2.0,  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units
            min_confidence=0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
            min_price_cents=5,  # 2026-07-10: Expanded from 10c to 5c for skewed markets
            max_price_cents=95  # 2026-07-10: Expanded from 50c to 95c for skewed markets
        )
        
        candidates = [
            OrderCandidate(
                asset="BTC", ticker="KXBTC15M-TEST", side="yes", action="buy",
                price_cents=50, count=1, edge_pct=3.0, confidence=0.55,
                model_prob=0.85, agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH", ticker="KXETH15M-TEST", side="yes", action="buy",
                price_cents=30, count=1, edge_pct=2.9, confidence=0.55,
                model_prob=0.84, agent_name="ETH_15M"
            ),
            OrderCandidate(
                asset="SOL", ticker="KXSOL15M-TEST", side="yes", action="buy",
                price_cents=30, count=1, edge_pct=2.8, confidence=0.55,
                model_prob=0.83, agent_name="SOL_15M"
            ),
            OrderCandidate(
                asset="XRP", ticker="KXXRP15M-TEST", side="yes", action="buy",
                price_cents=25, count=1, edge_pct=2.7, confidence=0.55,
                model_prob=0.82, agent_name="XRP_15M"
            ),
            OrderCandidate(
                asset="DOGE", ticker="KXDOGE15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.6, confidence=0.55,
                model_prob=0.81, agent_name="DOGE_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # Total risk must not exceed $1.00
        total_risk = sum(c.notional_usd for c in chosen)
        assert total_risk <= 1.00, f"Total risk ${total_risk:.2f} exceeds $1.00 cap"
        
        # With prices [50c, 30c, 30c, 25c, 20c], we can fit at most:
        # 50c + 30c + 20c = 100c (3 assets)
        # or 30c + 30c + 25c + 20c = 105c (too much)
        # So we expect 2-3 assets depending on edge ranking
        assert len(chosen) in [2, 3], f"Expected 2-3 chosen, got {len(chosen)}"
        
        # No duplicate assets
        assets = [c.asset for c in chosen]
        assert len(assets) == len(set(assets)), "Duplicate assets found"
        
        print(f"[PASS] Test passed: Mixed prices -> {len(chosen)} selected, total_risk=${total_risk:.2f} <= $1.00")
    
    def test_three_assets_40c_cap_enforcement(self):
        """
        Scenario: 3 assets, all at 40c, all edges valid.
        Expected: Either top two (80c total) or one (40c), but never 3 (120c).
        """
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=2.0,  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units
            min_confidence=0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
            min_price_cents=5,  # 2026-07-10: Expanded from 10c to 5c for skewed markets
            max_price_cents=95  # 2026-07-10: Expanded from 50c to 95c for skewed markets
        )
        
        candidates = [
            OrderCandidate(
                asset="BTC", ticker="KXBTC15M-TEST", side="yes", action="buy",
                price_cents=40, count=1, edge_pct=3.0, confidence=0.55,
                model_prob=0.85, agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH", ticker="KXETH15M-TEST", side="yes", action="buy",
                price_cents=40, count=1, edge_pct=2.9, confidence=0.55,
                model_prob=0.84, agent_name="ETH_15M"
            ),
            OrderCandidate(
                asset="SOL", ticker="KXSOL15M-TEST", side="yes", action="buy",
                price_cents=40, count=1, edge_pct=2.8, confidence=0.55,
                model_prob=0.83, agent_name="SOL_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # Total risk must not exceed $1.00
        total_risk = sum(c.notional_usd for c in chosen)
        assert total_risk <= 1.00, f"Total risk ${total_risk:.2f} exceeds $1.00 cap"
        
        # With 3 assets at 40c each, we can only fit 2 (80c total)
        # 3 would be 120c which exceeds $1.00
        assert len(chosen) <= 2, f"Expected at most 2 chosen, got {len(chosen)} (3 would be 120c > $1.00)"
        
        # No duplicate assets
        assets = [c.asset for c in chosen]
        assert len(assets) == len(set(assets)), "Duplicate assets found"
        
        print(f"[PASS] Test passed: 3 assets at 40c -> {len(chosen)} selected, total_risk=${total_risk:.2f} <= $1.00")
    
    def test_price_range_filtering(self):
        """
        Scenario: Candidates with prices outside [5c, 95c] range.
        Expected: Only candidates within range are considered.
        """
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=2.0,  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units
            min_confidence=0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
            min_price_cents=5,  # 2026-07-10: Expanded from 10c to 5c for skewed markets
            max_price_cents=95  # 2026-07-10: Expanded from 50c to 95c for skewed markets
        )
        
        candidates = [
            OrderCandidate(
                asset="BTC", ticker="KXBTC15M-TEST", side="yes", action="buy",
                price_cents=3, count=1, edge_pct=3.0, confidence=0.55,
                model_prob=0.85, agent_name="BTC_15M"  # Below min (5c)
            ),
            OrderCandidate(
                asset="ETH", ticker="KXETH15M-TEST", side="yes", action="buy",
                price_cents=25, count=1, edge_pct=2.5, confidence=0.55,
                model_prob=0.84, agent_name="ETH_15M"  # Within range
            ),
            OrderCandidate(
                asset="SOL", ticker="KXSOL15M-TEST", side="yes", action="buy",
                price_cents=97, count=1, edge_pct=2.2, confidence=0.55,
                model_prob=0.83, agent_name="SOL_15M"  # Above max (95c)
            ),
            OrderCandidate(
                asset="XRP", ticker="KXXRP15M-TEST", side="yes", action="buy",
                price_cents=30, count=1, edge_pct=2.1, confidence=0.55,
                model_prob=0.82, agent_name="XRP_15M"  # Within range
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # Only ETH (25c) and XRP (30c) should be selected
        assert len(chosen) == 2, f"Expected 2 chosen (within range), got {len(chosen)}"
        
        assets = [c.asset for c in chosen]
        assert "ETH" in assets, "ETH should be selected (25c within range)"
        assert "XRP" in assets, "XRP should be selected (30c within range)"
        assert "BTC" not in assets, "BTC should be filtered (3c below min)"
        assert "SOL" not in assets, "SOL should be filtered (97c above max)"
        
        print(f"[PASS] Test passed: Price range filtering -> {len(chosen)} selected (only within [5c-95c])")
    
    def test_confidence_filtering(self):
        """
        Scenario: Candidates with confidence below 50%.
        Expected: Only candidates with confidence ≥ 50% are considered.
        """
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=2.0,  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units
            min_confidence=0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
            min_price_cents=5,  # 2026-07-10: Expanded from 10c to 5c for skewed markets
            max_price_cents=95  # 2026-07-10: Expanded from 50c to 95c for skewed markets
        )
        
        candidates = [
            OrderCandidate(
                asset="BTC", ticker="KXBTC15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.5, confidence=0.45,
                model_prob=0.85, agent_name="BTC_15M"  # Below min (50%)
            ),
            OrderCandidate(
                asset="ETH", ticker="KXETH15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.4, confidence=0.55,
                model_prob=0.84, agent_name="ETH_15M"  # Above min
            ),
            OrderCandidate(
                asset="SOL", ticker="KXSOL15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.3, confidence=0.48,
                model_prob=0.83, agent_name="SOL_15M"  # Below min
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # Only ETH should be selected (confidence 55%)
        assert len(chosen) == 1, f"Expected 1 chosen (confidence ≥ 50%), got {len(chosen)}"
        assert chosen[0].asset == "ETH", "ETH should be selected (confidence 55%)"
        
        print(f"[PASS] Test passed: Confidence filtering -> {len(chosen)} selected (only >= 50%)")
    
    def test_edge_filtering(self):
        """
        Scenario: Candidates with edge below 2.0%.
        Expected: Only candidates with edge ≥ 2.0% are considered.
        """
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=2.0,  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units
            min_confidence=0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
            min_price_cents=5,  # 2026-07-10: Expanded from 10c to 5c for skewed markets
            max_price_cents=95  # 2026-07-10: Expanded from 50c to 95c for skewed markets
        )
        
        candidates = [
            OrderCandidate(
                asset="BTC", ticker="KXBTC15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=1.5, confidence=0.55,
                model_prob=0.85, agent_name="BTC_15M"  # Below min (2.0%)
            ),
            OrderCandidate(
                asset="ETH", ticker="KXETH15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.5, confidence=0.55,
                model_prob=0.84, agent_name="ETH_15M"  # Above min
            ),
            OrderCandidate(
                asset="SOL", ticker="KXSOL15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=1.0, confidence=0.55,
                model_prob=0.83, agent_name="SOL_15M"  # Below min
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # Only ETH should be selected (edge 2.5%)
        assert len(chosen) == 1, f"Expected 1 chosen (edge ≥ 2.0%), got {len(chosen)}"
        assert chosen[0].asset == "ETH", "ETH should be selected (edge 2.5%)"
        
        print(f"[PASS] Test passed: Edge filtering -> {len(chosen)} selected (only >= 2.0%)")
    
    def test_one_contract_per_asset(self):
        """
        Scenario: Multiple candidates for the same asset.
        Expected: Only 1 contract per asset is selected.
        """
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=2.0,  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units
            min_confidence=0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
            min_price_cents=5,  # 2026-07-10: Expanded from 10c to 5c for skewed markets
            max_price_cents=95  # 2026-07-10: Expanded from 50c to 95c for skewed markets
        )
        
        candidates = [
            OrderCandidate(
                asset="BTC", ticker="KXBTC15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=3.0, confidence=0.55,
                model_prob=0.85, agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="BTC", ticker="KXBTC15M-TEST2", side="no", action="buy",
                price_cents=20, count=1, edge_pct=2.9, confidence=0.55,
                model_prob=0.84, agent_name="BTC_15M"  # Same asset
            ),
            OrderCandidate(
                asset="ETH", ticker="KXETH15M-TEST", side="yes", action="buy",
                price_cents=20, count=1, edge_pct=2.8, confidence=0.55,
                model_prob=0.83, agent_name="ETH_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # Only 1 BTC order should be selected (best edge)
        btc_orders = [c for c in chosen if c.asset == "BTC"]
        assert len(btc_orders) == 1, f"Expected 1 BTC order, got {len(btc_orders)}"
        
        # Total should be 2 (1 BTC + 1 ETH)
        assert len(chosen) == 2, f"Expected 2 chosen, got {len(chosen)}"
        
        print(f"[PASS] Test passed: 1 contract per asset -> {len(chosen)} selected (1 BTC, 1 ETH)")
    
    def test_shared_pool_not_per_asset_budget(self):
        """
        Scenario: Verify that assets compete for shared $1 pool, not per-asset budgets.
        Expected: No per-asset cap rescaling, total exposure ≤ $1.00.
        """
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=2.0,  # 2026-07-10: Changed from 0.05% to 2.0% to match agent grid edge units
            min_confidence=0.50,  # 2026-07-10: Lowered from 65% to 50% to match agent grid confidence
            min_price_cents=5,  # 2026-07-10: Expanded from 10c to 5c for skewed markets
            max_price_cents=95,  # 2026-07-10: Expanded from 50c to 95c for skewed markets
            max_single_asset_fraction=1.00  # Allow single asset to use full cap
        )
        
        candidates = [
            OrderCandidate(
                asset="BTC", ticker="KXBTC15M-TEST", side="yes", action="buy",
                price_cents=50, count=1, edge_pct=3.0, confidence=0.55,
                model_prob=0.85, agent_name="BTC_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # Single asset at 50c should be allowed (uses 50% of $1 cap)
        assert len(chosen) == 1, f"Expected 1 chosen, got {len(chosen)}"
        assert chosen[0].asset == "BTC"
        assert chosen[0].notional_usd == 0.50, f"Expected $0.50, got ${chosen[0].notional_usd:.2f}"
        
        # Verify no per-asset rescaling occurred
        # If per-asset caps were rescaled to 0.20 each, BTC at 50c would be rejected
        # But with shared pool, it's allowed as long as total ≤ $1.00
        
        print(f"[PASS] Test passed: Shared pool model -> single asset at 50c allowed (no per-asset rescaling)")


if __name__ == "__main__":
    # Run tests
    test = TestGlobalAllocator()
    
    print("Running Global Allocator Tests...")
    print("=" * 60)
    
    test.test_five_assets_20c_all_allowed()
    test.test_mixed_prices_cap_enforcement()
    test.test_three_assets_40c_cap_enforcement()
    test.test_price_range_filtering()
    test.test_confidence_filtering()
    test.test_edge_filtering()
    test.test_one_contract_per_asset()
    test.test_shared_pool_not_per_asset_budget()
    
    print("=" * 60)
    print("✓ All tests passed!")
