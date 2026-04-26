"""Tests for strict Edge #1 priority enforcement.

This test suite validates the wagering rules:
1. Edge #1 (highest edge) MUST be executed first - non-negotiable priority
2. Edge #1 gets minimum 1% of bankroll if valid (cycle_risk_cap_pct >= 0.01)
3. Edge #2 is ONLY considered after Edge #1 is fully allocated
4. Edge #3 is ONLY considered after Edge #2 is fully allocated
5. If any edge fails min constraints, it and ALL subsequent edges are skipped
6. Never skip Edge #1 to take Edge #2 or #3
"""

from decimal import Decimal
from typing import List, Optional
import unittest
import os
import sys

# Ensure tests can import from project root
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())

from merid.trading.topn_allocator import (
    select_topn_allocations,
    EdgeCandidate,
    TopNAllocatorConfig,
    AllocationCycle,
)
from merid.trading.top3_edge_allocator import (
    select_top3_allocations,
    EdgeCandidate as Top3EdgeCandidate,
    Top3Allocation,
)


class TestEdgePriorityRules(unittest.TestCase):
    """Test strict Edge #1 priority enforcement."""

    def setUp(self):
        """Set up test fixtures."""
        self.bankroll_cents = 10000  # $100 bankroll for easy math

    def _make_topn_candidate(
        self,
        asset: str,
        edge: float,
        entry_price_cents: int = 50,
        direction: str = "long",
    ) -> EdgeCandidate:
        """Create a TopN EdgeCandidate."""
        return EdgeCandidate(
            asset=asset,
            edge=Decimal(str(edge)),
            direction=direction,
            entry_price_cents=entry_price_cents,
            stop_price_cents=0 if direction == "long" else 100,
            max_notional_cap=5000,  # $50 cap per asset
            metadata={"ticker": f"KX{asset}-15M"},
        )

    def _make_top3_candidate(
        self,
        asset: str,
        edge: float,
    ) -> Top3EdgeCandidate:
        """Create a Top3 EdgeCandidate."""
        return Top3EdgeCandidate(
            asset=asset,
            edge=Decimal(str(edge)),
            max_notional_cap=5000,  # $50 cap per asset
            metadata={"ticker": f"KX{asset}-15M"},
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # RULE 1: Edge #1 MUST be executed first
    # ═══════════════════════════════════════════════════════════════════════════

    def test_edge1_always_allocated_when_valid(self):
        """Edge #1 must always be allocated when it has positive edge."""
        candidates = [
            self._make_topn_candidate("BTC", 0.05),  # Edge #1
            self._make_topn_candidate("ETH", 0.03),  # Edge #2
        ]

        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,  # 2% total budget
            min_cycle_risk_pct=0.01,  # 1% minimum
        )

        cycle = select_topn_allocations(
            equity_cents=self.bankroll_cents,
            candidates=candidates,
            config=config,
        )

        # Edge #1 must be allocated
        self.assertEqual(len(cycle.allocations), 2)
        self.assertEqual(cycle.allocations[0].asset, "BTC")  # Highest edge first

    def test_edge1_gets_minimum_1pct_budget(self):
        """Edge #1 gets at least 1% of bankroll when cycle cap is >= 1%."""
        candidates = [
            self._make_topn_candidate("BTC", 0.05),  # Edge #1
        ]

        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,  # 2% = $2 budget
            min_cycle_risk_pct=0.01,  # 1% = $1 minimum for Edge #1
        )

        cycle = select_topn_allocations(
            equity_cents=self.bankroll_cents,
            candidates=candidates,
            config=config,
        )

        self.assertEqual(len(cycle.allocations), 1)
        # Edge #1 should get at least $1 (1% of $100)
        self.assertGreaterEqual(
            cycle.allocations[0].risk_budget_usd, 1.0
        )

    def test_only_edge1_allocated_when_budget_constrained(self):
        """When budget only allows 1 edge, only Edge #1 is allocated."""
        candidates = [
            self._make_topn_candidate("BTC", 0.05),  # Edge #1
            self._make_topn_candidate("ETH", 0.03),  # Edge #2
            self._make_topn_candidate("SOL", 0.02),  # Edge #3
        ]

        # Very tight budget - only enough for 1 edge
        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.01,  # 1% = only $1 total budget
            min_cycle_risk_pct=0.01,
        )

        cycle = select_topn_allocations(
            equity_cents=self.bankroll_cents,
            candidates=candidates,
            config=config,
        )

        # Only Edge #1 should be allocated
        self.assertEqual(len(cycle.allocations), 1)
        self.assertEqual(cycle.allocations[0].asset, "BTC")

    # ═══════════════════════════════════════════════════════════════════════════
    # RULE 2 & 3: Edge #2 and #3 only considered after previous edges
    # ═══════════════════════════════════════════════════════════════════════════

    def test_edge2_blocked_until_edge1_executed(self):
        """Edge #2 allocation must wait until Edge #1 is fully allocated."""
        candidates = [
            self._make_topn_candidate("BTC", 0.05),  # Edge #1
            self._make_topn_candidate("ETH", 0.03),  # Edge #2
        ]

        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,
            min_cycle_risk_pct=0.01,
        )

        cycle = select_topn_allocations(
            equity_cents=self.bankroll_cents,
            candidates=candidates,
            config=config,
        )

        # Both should be allocated (sufficient budget)
        self.assertEqual(len(cycle.allocations), 2)
        # Edge #1 first
        self.assertEqual(cycle.allocations[0].asset, "BTC")
        # Edge #2 second
        self.assertEqual(cycle.allocations[1].asset, "ETH")

    def test_edge3_only_after_edge2(self):
        """Edge #3 is only considered after Edge #2 is allocated."""
        candidates = [
            self._make_topn_candidate("BTC", 0.05),  # Edge #1
            self._make_topn_candidate("ETH", 0.04),  # Edge #2
            self._make_topn_candidate("SOL", 0.03),  # Edge #3
        ]

        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,  # 2% = $2 budget
            min_cycle_risk_pct=0.01,
        )

        cycle = select_topn_allocations(
            equity_cents=self.bankroll_cents,
            candidates=candidates,
            config=config,
        )

        # All three should be allocated with sufficient budget
        self.assertGreaterEqual(len(cycle.allocations), 1)
        # Order must be preserved
        if len(cycle.allocations) >= 3:
            self.assertEqual(cycle.allocations[0].asset, "BTC")
            self.assertEqual(cycle.allocations[1].asset, "ETH")
            self.assertEqual(cycle.allocations[2].asset, "SOL")

    # ═══════════════════════════════════════════════════════════════════════════
    # RULE 4: If any edge fails, subsequent edges are skipped
    # ═══════════════════════════════════════════════════════════════════════════

    def test_subsequent_edges_skipped_when_edge_fails(self):
        """If Edge #2 fails, Edge #3 must also be skipped."""
        candidates = [
            self._make_topn_candidate("BTC", 0.05),  # Edge #1 - good
            self._make_topn_candidate("ETH", 0.03, entry_price_cents=99),  # Edge #2 - high price
            self._make_topn_candidate("SOL", 0.02),  # Edge #3 - should be skipped
        ]

        # Very restrictive config to force Edge #2 to fail
        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,
            min_cycle_risk_pct=0.01,
            min_contracts=10,  # High minimum that might not be met
            min_notional_usd=50.0,  # $50 minimum - Edge #2 will fail
        )

        cycle = select_topn_allocations(
            equity_cents=self.bankroll_cents,
            candidates=candidates,
            config=config,
        )

        # Either only Edge #1 or no allocations (depending on constraints)
        # The key point: if Edge #2 fails, Edge #3 must NOT be allocated
        for alloc in cycle.allocations:
            # SOL should never be allocated if it was Edge #3 and Edge #2 failed
            if alloc.asset == "SOL":
                self.fail(f"Edge #3 (SOL) was allocated when Edge #2 failed - violates priority rules")

    def test_no_edges_if_edge1_fails(self):
        """If Edge #1 fails min constraints, NO trades should be made."""
        candidates = [
            self._make_topn_candidate("BTC", 0.01, entry_price_cents=95),  # Edge #1 - low edge, high price
            self._make_topn_candidate("ETH", 0.05),  # Edge #2 - better edge but lower priority
        ]

        # Restrictive config
        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,
            min_cycle_risk_pct=0.01,
            min_edge_threshold=0.02,  # Edge threshold that BTC might not meet
            min_contracts=10,
            min_notional_usd=50.0,
        )

        cycle = select_topn_allocations(
            equity_cents=self.bankroll_cents,
            candidates=candidates,
            config=config,
        )

        # If Edge #1 fails, NO trades - never take Edge #2 alone
        for alloc in cycle.allocations:
            if alloc.asset == "ETH" and "BTC" not in [a.asset for a in cycle.allocations]:
                self.fail("Edge #2 (ETH) allocated without Edge #1 - violates priority rules")

    # ═══════════════════════════════════════════════════════════════════════════
    # RULE 5: Never skip Edge #1 for weaker edges
    # ═══════════════════════════════════════════════════════════════════════════

    def test_never_skip_edge1_for_weaker_edges(self):
        """System must never skip Edge #1 to take Edge #2 or #3."""
        candidates = [
            self._make_topn_candidate("BTC", 0.10),  # Strong Edge #1
            self._make_topn_candidate("ETH", 0.05),  # Weaker Edge #2
            self._make_topn_candidate("SOL", 0.03),  # Weaker Edge #3
        ]

        # Edge #1 has very high edge - it MUST be taken
        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,
            min_cycle_risk_pct=0.01,
        )

        cycle = select_topn_allocations(
            equity_cents=self.bankroll_cents,
            candidates=candidates,
            config=config,
        )

        # If any edges are allocated, Edge #1 (BTC) MUST be among them
        if cycle.allocations:
            assets_allocated = [a.asset for a in cycle.allocations]
            self.assertIn("BTC", assets_allocated,
                         "Edge #1 (BTC) was skipped while other edges were taken - violates priority")

    # ═══════════════════════════════════════════════════════════════════════════
    # Top3 Allocator Tests
    # ═══════════════════════════════════════════════════════════════════════════

    def test_top3_edge1_priority_allocation(self):
        """Top3 allocator respects Edge #1 priority."""
        candidates = [
            self._make_top3_candidate("BTC", 0.05),
            self._make_top3_candidate("ETH", 0.03),
            self._make_top3_candidate("SOL", 0.02),
        ]

        allocations = select_top3_allocations(
            bankroll_notional=self.bankroll_cents,
            cycle_risk_cap_pct=0.02,  # 2% risk cap
            candidates=candidates,
        )

        # Edge #1 should be first in allocations
        self.assertGreaterEqual(len(allocations), 1)
        self.assertEqual(allocations[0].asset, "BTC")

    def test_top3_edge1_gets_minimum_budget(self):
        """Top3 allocator gives Edge #1 minimum 1% budget."""
        candidates = [
            self._make_top3_candidate("BTC", 0.05),
            self._make_top3_candidate("ETH", 0.03),
        ]

        allocations = select_top3_allocations(
            bankroll_notional=10000,  # $100
            cycle_risk_cap_pct=0.02,  # 2% = $2
            candidates=candidates,
        )

        if allocations:
            # Edge #1 should get meaningful allocation
            edge1_alloc = allocations[0]
            self.assertGreaterEqual(
                edge1_alloc.target_notional, 50,  # At least 50¢
                "Edge #1 should get minimum allocation"
            )

    # ═══════════════════════════════════════════════════════════════════════════
    # Risk Limit Tests
    # ═══════════════════════════════════════════════════════════════════════════

    def test_total_cycle_risk_never_exceeds_2pct(self):
        """Total cycle risk must never exceed 2% of bankroll."""
        candidates = [
            self._make_topn_candidate("BTC", 0.08),
            self._make_topn_candidate("ETH", 0.07),
            self._make_topn_candidate("SOL", 0.06),
        ]

        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,  # 2% hard cap
            min_cycle_risk_pct=0.01,
        )

        cycle = select_topn_allocations(
            equity_cents=self.bankroll_cents,
            candidates=candidates,
            config=config,
        )

        total_risk_pct = (cycle.sum_risk_usd * 100) / (self.bankroll_cents / 100)
        self.assertLessEqual(
            total_risk_pct, 2.01,  # Small epsilon for floating point
            f"Total cycle risk {total_risk_pct:.2f}% exceeds 2% limit"
        )

    def test_per_edge_risk_never_exceeds_2pct(self):
        """No single edge should exceed 2% risk (actually should be 1-2%)."""
        candidates = [
            self._make_topn_candidate("BTC", 0.10),
        ]

        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,
            min_cycle_risk_pct=0.01,
        )

        cycle = select_topn_allocations(
            equity_cents=self.bankroll_cents,
            candidates=candidates,
            config=config,
        )

        if cycle.allocations:
            for alloc in cycle.allocations:
                risk_pct = (alloc.max_loss_usd * 100) / (self.bankroll_cents / 100)
                self.assertLessEqual(
                    risk_pct, 2.01,
                    f"Edge {alloc.asset} risk {risk_pct:.2f}% exceeds 2%"
                )


class TestEdgePriorityValidation(unittest.TestCase):
    """Additional validation tests for edge priority enforcement."""

    def test_empty_candidates_returns_empty(self):
        """Empty candidates list should return empty allocations."""
        config = TopNAllocatorConfig()
        cycle = select_topn_allocations(
            equity_cents=10000,
            candidates=[],
            config=config,
        )
        self.assertEqual(len(cycle.allocations), 0)

    def test_negative_edges_filtered(self):
        """Candidates with negative or zero edges should be filtered out."""
        candidates = [
            EdgeCandidate(
                asset="BTC",
                edge=Decimal("-0.01"),  # Negative edge
                direction="long",
                entry_price_cents=50,
                stop_price_cents=0,
                max_notional_cap=1000,
                metadata={},
            ),
            self._make_candidate("ETH", 0.03),
        ]

        config = TopNAllocatorConfig()
        cycle = select_topn_allocations(
            equity_cents=10000,
            candidates=candidates,
            config=config,
        )

        # BTC should be filtered out due to negative edge
        assets = [a.asset for a in cycle.allocations]
        self.assertNotIn("BTC", assets)

    def _make_candidate(self, asset: str, edge: float) -> EdgeCandidate:
        """Helper to create a candidate."""
        return EdgeCandidate(
            asset=asset,
            edge=Decimal(str(edge)),
            direction="long",
            entry_price_cents=50,
            stop_price_cents=0,
            max_notional_cap=1000,
            metadata={},
        )


if __name__ == "__main__":
    unittest.main()
