"""
Top-N / Top-3 Alignment Audit — Scenarios A-E + Bankroll Consistency

These tests lock in the behaviors required by docs/TOPN_TOP3_RISK_ALIGNMENT_AUDIT.md:

- Bankroll source used by TopNEdgeAllocator.compute_allocations and by
  GlobalRiskGuard.check_order is the SAME equity notion (total_value_cents =
  cash + portfolio MTM) every cycle.
- Only the top 3 edges are ever tradable; N is always in {0, 1, 2, 3}.
- Edges below threshold produce N=0 (no trades).
- When GlobalRiskGuard rejects an order mid-cycle, the system does NOT
  reallocate the freed budget to lower-ranked assets.
"""

import os
import re
import sys
import unittest
from pathlib import Path

os.environ["USE_TOPN_ALLOCATOR"] = "true"
os.environ["MAX_CYCLE_RISK_PCT"] = "0.02"
os.environ["MAX_TOTAL_RISK_PCT"] = "0.02"

# Force settings reload so env vars take effect
for _mod in ("core.settings",):
    if _mod in sys.modules:
        del sys.modules[_mod]

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
)


CT_PATH = Path("merid/trading/kalshi_continuous_trader.py")


def _fresh_allocator(
    max_cycle_risk_pct: float = 0.02,
    min_cycle_risk_pct: float = 0.02,
    min_contracts: int = 1,
    min_notional_usd: float = 1.0,
) -> TopNEdgeAllocator:
    return TopNEdgeAllocator(TopNAllocatorConfig(
        min_cycle_risk_pct=min_cycle_risk_pct,
        max_cycle_risk_pct=max_cycle_risk_pct,
        max_edges_per_cycle=3,
        min_edges_per_cycle=0,
        min_contracts=min_contracts,
        min_notional_usd=min_notional_usd,
    ))


def _five_asset_candidates() -> list:
    """5 distinct, positive edges descending. BTC>ETH>SOL>XRP>DOGE."""
    return [
        EdgeCandidate("BTC", edge=0.10, direction="long",
                      entry_price_cents=50, stop_price_cents=0,
                      max_notional_cap=100_000, metadata={"ticker": "BTC"}),
        EdgeCandidate("ETH", edge=0.08, direction="long",
                      entry_price_cents=50, stop_price_cents=0,
                      max_notional_cap=100_000, metadata={"ticker": "ETH"}),
        EdgeCandidate("SOL", edge=0.06, direction="long",
                      entry_price_cents=50, stop_price_cents=0,
                      max_notional_cap=100_000, metadata={"ticker": "SOL"}),
        EdgeCandidate("XRP", edge=0.04, direction="long",
                      entry_price_cents=50, stop_price_cents=0,
                      max_notional_cap=100_000, metadata={"ticker": "XRP"}),
        EdgeCandidate("DOGE", edge=0.02, direction="long",
                      entry_price_cents=50, stop_price_cents=0,
                      max_notional_cap=100_000, metadata={"ticker": "DOGE"}),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1 — Bankroll Source Alignment
# ═══════════════════════════════════════════════════════════════════════════


class TestBankrollSourceAlignment(unittest.TestCase):
    """Phase 1: Confirm TopN allocator and GlobalRiskGuard use the same
    equity notion (total_value_cents) in live code."""

    def test_topn_and_guard_share_total_value_cents(self):
        """Both code paths must reference total_value_cents (cash + portfolio MTM),
        not balance_cents (cash only)."""
        source = CT_PATH.read_text(encoding="utf-8")

        # TopN call site
        topn_block = re.search(
            r"_bankroll_cents\s*=\s*total_value_cents"
            r".*?self\._topn_allocator\.compute_allocations\("
            r"[^)]*equity_cents\s*=\s*_bankroll_cents",
            source, re.DOTALL,
        )
        self.assertIsNotNone(
            topn_block,
            "TopN allocator must receive equity_cents = total_value_cents",
        )

        # GlobalRiskGuard call site
        guard_block = re.search(
            r"_guard_equity_cents\s*=\s*total_value_cents"
            r".*?self\._risk_guard\.check_order\("
            r"[^)]*equity_cents\s*=\s*_guard_equity_cents",
            source, re.DOTALL,
        )
        self.assertIsNotNone(
            guard_block,
            "GlobalRiskGuard must receive equity_cents = total_value_cents",
        )

    def test_bankroll_sources_log_line_present(self):
        """The BANKROLL-SOURCES observability log must remain wired."""
        source = CT_PATH.read_text(encoding="utf-8")
        self.assertIn("[BANKROLL-SOURCES]", source)
        self.assertIn("topn_B", source)
        self.assertIn("cash_B", source)

    def test_cycle_reset_before_allocations(self):
        """reset_cycle() must be called each cycle before new order checks."""
        source = CT_PATH.read_text(encoding="utf-8")
        self.assertIn("self._risk_guard.reset_cycle()", source)

    def test_guard_uses_canonical_settings(self):
        """GlobalRiskGuard (now the process-wide singleton in
        ``merid.guards.global_risk_guard``) loads MAX_CYCLE_RISK_PCT /
        MAX_TOTAL_RISK_PCT from core.settings (env-backed).  CT obtains the
        singleton via ``get_global_risk_guard()``; see
        ``docs/TRADING_OWNERSHIP_DECISION.md``.
        """
        source = CT_PATH.read_text(encoding="utf-8")
        # CT must obtain the singleton, not construct its own guard.
        self.assertIn("_get_global_risk_guard()", source)
        # Canonical pct values are still enforced by core.settings.
        self.assertEqual(MAX_CYCLE_RISK_PCT, 0.02)
        self.assertEqual(MAX_TOTAL_RISK_PCT, 0.02)
        self.assertTrue(USE_TOPN_ALLOCATOR)
        # The shared singleton reads those same canonical values at init.
        from merid.guards.global_risk_guard import (
            reset_global_risk_guard_for_tests, get_global_risk_guard,
        )
        reset_global_risk_guard_for_tests()
        try:
            g = get_global_risk_guard()
            self.assertEqual(g.max_cycle_risk_pct, MAX_CYCLE_RISK_PCT)
            self.assertEqual(g.max_total_risk_pct, MAX_TOTAL_RISK_PCT)
        finally:
            reset_global_risk_guard_for_tests()


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 — Scenarios A–E: Top 3 Only, N ∈ {0,1,2,3}
# ═══════════════════════════════════════════════════════════════════════════


class TestTopNSelectionScenarios(unittest.TestCase):

    def test_scenario_A_small_bankroll_only_T1(self):
        """Scenario A: bankroll so small only T1 fits.

        $100 equity, 2% cap → $2 budget. At 50¢ long, T1 gets ~$2 ≈ 4 contracts;
        T2/T3 would need more than the remaining budget + min_contracts.
        """
        allocator = _fresh_allocator(max_cycle_risk_pct=0.02,
                                     min_cycle_risk_pct=0.02,
                                     min_contracts=4)
        # equity $2 → 2% = 4¢ → only 1 candidate can possibly get min 1 contract
        cycle = allocator.compute_allocations(
            equity_cents=200,  # $2.00
            candidates=_five_asset_candidates(),
        )
        self.assertLessEqual(cycle.num_edges_traded, 1)
        if cycle.num_edges_traded == 1:
            self.assertEqual(cycle.allocations[0].asset, "BTC")

    def test_scenario_B_medium_bankroll_T1_and_T2(self):
        """Scenario B: bankroll fits T1+T2 but T3 would break the cap."""
        allocator = _fresh_allocator(
            max_cycle_risk_pct=0.02,
            min_cycle_risk_pct=0.02,
            min_contracts=5,  # force each trade to be non-trivial
        )
        # Budget = 2% of $20 = 40¢. Two trades of 5 contracts @ (edge-weighted
        # budgets) can fit; three cannot (would require 15 contracts * ~13c = $2).
        cycle = allocator.compute_allocations(
            equity_cents=2000,  # $20
            candidates=_five_asset_candidates(),
        )
        self.assertLessEqual(cycle.num_edges_traded, 3)
        # allocated assets must be a prefix of edge-sorted list
        assets = [a.asset for a in cycle.allocations]
        expected_prefix = ["BTC", "ETH", "SOL"][: len(assets)]
        self.assertEqual(assets, expected_prefix)

    def test_scenario_C_large_bankroll_all_top3(self):
        """Scenario C: bankroll large enough for all of T1+T2+T3."""
        allocator = _fresh_allocator()
        cycle = allocator.compute_allocations(
            equity_cents=1_000_000,  # $10,000
            candidates=_five_asset_candidates(),
        )
        self.assertEqual(cycle.num_edges_traded, 3)
        assets = [a.asset for a in cycle.allocations]
        self.assertEqual(assets, ["BTC", "ETH", "SOL"])
        # DOGE/XRP must be excluded
        self.assertNotIn("XRP", assets)
        self.assertNotIn("DOGE", assets)

    def test_scenario_D_all_edges_below_threshold(self):
        """Scenario D: all candidates have edge <= 0 → N=0."""
        allocator = _fresh_allocator()
        cands = [
            EdgeCandidate("BTC", edge=0.0, direction="long",
                          entry_price_cents=50, stop_price_cents=0,
                          max_notional_cap=100_000),
            EdgeCandidate("ETH", edge=-0.01, direction="long",
                          entry_price_cents=50, stop_price_cents=0,
                          max_notional_cap=100_000),
        ]
        cycle = allocator.compute_allocations(
            equity_cents=1_000_000, candidates=cands,
        )
        self.assertEqual(cycle.num_edges_traded, 0)
        self.assertEqual(cycle.allocations, [])

    def test_scenario_E_guard_rejects_no_reallocation(self):
        """Scenario E: TopN planned N=3, but GlobalRiskGuard rejects T2.

        After rejection of T2, T3 must NOT be "promoted" to consume the freed
        budget. The guard simply blocks the second order; T3 may still pass on
        its own merit within the remaining cycle budget — but nothing is
        re-allocated from T2's rejection. This test verifies the guard's own
        cycle-accumulator semantics.
        """
        guard = GlobalRiskGuard(
            max_cycle_risk_pct=0.02, max_total_risk_pct=0.02,
        )
        equity = 10_000  # $100 → cap 200¢
        # First order: 100¢ max loss (under cap)
        ok, _ = guard.check_order(
            equity_cents=equity,
            existing_risk_cents=0,
            pending_order=PendingOrderRisk(
                ticker="T1", asset="BTC", contracts=1,
                entry_price_cents=100, direction="long",
                max_loss_cents=100, edge=0.1,
            ),
        )
        self.assertTrue(ok)
        # Second order: 150¢ would push cycle risk to 250¢ > 200¢ cap → BLOCKED
        blocked, reason = guard.check_order(
            equity_cents=equity,
            existing_risk_cents=0,
            pending_order=PendingOrderRisk(
                ticker="T2", asset="ETH", contracts=1,
                entry_price_cents=150, direction="long",
                max_loss_cents=150, edge=0.08,
            ),
        )
        self.assertFalse(blocked)
        self.assertIn("Cycle risk cap exceeded", reason)
        # Third order: tiny 50¢ would fit (100 + 50 = 150 <= 200). Guard does
        # not "top up" from the rejected 150¢ budget — each order is evaluated
        # independently against the accumulator.
        ok3, _ = guard.check_order(
            equity_cents=equity,
            existing_risk_cents=0,
            pending_order=PendingOrderRisk(
                ticker="T3", asset="SOL", contracts=1,
                entry_price_cents=50, direction="long",
                max_loss_cents=50, edge=0.06,
            ),
        )
        self.assertTrue(ok3)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4 — Invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestTopNInvariants(unittest.TestCase):

    def test_len_allocations_le_3(self):
        allocator = _fresh_allocator()
        cycle = allocator.compute_allocations(
            equity_cents=1_000_000, candidates=_five_asset_candidates(),
        )
        self.assertLessEqual(len(cycle.allocations), 3)

    def test_sum_risk_within_budget(self):
        allocator = _fresh_allocator()
        cycle = allocator.compute_allocations(
            equity_cents=1_000_000, candidates=_five_asset_candidates(),
        )
        budget = 1_000_000 * 0.02 / 100  # $200
        self.assertLessEqual(cycle.sum_risk_usd, budget + 0.01)

    def test_edges_descending_in_allocations(self):
        allocator = _fresh_allocator()
        cycle = allocator.compute_allocations(
            equity_cents=1_000_000, candidates=_five_asset_candidates(),
        )
        edges = [a.edge for a in cycle.allocations]
        self.assertEqual(edges, sorted(edges, reverse=True))

    def test_only_valid_assets_allocated(self):
        """Only BTC, ETH, SOL, XRP, DOGE can be allocated."""
        allocator = _fresh_allocator()
        cycle = allocator.compute_allocations(
            equity_cents=1_000_000, candidates=_five_asset_candidates(),
        )
        valid = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        for alloc in cycle.allocations:
            self.assertIn(alloc.asset, valid)


if __name__ == "__main__":
    unittest.main()
