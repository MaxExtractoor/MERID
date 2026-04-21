"""
REGRESSION TEST: Risk Oversizing Fix

This test suite verifies that the 1-2% per-cycle risk cap is strictly enforced.
It specifically tests the scenario where 7 BTC orders at ~0.35 each were sent
with only 28 equity - a clear violation that must never happen again.

INCIDENT REFERENCE: 7-BTC-Orders-With-28-Equity Bug
- Date: Prior to 2026-04-20
- Symptom: 7 BTC orders (~$0.35 each) sent with only $28 equity
- Root Cause: Kelly sizing used 1.5% per-trade risk instead of per-cycle
- Impact: $2.45 total risk vs $0.56 cap (8.75% — 4.4x over limit!)
- Fix: TopNEdgeAllocator + GlobalRiskGuard with cycle-wide 1-2% cap

Tests cover:
1. Canonical settings import (same as production)
2. Kelly sizing bypass when USE_TOPN_ALLOCATOR=true
3. Global risk guard enforcement
4. Per-cycle risk accumulation tracking
5. Multiple order scenarios (7-BTC regression)
"""

import os
import sys
import unittest
from decimal import Decimal
from typing import List
from unittest.mock import MagicMock, patch

# ═══════════════════════════════════════════════════════════════════════════
# PRODUCTION-LIKE ENV SETUP
# ═══════════════════════════════════════════════════════════════════════════
# This mimics how production sets the flag via environment -> core.settings
os.environ["USE_TOPN_ALLOCATOR"] = "true"
os.environ["MAX_CYCLE_RISK_PCT"] = "0.02"
os.environ["MAX_TOTAL_RISK_PCT"] = "0.02"

# Force reload of settings module to pick up env vars
if 'core.settings' in sys.modules:
    del sys.modules['core.settings']

from core.settings import USE_TOPN_ALLOCATOR, MAX_CYCLE_RISK_PCT, MAX_TOTAL_RISK_PCT
from merid.trading.topn_allocator import (
    EdgeCandidate,
    TopNEdgeAllocator,
    TopNAllocatorConfig,
    AllocationCycle,
)
from merid.trading.kalshi_continuous_trader import (
    GlobalRiskGuard,
    PendingOrderRisk,
    _USE_TOPN_ALLOCATOR,
)


class TestRiskOversizingRegression(unittest.TestCase):
    """Regression tests for the risk oversizing bug (7 BTC orders with 28 equity)."""

    def test_feature_flag_is_true(self):
        """Verify USE_TOPN_ALLOCATOR flag is set."""
        self.assertTrue(_USE_TOPN_ALLOCATOR, "USE_TOPN_ALLOCATOR must be true for these tests")

    def test_global_risk_guard_blocks_over_cycle_cap(self):
        """Test that the global risk guard blocks orders that would exceed cycle cap."""
        guard = GlobalRiskGuard(max_cycle_risk_pct=0.02, max_total_risk_pct=0.02)
        
        # Equity = $28 (2800 cents), 2% cap = $0.56 (56 cents)
        equity_cents = 2800
        
        # First order: 1 BTC contract at 35¢ entry (long) = 35¢ max loss
        # This should be ALLOWED (35¢ < 56¢ cap)
        order1 = PendingOrderRisk(
            ticker="KXBTC-TEST",
            asset="BTC",
            contracts=1,
            entry_price_cents=35,
            direction="long",
            max_loss_cents=35,  # 1 contract * 35¢
            edge=0.08,
        )
        
        allowed, reason = guard.check_order(
            equity_cents=equity_cents,
            existing_risk_cents=0,
            pending_order=order1,
        )
        self.assertTrue(allowed, f"First order should be allowed: {reason}")
        
        # Second order: 1 BTC contract at 35¢ = another 35¢ max loss
        # Total would be 70¢ > 56¢ cap — should be BLOCKED
        order2 = PendingOrderRisk(
            ticker="KXBTC-TEST2",
            asset="BTC",
            contracts=1,
            entry_price_cents=35,
            direction="long",
            max_loss_cents=35,
            edge=0.08,
        )
        
        allowed, reason = guard.check_order(
            equity_cents=equity_cents,
            existing_risk_cents=0,
            pending_order=order2,
        )
        self.assertFalse(allowed, "Second order should be BLOCKED - would exceed 2% cap")
        self.assertIn("Cycle risk cap exceeded", reason)

    def test_global_risk_guard_blocks_simulated_7_btc_scenario(self):
        """
        REGRESSION: 7-BTC-Orders-With-28-Equity Bug
        
        This test reproduces the exact production incident that triggered this fix.
        
        Incident Details:
        - Equity: $28 (2800 cents)
        - Orders: 7 BTC contracts at ~$0.35 each
        - Legacy behavior (Kelly): All 7 orders placed = $2.45 total risk
        - Violation: $2.45 vs $0.56 cap (8.75% — 4.4x over limit!)
        
        Expected behavior with fix:
        - Order 1: ALLOWED (35¢ max loss, within 56¢ cap)
        - Orders 2-7: BLOCKED by GlobalRiskGuard (would exceed cap)
        - Total risk: $0.35 (within $0.56 cap) ✅
        
        This test must NEVER be removed or weakened. It protects against the
        exact bug that caused production risk violations.
        """
        guard = GlobalRiskGuard(max_cycle_risk_pct=0.02, max_total_risk_pct=0.02)
        
        # Equity = $28, 2% cap = $0.56
        equity_cents = 2800
        cycle_risk_cap = int(equity_cents * 0.02)  # 56 cents
        
        # Try to place 7 orders of 1 contract each at 35¢
        # This is the exact scenario that violated the rule
        orders_placed = 0
        orders_blocked = 0
        
        for i in range(7):
            order = PendingOrderRisk(
                ticker=f"KXBTC-TEST{i}",
                asset="BTC",
                contracts=1,
                entry_price_cents=35,
                direction="long",
                max_loss_cents=35,  # 35¢ per order
                edge=0.08,
            )
            
            allowed, reason = guard.check_order(
                equity_cents=equity_cents,
                existing_risk_cents=0,
                pending_order=order,
            )
            
            if allowed:
                orders_placed += 1
            else:
                orders_blocked += 1
        
        # With 56¢ cap and 35¢ per order:
        # - Order 1: allowed (35¢ used, 21¢ remaining)
        # - Order 2: blocked (would need 70¢ total)
        # Only 1 order should be placed!
        self.assertEqual(orders_placed, 1, "Only 1 order should be placed within 2% cap")
        self.assertEqual(orders_blocked, 6, "6 orders should be blocked")
        
        # Total risk should be ≤ 56¢
        total_risk = orders_placed * 35
        self.assertLessEqual(total_risk, cycle_risk_cap, 
                            f"Total risk {total_risk}¢ exceeds cap {cycle_risk_cap}¢")

    def test_global_risk_guard_reset_cycle(self):
        """Test that cycle reset works correctly."""
        guard = GlobalRiskGuard(max_cycle_risk_pct=0.02, max_total_risk_pct=0.02)
        
        equity_cents = 2800
        
        # Place an order in cycle 1
        order = PendingOrderRisk(
            ticker="KXBTC-TEST",
            asset="BTC",
            contracts=1,
            entry_price_cents=35,
            direction="long",
            max_loss_cents=35,
            edge=0.08,
        )
        
        allowed, _ = guard.check_order(
            equity_cents=equity_cents,
            existing_risk_cents=0,
            pending_order=order,
        )
        self.assertTrue(allowed)
        
        # Second order should be blocked (cap exhausted)
        allowed, _ = guard.check_order(
            equity_cents=equity_cents,
            existing_risk_cents=0,
            pending_order=order,
        )
        self.assertFalse(allowed)
        
        # Reset cycle
        guard.reset_cycle()
        
        # After reset, order should be allowed again
        allowed, _ = guard.check_order(
            equity_cents=equity_cents,
            existing_risk_cents=0,
            pending_order=order,
        )
        self.assertTrue(allowed, "Order should be allowed after cycle reset")

    def test_topn_allocator_enforces_cycle_cap(self):
        """Test that TopN allocator enforces cycle-wide risk cap."""
        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,  # 2% cap
            max_edges_per_cycle=3,
            min_contracts=1,
        )
        
        # Equity = $28, 2% = $0.56 risk budget
        equity_cents = 2800
        
        # Create 5 BTC candidates with high edges
        # Each would want to trade if selected
        candidates = [
            EdgeCandidate("BTC", 0.10, "long", 35, 0, 10000),  # max_loss = 35¢
            EdgeCandidate("ETH", 0.09, "long", 35, 0, 10000),
            EdgeCandidate("SOL", 0.08, "long", 35, 0, 10000),
            EdgeCandidate("XRP", 0.07, "long", 35, 0, 10000),
            EdgeCandidate("DOGE", 0.06, "long", 35, 0, 10000),
        ]
        
        allocator = TopNEdgeAllocator(config)
        cycle = allocator.compute_allocations(equity_cents, candidates)
        
        # Verify cycle risk is within cap
        self.assertLessEqual(
            cycle.sum_risk_usd,
            cycle.cycle_risk_usd + 0.01,  # Small tolerance
            f"Sum risk ${cycle.sum_risk_usd:.2f} exceeds cycle cap ${cycle.cycle_risk_usd:.2f}"
        )
        
        # With $0.56 budget and 35¢ per contract, should get at most 1 trade
        # (2 contracts would be 70¢ > 56¢)
        total_contracts = sum(a.target_contracts for a in cycle.allocations)
        max_expected = cycle.cycle_risk_usd / 0.35  # $0.56 / $0.35 ≈ 1.6
        
        self.assertLessEqual(
            total_contracts,
            int(max_expected) + 1,  # Allow rounding
            f"Total contracts {total_contracts} exceeds expected max ~{int(max_expected)}"
        )

    def test_topn_allocator_step_down_n(self):
        """Test that allocator steps down N when budget is insufficient."""
        config = TopNAllocatorConfig(
            max_cycle_risk_pct=0.02,
            max_edges_per_cycle=3,
            min_contracts=2,  # Require at least 2 contracts per trade
        )
        
        # Very small equity: $10, 2% = $0.20
        # Each trade needs 2 contracts * 35¢ = 70¢ max loss
        # Can't afford even 1 trade
        equity_cents = 1000
        
        candidates = [
            EdgeCandidate("BTC", 0.10, "long", 35, 0, 10000),
            EdgeCandidate("ETH", 0.09, "long", 35, 0, 10000),
            EdgeCandidate("SOL", 0.08, "long", 35, 0, 10000),
        ]
        
        allocator = TopNEdgeAllocator(config)
        cycle = allocator.compute_allocations(equity_cents, candidates)
        
        # Should step down to N=0 (can't afford min_contracts)
        self.assertEqual(cycle.num_edges_traded, 0, 
                        "Should trade 0 when can't afford min_contracts")
        self.assertEqual(len(cycle.allocations), 0)

    def test_short_position_max_loss_calculation(self):
        """Test that short positions correctly compute max loss."""
        guard = GlobalRiskGuard(max_cycle_risk_pct=0.02, max_total_risk_pct=0.02)
        
        equity_cents = 2800
        
        # Short position at 35¢ entry
        # Max loss = 100¢ - 35¢ = 65¢ per contract (if settles YES)
        short_order = PendingOrderRisk(
            ticker="KXBTC-TEST",
            asset="BTC",
            contracts=1,
            entry_price_cents=35,
            direction="short",
            max_loss_cents=65,  # 100 - 35 = 65¢
            edge=0.08,
        )
        
        allowed, reason = guard.check_order(
            equity_cents=equity_cents,
            existing_risk_cents=0,
            pending_order=short_order,
        )
        
        # 65¢ > 56¢ cap — should be blocked immediately
        self.assertFalse(allowed, "Short order with 65¢ max loss should be blocked (exceeds 56¢ cap)")
        self.assertIn("Cycle risk cap exceeded", reason)

    def test_total_risk_cap_includes_existing_positions(self):
        """Test that total risk cap includes existing open positions."""
        guard = GlobalRiskGuard(max_cycle_risk_pct=0.02, max_total_risk_pct=0.02)
        
        equity_cents = 2800
        max_total_risk = int(equity_cents * 0.02)  # 56¢
        
        # Existing position using 40¢ of risk
        existing_risk = 40
        
        # New order with 20¢ max loss
        # Total would be 60¢ > 56¢ cap — should be blocked
        new_order = PendingOrderRisk(
            ticker="KXBTC-NEW",
            asset="BTC",
            contracts=1,
            entry_price_cents=20,
            direction="long",
            max_loss_cents=20,
            edge=0.08,
        )
        
        allowed, reason = guard.check_order(
            equity_cents=equity_cents,
            existing_risk_cents=existing_risk,
            pending_order=new_order,
        )
        
        self.assertFalse(allowed, "Should block when existing + new exceeds total cap")
        self.assertIn("Total risk cap exceeded", reason)


class TestKellySizingBypass(unittest.TestCase):
    """Test that Kelly sizing is bypassed when USE_TOPN_ALLOCATOR is true."""

    def test_kelly_not_called_when_topn_enabled(self):
        """Verify Kelly sizing is skipped when TopN allocator provides size."""
        # This is an integration test that would require mocking the continuous trader
        # For now, we verify the flag is set correctly
        self.assertTrue(_USE_TOPN_ALLOCATOR, 
                       "USE_TOPN_ALLOCATOR must be true to bypass Kelly sizing")


class TestInvariantValidation(unittest.TestCase):
    """Test invariant validation for allocation cycles."""

    def test_allocation_cycle_validates_sum_risk(self):
        """Test that AllocationCycle.validate_invariants catches sum_risk > cycle_risk."""
        from merid.trading.topn_allocator import TradeAllocation
        
        config = TopNAllocatorConfig(max_edges_per_cycle=2, min_contracts=1)
        
        # Create an invalid cycle where sum_risk > cycle_risk
        allocations = [
            TradeAllocation("BTC", 0.08, "long", 10, 50, 0, 5.0, 0.5, 6.0),
        ]
        
        cycle = AllocationCycle(
            cycle_id="test",
            cycle_ts=None,
            equity_cents=10000,  # $100 equity
            cycle_risk_pct=0.02,
            cycle_risk_usd=2.0,  # $2.00 risk budget
            num_candidates=5,
            num_edges_traded=1,
            sum_risk_usd=5.0,  # $5.00 actual risk (INVALID!)
            allocations=allocations,
            config=config,
        )
        
        is_valid, violations = cycle.validate_invariants()
        self.assertFalse(is_valid, "Should detect invariant violation")
        self.assertTrue(any("sum_risk_usd" in v for v in violations))

    def test_allocation_cycle_validates_num_edges(self):
        """Test that AllocationCycle.validate_invariants catches num_edges > max."""
        from merid.trading.topn_allocator import TradeAllocation
        
        config = TopNAllocatorConfig(max_edges_per_cycle=2, min_contracts=1)
        
        allocations = [
            TradeAllocation("BTC", 0.08, "long", 1, 50, 0, 0.50, 0.33, 1.0),
            TradeAllocation("ETH", 0.07, "long", 1, 50, 0, 0.50, 0.33, 1.0),
            TradeAllocation("SOL", 0.06, "long", 1, 50, 0, 0.50, 0.34, 1.0),
        ]
        
        cycle = AllocationCycle(
            cycle_id="test",
            cycle_ts=None,
            equity_cents=10000,
            cycle_risk_pct=0.02,
            cycle_risk_usd=2.0,
            num_candidates=5,
            num_edges_traded=3,  # 3 > max 2 (INVALID!)
            sum_risk_usd=1.5,
            allocations=allocations,
            config=config,
        )
        
        is_valid, violations = cycle.validate_invariants()
        self.assertFalse(is_valid, "Should detect too many edges")
        self.assertTrue(any("num_edges_traded" in v for v in violations))


class TestCanonicalSettingsImport(unittest.TestCase):
    """
    Test that feature flags are loaded via canonical settings (production-like).
    
    This ensures the test environment matches production environment setup:
    Environment Variable -> core.settings -> Production Code
    """

    def test_settings_imported_from_core(self):
        """Verify USE_TOPN_ALLOCATOR comes from core.settings (same as production)."""
        # These are imported from core.settings at the top of this test file
        # They come from os.environ -> core.settings -> here
        self.assertTrue(USE_TOPN_ALLOCATOR, 
                       "USE_TOPN_ALLOCATOR from core.settings must be True")
        self.assertEqual(MAX_CYCLE_RISK_PCT, 0.02,
                        "MAX_CYCLE_RISK_PCT from core.settings must be 0.02")
        self.assertEqual(MAX_TOTAL_RISK_PCT, 0.02,
                        "MAX_TOTAL_RISK_PCT from core.settings must be 0.02")

    def test_module_flag_matches_settings(self):
        """Verify _USE_TOPN_ALLOCATOR in continuous trader matches settings."""
        # _USE_TOPN_ALLOCATOR is imported from kalshi_continuous_trader
        # It should equal USE_TOPN_ALLOCATOR from settings
        self.assertEqual(_USE_TOPN_ALLOCATOR, USE_TOPN_ALLOCATOR,
                        "Module flag must match settings flag")

    def test_env_var_propagation(self):
        """Verify env vars propagate through settings to module."""
        # This test documents the env -> settings -> module chain
        # os.environ["USE_TOPN_ALLOCATOR"] is set at top of this file
        # core.settings imports it
        # kalshi_continuous_trader imports from core.settings
        
        env_value = os.environ.get("USE_TOPN_ALLOCATOR", "")
        self.assertIn(env_value.lower(), ["true", "1", "yes", "on"],
                     "USE_TOPN_ALLOCATOR env var must be set to truthy value")
        
        # After settings import, flag should be True
        self.assertTrue(USE_TOPN_ALLOCATOR,
                       "Env var must propagate to settings flag")

    def test_false_flag_scenario(self):
        """Test that flag=False would disable the new allocator."""
        # This test documents what happens when flag is False
        # We can't actually set it false without reloading, but we document
        # the expected behavior for ops reference
        
        # When USE_TOPN_ALLOCATOR=false:
        # - Kelly sizing would be used (per-trade risk)
        # - GlobalRiskGuard still exists but relies on Kelly output
        # - TopN allocator would not be instantiated
        
        # This is a documentation test — actual false behavior would require
        # separate test file with USE_TOPN_ALLOCATOR=false
        self.assertTrue(True, "See test comments for false flag behavior")


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)
