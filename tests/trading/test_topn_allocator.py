"""
Unit tests for Top-N Edge Allocator

Comprehensive coverage of:
- Basic allocation computation
- Dynamic N stepping (3→2→1→0)
- Max-loss-based sizing
- Edge tie handling
- Min contracts constraints
- Min notional constraints
- Per-asset notional caps
- Invariant validation
- Configuration loading
"""

import os
import unittest
from decimal import Decimal
from typing import List, Optional

from merid.trading.topn_allocator import (
    TopNAllocatorConfig,
    EdgeCandidate,
    TradeAllocation,
    AllocationCycle,
    select_topn_allocations,
    TopNEdgeAllocator,
    GlobalRiskManager,
    create_topn_allocator,
    get_topn_allocator,
    reset_topn_allocator,
)


# ═══════════════════════════════════════════════════════════════════════════
# Test Data
# ═══════════════════════════════════════════════════════════════════════════


def make_candidate(
    asset: str = "BTC",
    edge: float = 0.05,
    direction: str = "long",
    entry_price_cents: int = 55,
    stop_price_cents: Optional[int] = None,
    max_notional_cap: int = 10000,
) -> EdgeCandidate:
    """Helper to create EdgeCandidate.
    
    For Kalshi binary contracts, the "stop" is implicit:
    - Long YES: max loss = entry price (if settles NO)
    - Short YES (Long NO): max loss = 100 - entry (if settles YES)
    
    So we use stop_price_cents = 0 for longs and 100 for shorts to indicate
    the settlement boundary (not an actual stop-loss order).
    """
    if stop_price_cents is None:
        # Binary contract: implicit stop at opposite settlement value
        stop_price_cents = 0 if direction == "long" else 100
    
    return EdgeCandidate(
        asset=asset,
        edge=edge,
        direction=direction,
        entry_price_cents=entry_price_cents,
        stop_price_cents=stop_price_cents,
        max_notional_cap=max_notional_cap,
    )


def make_5_candidates() -> List[EdgeCandidate]:
    """Create 5 candidates with different edges."""
    return [
        make_candidate("BTC", 0.08, "long", 55, max_notional_cap=10000),
        make_candidate("ETH", 0.07, "long", 52, max_notional_cap=10000),
        make_candidate("SOL", 0.06, "short", 48, max_notional_cap=10000),
        make_candidate("XRP", 0.05, "long", 50, max_notional_cap=10000),
        make_candidate("DOGE", 0.04, "short", 45, max_notional_cap=10000),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Configuration Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTopNAllocatorConfig(unittest.TestCase):
    """Test configuration loading and defaults."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = TopNAllocatorConfig()
        
        self.assertEqual(config.min_cycle_risk_pct, 0.01)
        self.assertEqual(config.max_cycle_risk_pct, 0.02)
        self.assertEqual(config.max_edges_per_cycle, 3)
        self.assertEqual(config.min_edges_per_cycle, 0)
        self.assertEqual(config.min_contracts, 1)
        self.assertEqual(config.min_notional_usd, 1.00)
        self.assertEqual(config.edge_epsilon, 1e-6)
        self.assertEqual(config.default_stop_distance_pct, 0.02)
        self.assertEqual(config.valid_assets, ("BTC", "ETH", "SOL", "XRP", "DOGE"))
    
    def test_from_env(self):
        """Test loading from environment variables."""
        os.environ["TOPN_MIN_CYCLE_RISK_PCT"] = "0.015"
        os.environ["TOPN_MAX_EDGES"] = "5"
        os.environ["TOPN_MIN_CONTRACTS"] = "2"
        
        config = TopNAllocatorConfig.from_env()
        
        self.assertEqual(config.min_cycle_risk_pct, 0.015)
        self.assertEqual(config.max_edges_per_cycle, 5)
        self.assertEqual(config.min_contracts, 2)
        
        # Clean up
        del os.environ["TOPN_MIN_CYCLE_RISK_PCT"]
        del os.environ["TOPN_MAX_EDGES"]
        del os.environ["TOPN_MIN_CONTRACTS"]
    
    def test_from_yaml(self):
        """Test loading from YAML dict."""
        yaml_config = {
            "min_cycle_risk_pct": 0.015,
            "max_cycle_risk_pct": 0.025,
            "max_edges_per_cycle": 4,
            "min_contracts": 3,
        }
        
        config = TopNAllocatorConfig.from_yaml(yaml_config)
        
        self.assertEqual(config.min_cycle_risk_pct, 0.015)
        self.assertEqual(config.max_cycle_risk_pct, 0.025)
        self.assertEqual(config.max_edges_per_cycle, 4)
        self.assertEqual(config.min_contracts, 3)
        # Unspecified values use defaults
        self.assertEqual(config.min_notional_usd, 1.00)


# ═══════════════════════════════════════════════════════════════════════════
# EdgeCandidate Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCandidate(unittest.TestCase):
    """Test EdgeCandidate dataclass and methods."""
    
    def test_compute_max_loss_per_contract_long(self):
        """Test max loss computation for long position."""
        c = make_candidate(direction="long", entry_price_cents=55)
        # Long YES: max loss = entry price (lose 55¢ if wrong)
        self.assertEqual(c.compute_max_loss_per_contract(), 55)
    
    def test_compute_max_loss_per_contract_short(self):
        """Test max loss computation for short position."""
        c = make_candidate(direction="short", entry_price_cents=55)
        # Short YES (Long NO): max loss = 100 - entry = 45¢ if YES settles
        self.assertEqual(c.compute_max_loss_per_contract(), 45)
    
    def test_compute_contracts_for_risk_budget(self):
        """Test contract calculation for risk budget."""
        c = make_candidate(direction="long", entry_price_cents=50)
        # With $10 risk budget (1000¢) and 50¢ max loss, can buy 20 contracts
        self.assertEqual(c.compute_contracts_for_risk_budget(1000), 20)
        
        # With $5 risk budget (500¢) and 50¢ max loss, can buy 10 contracts
        self.assertEqual(c.compute_contracts_for_risk_budget(500), 10)
        
        # Zero risk budget
        self.assertEqual(c.compute_contracts_for_risk_budget(0), 0)


# ═══════════════════════════════════════════════════════════════════════════
# Core Allocation Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSelectTopNAllocations(unittest.TestCase):
    """Test core allocation selection algorithm."""
    
    def test_basic_allocation(self):
        """Test basic allocation with 5 candidates."""
        config = TopNAllocatorConfig(max_edges_per_cycle=3)
        candidates = make_5_candidates()
        
        # $1000 equity, 2% risk cap = $20 risk budget
        cycle = select_topn_allocations(100000, candidates, config)
        
        self.assertEqual(cycle.num_edges_traded, 3)  # Top 3 selected
        self.assertEqual(len(cycle.allocations), 3)
        self.assertEqual(cycle.cycle_risk_usd, 20.0)  # 2% of $1000
        
        # Top 3 edges: BTC (0.08), ETH (0.07), SOL (0.06)
        assets = [a.asset for a in cycle.allocations]
        self.assertEqual(assets, ["BTC", "ETH", "SOL"])
    
    def test_dynamic_n_stepping_insufficient_budget(self):
        """Test N stepping down when budget insufficient for 3."""
        config = TopNAllocatorConfig(max_edges_per_cycle=3, min_contracts=10)
        candidates = make_5_candidates()
        
        # Very small equity: $10 with 2% risk = 20¢ budget
        # Each trade needs min_contracts * max_loss_per_contract
        # For BTC long @ 55¢: needs 10 contracts * 55¢ = 550¢ = $5.50
        # So 3 trades would need ~$16.50, which exceeds $0.20
        # Should step down to fewer trades or 0
        
        cycle = select_topn_allocations(1000, candidates, config)
        
        # Should step down to N=0 since no allocation satisfies min_contracts
        self.assertEqual(cycle.num_edges_traded, 0)
    
    def test_proportional_allocation(self):
        """Test that allocations are proportional to edge."""
        config = TopNAllocatorConfig(max_edges_per_cycle=2)
        
        # Create 2 candidates with different edges
        candidates = [
            make_candidate("BTC", 0.10, "long", 50),  # 2x edge
            make_candidate("ETH", 0.05, "long", 50),  # 1x edge
        ]
        
        # $1000 equity, 2% risk = $20
        cycle = select_topn_allocations(100000, candidates, config)
        
        self.assertEqual(len(cycle.allocations), 2)
        
        btc_alloc = next(a for a in cycle.allocations if a.asset == "BTC")
        eth_alloc = next(a for a in cycle.allocations if a.asset == "ETH")
        
        # BTC should have ~2x the risk budget of ETH (10:5 ratio)
        btc_risk = btc_alloc.risk_budget_usd
        eth_risk = eth_alloc.risk_budget_usd
        
        # Ratio should be approximately 2:1
        self.assertAlmostEqual(btc_risk / eth_risk, 2.0, delta=0.1)
    
    def test_tied_edge_equal_split(self):
        """Test equal split when edges are tied."""
        config = TopNAllocatorConfig(max_edges_per_cycle=2, edge_epsilon=0.001)
        
        # Create 2 candidates with tied edges (within epsilon)
        candidates = [
            make_candidate("BTC", 0.10, "long", 50),
            make_candidate("ETH", 0.100001, "long", 50),  # Within 1e-6
        ]
        
        # $1000 equity, 2% risk = $20
        cycle = select_topn_allocations(100000, candidates, config)
        
        # Actually epsilon is 1e-6, 0.10 vs 0.100001 diff is 1e-6 which is at boundary
        # Let's use more distinct tied values
        candidates = [
            make_candidate("BTC", 0.10, "long", 50),
            make_candidate("ETH", 0.10, "long", 50),  # Exactly tied
        ]
        
        cycle = select_topn_allocations(100000, candidates, config)
        
        btc_alloc = next(a for a in cycle.allocations if a.asset == "BTC")
        eth_alloc = next(a for a in cycle.allocations if a.asset == "ETH")
        
        # Should be approximately equal (small rounding differences possible)
        self.assertAlmostEqual(btc_alloc.risk_budget_usd, eth_alloc.risk_budget_usd, delta=0.01)
    
    def test_less_candidates_than_max_n(self):
        """Test when fewer candidates than max N."""
        config = TopNAllocatorConfig(max_edges_per_cycle=5)
        
        # Only 2 candidates but max is 5
        candidates = make_5_candidates()[:2]
        
        cycle = select_topn_allocations(100000, candidates, config)
        
        self.assertEqual(cycle.num_edges_traded, 2)
    
    def test_no_candidates(self):
        """Test allocation with no candidates."""
        config = TopNAllocatorConfig()
        
        cycle = select_topn_allocations(100000, [], config)
        
        self.assertEqual(cycle.num_edges_traded, 0)
        self.assertEqual(len(cycle.allocations), 0)
        self.assertEqual(cycle.num_candidates, 0)
    
    def test_zero_equity(self):
        """Test allocation with zero equity."""
        config = TopNAllocatorConfig()
        candidates = make_5_candidates()
        
        # Should still return a cycle with 0 risk budget
        cycle = select_topn_allocations(0, candidates, config)
        
        # Will step down to 0 since budget is 0
        self.assertEqual(cycle.cycle_risk_usd, 0.0)
    
    def test_min_contracts_constraint(self):
        """Test min contracts constraint enforcement."""
        config = TopNAllocatorConfig(max_edges_per_cycle=1, min_contracts=5)
        
        # Small budget: $10 equity, 2% = 20¢ risk
        # For BTC @ 55¢ long, max loss = 55¢ per contract
        # With 20¢ budget, can only buy 0 contracts
        # min_contracts=5 requires at least 5 contracts = 275¢ = $2.75
        
        candidates = [make_candidate("BTC", 0.10, "long", 55)]
        
        cycle = select_topn_allocations(1000, candidates, config)
        
        # Should step down to 0 since min_contracts can't be satisfied
        self.assertEqual(cycle.num_edges_traded, 0)
    
    def test_per_asset_notional_cap(self):
        """Test that per-asset notional caps are respected."""
        config = TopNAllocatorConfig(max_edges_per_cycle=1)
        
        # BTC with tight cap of 100¢
        candidates = [make_candidate("BTC", 0.10, "long", 50, max_notional_cap=100)]
        
        # $1000 equity, 2% = $20 risk
        cycle = select_topn_allocations(100000, candidates, config)
        
        btc_alloc = cycle.allocations[0]
        # Should be capped: max 100¢ notional / 50¢ entry = 2 contracts
        self.assertEqual(btc_alloc.target_contracts, 2)
    
    def test_risk_budget_not_exceeded(self):
        """Test that total risk doesn't exceed budget."""
        config = TopNAllocatorConfig(max_edges_per_cycle=3)
        candidates = make_5_candidates()
        
        # Large equity: $10000, 2% = $200 risk
        cycle = select_topn_allocations(1000000, candidates, config)
        
        # Sum of max loss should be <= cycle risk
        total_risk = sum(a.max_loss_usd for a in cycle.allocations)
        self.assertLessEqual(total_risk, cycle.cycle_risk_usd + 0.01)


# ═══════════════════════════════════════════════════════════════════════════
# Cycle Validation Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAllocationCycleValidation(unittest.TestCase):
    """Test AllocationCycle invariant validation."""
    
    def test_valid_cycle(self):
        """Test validation passes for valid cycle."""
        config = TopNAllocatorConfig(max_edges_per_cycle=3, min_contracts=1)
        
        allocations = [
            TradeAllocation("BTC", 0.08, "long", 10, 55, 0, 5.50, 0.5, 6.0),
            TradeAllocation("ETH", 0.07, "long", 10, 52, 0, 5.20, 0.5, 6.0),
        ]
        
        cycle = AllocationCycle(
            cycle_id="test",
            cycle_ts=None,
            equity_cents=100000,
            cycle_risk_pct=0.02,
            cycle_risk_usd=20.0,
            num_candidates=5,
            num_edges_traded=2,
            sum_risk_usd=10.7,
            allocations=allocations,
            config=config,
        )
        
        is_valid, violations = cycle.validate_invariants()
        self.assertTrue(is_valid)
        self.assertEqual(len(violations), 0)
    
    def test_invalid_num_edges_traded(self):
        """Test validation catches N > max_edges."""
        config = TopNAllocatorConfig(max_edges_per_cycle=2, min_contracts=1)
        
        allocations = [
            TradeAllocation("BTC", 0.08, "long", 10, 55, 0, 5.50, 0.33, 6.0),
            TradeAllocation("ETH", 0.07, "long", 10, 52, 0, 5.20, 0.33, 6.0),
            TradeAllocation("SOL", 0.06, "long", 10, 50, 0, 5.00, 0.34, 6.0),
        ]
        
        cycle = AllocationCycle(
            cycle_id="test",
            cycle_ts=None,
            equity_cents=100000,
            cycle_risk_pct=0.02,
            cycle_risk_usd=20.0,
            num_candidates=5,
            num_edges_traded=3,  # Exceeds max of 2
            sum_risk_usd=15.7,
            allocations=allocations,
            config=config,
        )
        
        is_valid, violations = cycle.validate_invariants()
        self.assertFalse(is_valid)
        self.assertTrue(any("num_edges_traded" in v for v in violations))
    
    def test_invalid_sum_risk_exceeded(self):
        """Test validation catches sum_risk > cycle_risk."""
        config = TopNAllocatorConfig(max_edges_per_cycle=3, min_contracts=1)
        
        allocations = [
            TradeAllocation("BTC", 0.08, "long", 10, 55, 0, 5.50, 0.5, 6.0),
        ]
        
        cycle = AllocationCycle(
            cycle_id="test",
            cycle_ts=None,
            equity_cents=100000,
            cycle_risk_pct=0.02,
            cycle_risk_usd=5.0,  # $5 budget
            num_candidates=5,
            num_edges_traded=1,
            sum_risk_usd=5.50,  # $5.50 exceeds $5.00 budget
            allocations=allocations,
            config=config,
        )
        
        is_valid, violations = cycle.validate_invariants()
        self.assertFalse(is_valid)
        self.assertTrue(any("sum_risk_usd" in v for v in violations))
    
    def test_invalid_min_contracts(self):
        """Test validation catches target_contracts < min_contracts."""
        config = TopNAllocatorConfig(max_edges_per_cycle=3, min_contracts=5)
        
        allocations = [
            TradeAllocation("BTC", 0.08, "long", 3, 55, 0, 1.65, 1.0, 6.0),  # 3 < min 5
        ]
        
        cycle = AllocationCycle(
            cycle_id="test",
            cycle_ts=None,
            equity_cents=100000,
            cycle_risk_pct=0.02,
            cycle_risk_usd=20.0,
            num_candidates=5,
            num_edges_traded=1,
            sum_risk_usd=1.65,
            allocations=allocations,
            config=config,
        )
        
        is_valid, violations = cycle.validate_invariants()
        self.assertFalse(is_valid)
        self.assertTrue(any("target_contracts" in v or "min_contracts" in v for v in violations))


# ═══════════════════════════════════════════════════════════════════════════
# Allocator Class Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTopNEdgeAllocator(unittest.TestCase):
    """Test TopNEdgeAllocator class."""
    
    def setUp(self):
        """Reset allocator before each test."""
        reset_topn_allocator()
    
    def tearDown(self):
        """Reset allocator after each test."""
        reset_topn_allocator()
    
    def test_singleton(self):
        """Test singleton behavior."""
        allocator1 = get_topn_allocator()
        allocator2 = get_topn_allocator()
        
        self.assertIs(allocator1, allocator2)
    
    def test_compute_allocations(self):
        """Test compute_allocations method."""
        allocator = create_topn_allocator(TopNAllocatorConfig(max_edges_per_cycle=3))
        candidates = make_5_candidates()
        
        cycle = allocator.compute_allocations(100000, candidates)
        
        self.assertEqual(len(cycle.allocations), 3)
        self.assertEqual(cycle.num_edges_traded, 3)
    
    def test_metrics_tracking(self):
        """Test metrics accumulation."""
        allocator = create_topn_allocator(TopNAllocatorConfig(max_edges_per_cycle=2))
        candidates = make_5_candidates()
        
        # Run 3 cycles
        for _ in range(3):
            allocator.compute_allocations(100000, candidates)
        
        metrics = allocator.get_metrics()
        
        self.assertEqual(metrics["cycle_count"], 3)
        self.assertEqual(metrics["total_trades"], 3 * 2)  # 2 trades per cycle
    
    def test_reset_metrics(self):
        """Test metrics reset."""
        allocator = create_topn_allocator(TopNAllocatorConfig(max_edges_per_cycle=2))
        candidates = make_5_candidates()
        
        allocator.compute_allocations(100000, candidates)
        allocator.reset_metrics()
        
        metrics = allocator.get_metrics()
        self.assertEqual(metrics["cycle_count"], 0)
        self.assertEqual(metrics["total_trades"], 0)
    
    def test_empty_cycle_on_zero_equity(self):
        """Test empty cycle returned on zero equity."""
        allocator = create_topn_allocator(TopNAllocatorConfig())
        candidates = make_5_candidates()
        
        cycle = allocator.compute_allocations(0, candidates)
        
        self.assertEqual(cycle.num_edges_traded, 0)
        self.assertEqual(len(cycle.allocations), 0)


# ═══════════════════════════════════════════════════════════════════════════
# Global Risk Manager Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGlobalRiskManager(unittest.TestCase):
    """Test GlobalRiskManager checks."""
    
    def test_can_open_batch_allowed(self):
        """Test batch opening allowed when within limits."""
        rm = GlobalRiskManager()
        
        allocations = [
            TradeAllocation("BTC", 0.08, "long", 10, 55, 0, 5.0, 1.0, 6.0),
        ]
        
        # $1000 equity, 10% max open = $100 max open risk
        allowed, reason = rm.can_open_batch(allocations, 100000, 0.0)
        
        self.assertTrue(allowed)
        self.assertEqual(reason, "")
    
    def test_can_open_batch_max_open_risk_exceeded(self):
        """Test batch blocked when max open risk would be exceeded."""
        rm = GlobalRiskManager()
        rm._max_open_risk_pct = 0.05  # 5% max open risk
        
        allocations = [
            TradeAllocation("BTC", 0.08, "long", 10, 55, 0, 50.0, 1.0, 60.0),
        ]
        
        # $1000 equity, 5% max = $50 max open risk
        # Proposed $50 + existing $20 = $70 > $50 limit
        allowed, reason = rm.can_open_batch(allocations, 100000, 20.0)
        
        self.assertFalse(allowed)
        self.assertIn("Max open risk exceeded", reason)
    
    def test_daily_loss_limit(self):
        """Test batch blocked when daily loss limit reached."""
        rm = GlobalRiskManager()
        rm._daily_loss_usd = 150.0
        rm._max_daily_loss_usd = 100.0
        
        allocations = [TradeAllocation("BTC", 0.08, "long", 10, 55, 0, 5.0, 1.0, 6.0)]
        
        allowed, reason = rm.can_open_batch(allocations, 100000, 0.0)
        
        self.assertFalse(allowed)
        self.assertIn("Daily loss limit reached", reason)
    
    def test_record_loss(self):
        """Test loss recording."""
        rm = GlobalRiskManager()
        
        rm.record_loss(10.0)
        rm.record_loss(5.0)
        
        self.assertEqual(rm._daily_loss_usd, 15.0)
    
    def test_reset_daily_loss(self):
        """Test daily loss reset."""
        rm = GlobalRiskManager()
        
        rm.record_loss(10.0)
        rm.reset_daily_loss()
        
        self.assertEqual(rm._daily_loss_usd, 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Edge Case Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""
    
    def test_very_small_edge(self):
        """Test handling of very small edge values."""
        config = TopNAllocatorConfig()
        
        # Edge of 0.000001 should still be valid (just above epsilon)
        candidates = [make_candidate("BTC", 0.000001, "long", 50)]
        
        cycle = select_topn_allocations(100000, candidates, config)
        
        # Should be filtered out if edge <= 0 check
        self.assertEqual(cycle.num_edges_traded, 1)
    
    def test_extreme_entry_prices(self):
        """Test handling of extreme entry prices."""
        config = TopNAllocatorConfig()
        
        # Very low price (1¢)
        c1 = make_candidate("BTC", 0.05, "long", 1)
        self.assertEqual(c1.compute_max_loss_per_contract(), 1)
        
        # Very high price (99¢)
        c2 = make_candidate("BTC", 0.05, "short", 99)
        self.assertEqual(c2.compute_max_loss_per_contract(), 1)  # 100 - 99 = 1
    
    def test_large_number_of_candidates(self):
        """Test performance with many candidates."""
        config = TopNAllocatorConfig(max_edges_per_cycle=3)
        
        # Create 100 candidates (more than expected)
        candidates = []
        for i in range(100):
            asset = config.valid_assets[i % len(config.valid_assets)]
            candidates.append(make_candidate(asset, 0.01 + (i * 0.001), "long", 50))
        
        cycle = select_topn_allocations(100000, candidates, config)
        
        self.assertEqual(cycle.num_edges_traded, 3)
        # Top 3 should have highest edges
        edges = [a.edge for a in cycle.allocations]
        self.assertEqual(sorted(edges, reverse=True), edges)
    
    def test_all_same_edge(self):
        """Test when all candidates have identical edges."""
        config = TopNAllocatorConfig(max_edges_per_cycle=3, edge_epsilon=1e-6)
        
        candidates = [
            make_candidate("BTC", 0.05, "long", 50),
            make_candidate("ETH", 0.05, "long", 50),
            make_candidate("SOL", 0.05, "long", 50),
        ]
        
        cycle = select_topn_allocations(100000, candidates, config)
        
        self.assertEqual(cycle.num_edges_traded, 3)
        
        # Budget should be split equally
        for a in cycle.allocations:
            self.assertAlmostEqual(a.risk_budget_usd, 6.67, delta=0.02)
    
    def test_single_candidate(self):
        """Test with only one candidate."""
        config = TopNAllocatorConfig(max_edges_per_cycle=3)
        
        candidates = [make_candidate("BTC", 0.05, "long", 50)]
        
        cycle = select_topn_allocations(100000, candidates, config)
        
        self.assertEqual(cycle.num_edges_traded, 1)
        # Gets full budget
        self.assertAlmostEqual(cycle.allocations[0].risk_budget_usd, 20.0, delta=0.01)
    
    def test_invalid_assets_filtered(self):
        """Test that invalid assets are filtered out."""
        config = TopNAllocatorConfig()
        
        candidates = [
            make_candidate("BTC", 0.08, "long", 50),
            EdgeCandidate("INVALID", 0.09, "long", 50, 0, 10000),  # Invalid asset
        ]
        
        cycle = select_topn_allocations(100000, candidates, config)
        
        # Only BTC should be allocated
        self.assertEqual(cycle.num_edges_traded, 1)
        self.assertEqual(cycle.allocations[0].asset, "BTC")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    unittest.main()
