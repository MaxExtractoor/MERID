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
        """Invariant 1: At most 3 assets can be selected."""
        spec = Top3SelectionSpec()
        assert spec.MAX_ASSETS == 3
    
    def test_valid_assets_are_5_crypto(self):
        """Only 5 crypto assets are valid candidates."""
        spec = Top3SelectionSpec()
        assert spec.VALID_ASSETS == ("BTC", "ETH", "SOL", "XRP", "DOGE")
    
    def test_default_risk_cap_in_1_to_2_percent_range(self):
        """Default risk cap must be in [1%, 2%] range."""
        spec = Top3SelectionSpec()
        assert 0.01 <= spec.DEFAULT_CYCLE_RISK_CAP_PCT_MAX <= 0.02
        assert 0.01 <= spec.DEFAULT_CYCLE_RISK_CAP_PCT_MIN <= 0.02


class TestSelectTop3Basic:
    """Tests for basic selection behavior with 3+ candidates."""
    
    def test_selects_top_3_by_edge(self):
        """Should select assets with highest edges using sequential fill (Edge #1 priority)."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
            EdgeCandidate("XRP", edge=0.04, max_notional_cap=2000),
            EdgeCandidate("DOGE", edge=0.02, max_notional_cap=1000),
        ]
        
        bankroll = 100_000  # $1,000 in cents
        cap_pct = 0.02  # 2%
        
        allocations = select_top3_allocations(bankroll, cap_pct, candidates)
        
        # With sequential fill: Edge #1 gets 1% min ($10), Edge #2 gets remaining ($10), Edge #3 skipped
        # Total budget = $20 (2% of $1000)
        # Edge #1 (BTC): $10 budget
        # Edge #2 (ETH): $10 budget
        # Edge #3 (SOL): $0 remaining - skipped
        assert len(allocations) == 2
        
        # Should be BTC, ETH (top 2 edges that fit budget)
        assets = [a.asset for a in allocations]
        assert "BTC" in assets
        assert "ETH" in assets
        assert "SOL" not in assets
        assert "XRP" not in assets
        assert "DOGE" not in assets
    
    def test_weighted_sizing_by_edge(self):
        """Sizes follow sequential fill: Edge #1 gets 1% minimum, then remaining budget."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        bankroll = 100_000
        cap_pct = 0.02  # $2,000 total
        
        allocations = select_top3_allocations(bankroll, cap_pct, candidates)
        
        # Sequential fill: Edge #1 gets 1% min ($1000), Edge #2 gets remaining ($1000), Edge #3 skipped
        total = sum(a.target_notional for a in allocations)
        assert total <= 2000  # Within cap
        
        # Check Edge #1 gets minimum 1% budget
        btc_alloc = next(a for a in allocations if a.asset == "BTC")
        assert btc_alloc.target_notional >= 1000  # Minimum 1% of $100k = $1000
        
        # Check at least 2 edges allocated if budget allows
        assert len(allocations) >= 2
    
    def test_respects_per_asset_cap(self):
        """Should not exceed per-asset max_notional_cap."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=500),  # Low cap
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
        ]
        
        bankroll = 1_000_000  # $10,000
        cap_pct = 0.02  # Would be $200 without caps
        
        allocations = select_top3_allocations(bankroll, cap_pct, candidates)
        
        # BTC should be capped at 500
        btc_alloc = next(a for a in allocations if a.asset == "BTC")
        assert btc_alloc.target_notional <= 500


class TestSelectTop3Ties:
    """Tests for edge tie-breaking behavior."""
    
    def test_equal_edges_get_even_split(self):
        """Equal edges use sequential fill: Edge #1 gets 1% minimum, Edge #2 gets remaining."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("SOL", edge=0.10, max_notional_cap=5000),
        ]
        
        bankroll = 90_000  # $900 -> 2% = $18 = 1800 cents
        cap_pct = 0.02
        
        allocations = select_top3_allocations(bankroll, cap_pct, candidates)
        
        # Sequential fill: Edge #1 gets 1% min ($900), Edge #2 gets remaining ($900), Edge #3 skipped
        assert len(allocations) == 2
        
        # Both get equal allocation due to equal edges and sequential fill
        btc_alloc = next(a for a in allocations if a.asset == "BTC")
        eth_alloc = next(a for a in allocations if a.asset == "ETH")
        assert btc_alloc.target_notional == 900  # 1% of $900
        assert eth_alloc.target_notional == 900  # Remaining budget
    
    def test_two_equal_one_different(self):
        """Two equal edges and one different with sequential fill."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.10, max_notional_cap=5000),  # Equal to BTC
            EdgeCandidate("SOL", edge=0.05, max_notional_cap=5000),  # Different
        ]
        
        bankroll = 100_000
        cap_pct = 0.02  # $2,000
        
        allocations = select_top3_allocations(bankroll, cap_pct, candidates)
        
        # Sequential fill: Edge #1 gets 1% min ($1000), Edge #2 gets remaining ($1000), Edge #3 skipped
        assert len(allocations) == 2
        
        # BTC and ETH should be equal (both got $1000)
        btc_alloc = next(a for a in allocations if a.asset == "BTC")
        eth_alloc = next(a for a in allocations if a.asset == "ETH")
        assert btc_alloc.target_notional == eth_alloc.target_notional
        assert btc_alloc.target_notional == 1000  # 1% of $100k


class TestSelectTop3EdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_fewer_than_3_valid_candidates(self):
        """Should handle only 2 valid candidates."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
        ]
        
        bankroll = 100_000
        cap_pct = 0.02
        
        allocations = select_top3_allocations(bankroll, cap_pct, candidates)
        
        assert len(allocations) == 2
        assert {a.asset for a in allocations} == {"BTC", "ETH"}
    
    def test_only_1_valid_candidate(self):
        """Should handle single valid candidate with sequential fill."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
        ]
        
        bankroll = 100_000
        cap_pct = 0.02
        
        allocations = select_top3_allocations(bankroll, cap_pct, candidates)
        
        assert len(allocations) == 1
        assert allocations[0].asset == "BTC"
        # Sequential fill: Edge #1 gets minimum 1% ($1000) since it's the only edge
        assert allocations[0].target_notional == 1000  # Minimum 1% of $100k
    
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
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("INVALID", edge=0.09, max_notional_cap=4000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
        ]
        
        bankroll = 100_000
        cap_pct = 0.02
        
        allocations = select_top3_allocations(bankroll, cap_pct, candidates)
        
        # INVALID should be excluded
        assets = [a.asset for a in allocations]
        assert "INVALID" not in assets
        assert "BTC" in assets
        assert "ETH" in assets
    
    def test_zero_bankroll_returns_empty(self):
        """Zero or negative bankroll should return empty list."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
        ]
        
        allocations = select_top3_allocations(0, 0.02, candidates)
        assert len(allocations) == 0
        
        allocations = select_top3_allocations(-1000, 0.02, candidates)
        assert len(allocations) == 0
    
    def test_sum_of_allocations_within_cap(self):
        """Invariant 2: Total notional must be <= cap * bankroll."""
        candidates = [
            EdgeCandidate("BTC", edge=0.10, max_notional_cap=5000),
            EdgeCandidate("ETH", edge=0.08, max_notional_cap=4000),
            EdgeCandidate("SOL", edge=0.06, max_notional_cap=3000),
            EdgeCandidate("XRP", edge=0.04, max_notional_cap=2000),
            EdgeCandidate("DOGE", edge=0.02, max_notional_cap=1000),
        ]
        
        bankroll = 100_000
        cap_pct = 0.02
        
        allocations = select_top3_allocations(bankroll, cap_pct, candidates)
        
        total = sum(a.target_notional for a in allocations)
        max_allowed = int(cap_pct * bankroll)
        
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
    
    def test_get_cycle_risk_cap_pct_returns_valid_value(self):
        """get_cycle_risk_cap_pct should return value in [0.01, 0.02]."""
        allocator = Top3EdgeAllocator()
        pct = allocator.get_cycle_risk_cap_pct()
        
        assert 0.01 <= pct <= 0.02


class TestTop3EnvironmentConfig:
    """Tests for environment variable configuration."""
    
    def test_respects_top3_cycle_risk_cap_env(self, monkeypatch):
        """Should read TOP3_CYCLE_RISK_CAP_PCT from environment."""
        monkeypatch.setenv("TOP3_CYCLE_RISK_CAP_PCT", "0.015")
        
        # Need fresh instance since env is read at init
        from merid.trading.top3_edge_allocator import Top3EdgeAllocator
        allocator = Top3EdgeAllocator()
        
        assert allocator.get_cycle_risk_cap_pct() == 0.015
    
    def test_clamps_env_value_to_valid_range_high(self, monkeypatch):
        """Should clamp env value > 0.02 down to 0.02."""
        monkeypatch.setenv("TOP3_CYCLE_RISK_CAP_PCT", "0.05")
        
        from merid.trading.top3_edge_allocator import Top3EdgeAllocator
        allocator = Top3EdgeAllocator()
        
        assert allocator.get_cycle_risk_cap_pct() == 0.02
    
    def test_clamps_env_value_to_valid_range_low(self, monkeypatch):
        """Should clamp env value < 0.01 up to 0.01."""
        monkeypatch.setenv("TOP3_CYCLE_RISK_CAP_PCT", "0.005")
        
        from merid.trading.top3_edge_allocator import Top3EdgeAllocator
        allocator = Top3EdgeAllocator()
        
        assert allocator.get_cycle_risk_cap_pct() == 0.01
