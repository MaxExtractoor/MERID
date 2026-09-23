"""
Unit tests for Top3EdgeAllocator — the core selection and sizing algorithm.
"""

import pytest
from decimal import Decimal

from merid.trading.top3_edge_allocator import (
    EdgeCandidate,
    Top3Allocation,
    Top3EdgeAllocator,
    Top3SelectionSpec,
    select_top3_allocations,
    get_top3_allocator,
)


class TestTop3SelectionSpec:
    """Tests for the formal specification and invariants."""
    
    def test_max_assets_is_3(self):
        """Invariant 1: At most 3 assets can be selected (CRITICAL FIX: was 5, now 3)."""
        spec = Top3SelectionSpec()
        assert spec.MAX_ASSETS == 3
    
    def test_valid_assets_are_5_crypto(self):
        """Only 5 crypto assets are valid candidates."""
        spec = Top3SelectionSpec()
        assert spec.VALID_ASSETS == ("BTC", "ETH", "SOL", "XRP", "DOGE")
    
    def test_default_risk_cap_is_fixed_usd(self):
        """Default cycle risk cap is the fixed $1.00 USD cap (percentage model removed)."""
        spec = Top3SelectionSpec()
        assert spec.DEFAULT_CYCLE_RISK_CAP_USD == 1.00


class TestSelectTop3Basic:
    """Tests for basic selection behavior with 3+ candidates."""
    
    def test_selects_top_3_by_edge(self):
        """Should select assets with highest edges using sequential fill (Edge #1 priority)."""
        # Per-asset caps below the cycle budget so all top-3 edges get funded.
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=150),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=150),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=150),
            EdgeCandidate("XRP", edge=0.04, max_notional_cap=150),
            EdgeCandidate("DOGE", edge=0.02, max_notional_cap=150),
        ]

        bankroll = 100_000  # cents (unused in fixed-USD model)
        cap_usd = 5.00  # 500c cycle budget

        allocations = select_top3_allocations(bankroll, cap_usd, candidates)

        # Sequential priority-fill: each edge takes min(per-asset cap, remaining
        # budget); the $5 budget funds all three 150c caps.
        assert len(allocations) == 3

        # Should be BTC, ETH, SOL (top 3 edges), never XRP/DOGE
        assets = [a.asset for a in allocations]
        assert assets == ["BTC", "ETH", "SOL"]
        assert "XRP" not in assets
        assert "DOGE" not in assets
    
    def test_weighted_sizing_by_edge(self):
        """Sizes follow sequential fill: Edge #1 gets 1% minimum, then remaining budget."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=150),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=150),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=150),
        ]

        bankroll = 100_000
        cap_usd = 5.00  # 500c budget

        allocations = select_top3_allocations(bankroll, cap_usd, candidates)

        # Priority fill: Edge #1 funded first to its full cap.
        total = sum(a.target_notional for a in allocations)
        assert total <= 500

        btc_alloc = allocations[0]
        assert btc_alloc.asset == "BTC"
        assert btc_alloc.target_notional == 150

        assert len(allocations) == 3
    
    def test_respects_per_asset_cap(self):
        """Should not exceed per-asset max_notional_cap."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=150),  # Low cap
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=150),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=150),
        ]

        bankroll = 1_000_000
        cap_usd = 5.00

        allocations = select_top3_allocations(bankroll, cap_usd, candidates)

        # BTC should be capped at 150 (its per-asset cap)
        btc_alloc = next(a for a in allocations if a.asset == "BTC")
        assert btc_alloc.target_notional <= 150


class TestSelectTop3Ties:
    """Tests for edge tie-breaking behavior."""
    
    def test_equal_edges_get_even_split(self):
        """Equal edges use sequential fill: Edge #1 gets 1% minimum, Edge #2 gets remaining."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=150),
            EdgeCandidate("ETH", edge=0.10, max_notional_cap=150),
            EdgeCandidate("SOL", edge=0.10, max_notional_cap=150),
        ]

        bankroll = 90_000
        cap_usd = 5.00

        allocations = select_top3_allocations(bankroll, cap_usd, candidates)

        # Equal edges + equal caps: all three funded equally at their cap.
        assert len(allocations) == 3
        for alloc in allocations:
            assert alloc.target_notional == 150
    
    def test_two_equal_one_different(self):
        """Two equal edges and one different with sequential fill."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=150),
            EdgeCandidate("ETH", edge=0.10, max_notional_cap=150),  # Equal to BTC
            EdgeCandidate("SOL", edge=0.05, max_notional_cap=150),  # Different
        ]

        bankroll = 100_000
        cap_usd = 5.00

        allocations = select_top3_allocations(bankroll, cap_usd, candidates)

        assert len(allocations) == 3

        # BTC and ETH (equal top edges) funded first, equally at their cap.
        btc_alloc = next(a for a in allocations if a.asset == "BTC")
        eth_alloc = next(a for a in allocations if a.asset == "ETH")
        assert btc_alloc.target_notional == eth_alloc.target_notional == 150
        assert allocations.index(btc_alloc) < allocations.index(eth_alloc)


class TestSelectTop3EdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_fewer_than_3_valid_candidates(self):
        """Should handle only 2 valid candidates."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=150),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=150),
        ]

        bankroll = 100_000
        cap_usd = 5.00

        allocations = select_top3_allocations(bankroll, cap_usd, candidates)

        assert len(allocations) == 2
        assert {a.asset for a in allocations} == {"BTC", "ETH"}
    
    def test_only_1_valid_candidate(self):
        """Should handle single valid candidate with sequential fill."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=150),
        ]

        bankroll = 100_000
        cap_usd = 5.00

        allocations = select_top3_allocations(bankroll, cap_usd, candidates)

        assert len(allocations) == 1
        assert allocations[0].asset == "BTC"
        # Edge #1 takes min(per-asset cap, full budget)
        assert allocations[0].target_notional == 150
    
    def test_zero_edge_candidates_return_empty(self):
        """Zero or negative edges should result in no allocations."""
        candidates = [
            EdgeCandidate("BTC", edge=0.0, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=-0.01, max_notional_cap=4000),
        ]
        
        bankroll = 100_000
        cap_pct = 0.02
        
        allocations = select_top3_allocations(bankroll, cap_pct, candidates)
        
        assert len(allocations) == 0
    
    def test_all_zero_edges_return_empty(self):
        """All zero edges should return empty list."""
        candidates = [
            EdgeCandidate("BTC", edge=0.0, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.0, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.0, max_notional_cap=3000),
        ]
        
        allocations = select_top3_allocations(100_000, 0.02, candidates)
        
        assert len(allocations) == 0
    
    def test_empty_candidates_return_empty(self):
        """Empty candidate list should return empty list."""
        allocations = select_top3_allocations(100_000, 0.02, [])
        assert len(allocations) == 0
    
    def test_invalid_asset_filtered(self):
        """Assets not in valid list should be filtered out."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=150),
            EdgeCandidate("INVALID", edge=0.09, max_notional_cap=150),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=150),
        ]

        bankroll = 100_000
        cap_usd = 5.00

        allocations = select_top3_allocations(bankroll, cap_usd, candidates)
        
        # INVALID should be excluded
        assets = [a.asset for a in allocations]
        assert "INVALID" not in assets
        assert "BTC" in assets
        assert "ETH" in assets
    
    def test_zero_cycle_cap_returns_empty(self):
        """Zero cycle risk cap (no budget) should return empty list."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
        ]

        # Bankroll is unused in the fixed-USD model; the cap is the budget.
        allocations = select_top3_allocations(100_000, 0.0, candidates)
        assert len(allocations) == 0
    
    def test_sum_of_allocations_within_cap(self):
        """Invariant 2: Total notional must be <= cap * bankroll."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=150),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=150),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=150),
            EdgeCandidate("XRP", edge=0.04, max_notional_cap=150),
            EdgeCandidate("DOGE", edge=0.02, max_notional_cap=150),
        ]

        bankroll = 100_000
        cap_usd = 5.00

        allocations = select_top3_allocations(bankroll, cap_usd, candidates)

        total = sum(a.target_notional for a in allocations)
        max_allowed = int(cap_usd * 100)

        assert total <= max_allowed, f"Total {total} exceeds cap {max_allowed}"


class TestTop3EdgeAllocator:
    """Tests for the Top3EdgeAllocator class."""
    
    def test_singleton_behavior(self):
        """get_top3_allocator should return singleton."""
        a1 = get_top3_allocator()
        a2 = get_top3_allocator()
        assert a1 is a2
    
    def test_compute_allocations_returns_valid_list(self):
        """compute_allocations should return valid Top3Allocation list."""
        allocator = Top3EdgeAllocator()
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        allocations = allocator.compute_allocations(100_000, candidates)
        
        assert isinstance(allocations, list)
        assert len(allocations) <= 3
        for a in allocations:
            assert isinstance(a, Top3Allocation)
    
    def test_validate_invariants_passes_for_valid(self):
        """validate_invariants should return True for valid allocations."""
        allocator = Top3EdgeAllocator()
        
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        allocations = allocator.compute_allocations(100_000, candidates)
        
        assert allocator.validate_invariants(allocations, 100_000) is True
    
    def test_validate_invariants_fails_for_too_many_assets(self):
        """validate_invariants should fail if > 3 assets."""
        allocator = Top3EdgeAllocator()
        
        # Manually create invalid allocations
        invalid_allocations = [
            Top3Allocation("BTC", 0.1, 1000, 0.2),
            Top3Allocation("ETH", 0.1, 1000, 0.2),
            Top3Allocation("SOL", 0.1, 1000, 0.2),
            Top3Allocation("XRP", 0.1, 1000, 0.2),  # 4th asset - invalid
        ]
        
        assert allocator.validate_invariants(invalid_allocations, 100_000) is False
    
    def test_get_cycle_risk_cap_usd_returns_valid_value(self):
        """get_cycle_risk_cap_usd should return the USD cap within its clamp range."""
        allocator = Top3EdgeAllocator()
        usd = allocator.get_cycle_risk_cap_usd()

        assert 0.50 <= usd <= 5.00


class TestTop3EnvironmentConfig:
    """Tests for environment variable configuration."""
    
    def test_respects_top3_cycle_risk_cap_env(self, monkeypatch):
        """Should read TOP3_CYCLE_RISK_CAP_USD from environment."""
        monkeypatch.setenv("TOP3_CYCLE_RISK_CAP_USD", "1.50")

        # Need fresh instance since env is read at init
        from merid.trading.top3_edge_allocator import Top3EdgeAllocator
        allocator = Top3EdgeAllocator()

        assert allocator.get_cycle_risk_cap_usd() == 1.50

    def test_clamps_env_value_to_valid_range_high(self, monkeypatch):
        """Should clamp env value > $5.00 down to $5.00."""
        monkeypatch.setenv("TOP3_CYCLE_RISK_CAP_USD", "10.00")

        from merid.trading.top3_edge_allocator import Top3EdgeAllocator
        allocator = Top3EdgeAllocator()

        assert allocator.get_cycle_risk_cap_usd() == 5.00

    def test_clamps_env_value_to_valid_range_low(self, monkeypatch):
        """Should clamp env value < $0.50 up to $0.50."""
        monkeypatch.setenv("TOP3_CYCLE_RISK_CAP_USD", "0.10")

        from merid.trading.top3_edge_allocator import Top3EdgeAllocator
        allocator = Top3EdgeAllocator()

        assert allocator.get_cycle_risk_cap_usd() == 0.50
