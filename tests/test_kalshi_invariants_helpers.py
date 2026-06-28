"""
Static sanity tests for Kalshi invariants helper functions.

These tests validate the core helper functions with artificial scenarios
to ensure they behave as expected across edge cases.
"""

import pytest
from datetime import datetime, timedelta
from merid.event_venues.kalshi.invariants import (
    is_within_entry_window,
    is_within_entry_window_by_minutes,
    get_effective_edge_threshold,
    compute_max_notional,
    compute_contracts,
    is_trade_valid,
    clamp_probability,
)


class TestTimeWindowHelpers:
    """Test time window validation helpers."""

    def test_is_within_entry_window_valid(self):
        """Test valid entry window (within bounds)."""
        now = datetime.utcnow()
        expiry = now + timedelta(minutes=15)
        assert is_within_entry_window(now, expiry, 30, 2) is True

    def test_is_within_entry_window_too_far(self):
        """Test market too far from expiry (above upper bound)."""
        now = datetime.utcnow()
        expiry = now + timedelta(minutes=45)
        assert is_within_entry_window(now, expiry, 30, 2) is False

    def test_is_within_entry_window_too_close(self):
        """Test market too close to expiry (below lower bound)."""
        now = datetime.utcnow()
        expiry = now + timedelta(minutes=1)
        assert is_within_entry_window(now, expiry, 30, 2) is False

    def test_is_within_entry_window_expired(self):
        """Test expired market (expiry in past)."""
        now = datetime.utcnow()
        expiry = now - timedelta(minutes=5)
        assert is_within_entry_window(now, expiry, 30, 2) is False

    def test_is_within_entry_window_by_minutes_valid(self):
        """Test minutes-based helper with valid TTE."""
        assert is_within_entry_window_by_minutes(15, 30, 2) is True

    def test_is_within_entry_window_by_minutes_too_far(self):
        """Test minutes-based helper with TTE above upper bound."""
        assert is_within_entry_window_by_minutes(45, 30, 2) is False

    def test_is_within_entry_window_by_minutes_too_close(self):
        """Test minutes-based helper with TTE below lower bound."""
        assert is_within_entry_window_by_minutes(1, 30, 2) is False

    def test_is_within_entry_window_by_minutes_boundary_lower(self):
        """Test lower boundary (inclusive)."""
        assert is_within_entry_window_by_minutes(2, 30, 2) is True

    def test_is_within_entry_window_by_minutes_boundary_upper(self):
        """Test upper boundary (inclusive)."""
        assert is_within_entry_window_by_minutes(30, 30, 2) is True


class TestEdgeThresholdHelper:
    """Test edge threshold calculation helper."""

    class MockMarketState:
        def __init__(self, spread_cents):
            self.spread_cents = spread_cents

    class MockProfileConfig:
        def __init__(self, min_edge_pct):
            self.min_edge_pct = min_edge_pct

    def test_edge_threshold_base_only(self):
        """Test edge threshold with no spread (uses base)."""
        state = self.MockMarketState(spread_cents=0)
        config = self.MockProfileConfig(min_edge_pct=0.02)
        assert get_effective_edge_threshold(state, config) == 0.02

    def test_edge_threshold_spread_dominates(self):
        """Test edge threshold when 2x spread > base edge."""
        state = self.MockMarketState(spread_cents=3)  # 3% spread
        config = self.MockProfileConfig(min_edge_pct=0.02)
        # 2x spread = 6% > base 2%, so use 6%
        assert get_effective_edge_threshold(state, config) == 0.06

    def test_edge_threshold_base_dominates(self):
        """Test edge threshold when base edge > 2x spread."""
        state = self.MockMarketState(spread_cents=1)  # 1% spread
        config = self.MockProfileConfig(min_edge_pct=0.05)
        # 2x spread = 2% < base 5%, so use 5%
        assert get_effective_edge_threshold(state, config) == 0.05

    def test_edge_threshold_none_state(self):
        """Test edge threshold with None market state (uses base)."""
        config = self.MockProfileConfig(min_edge_pct=0.03)
        assert get_effective_edge_threshold(None, config) == 0.03

    def test_edge_threshold_tight_spread(self):
        """Test edge threshold with very tight spread (1 cent)."""
        state = self.MockMarketState(spread_cents=1)  # 1% spread
        config = self.MockProfileConfig(min_edge_pct=0.02)
        # 2x spread = 2% == base 2%, so use 2%
        assert get_effective_edge_threshold(state, config) == 0.02


class TestSizingHelpers:
    """Test sizing calculation helpers."""

    def test_compute_max_notional_normal(self):
        """Test max notional calculation (normal case, no floor)."""
        max_notional, floor_applied = compute_max_notional(1000.0, 0.02, 0.35)
        assert max_notional == 20.0  # 2% of 1000
        assert floor_applied is False

    def test_compute_max_notional_floor_applied(self):
        """Test max notional calculation (floor applied)."""
        max_notional, floor_applied = compute_max_notional(10.0, 0.02, 0.35)
        # 2% of 10 = 0.20, below floor 0.35, so use floor
        assert max_notional == 0.35
        assert floor_applied is True

    def test_compute_max_notional_large_bankroll(self):
        """Test max notional with large bankroll."""
        max_notional, floor_applied = compute_max_notional(100000.0, 0.02, 0.35)
        assert max_notional == 2000.0  # 2% of 100k
        assert floor_applied is False

    def test_compute_contracts_normal(self):
        """Test contracts calculation (normal case)."""
        contracts, override_applied = compute_contracts(20.0, 0.50, 0.5)
        assert contracts == 40  # 20 / 0.50 = 40
        assert override_applied is False

    def test_compute_contracts_below_threshold(self):
        """Test contracts calculation (below override threshold)."""
        contracts, override_applied = compute_contracts(0.20, 0.50, 0.5)
        # 0.20 / 0.50 = 0.4, below threshold 0.5, no override
        assert contracts == 0
        assert override_applied is False

    def test_compute_contracts_override_applied(self):
        """Test contracts calculation (override applied)."""
        contracts, override_applied = compute_contracts(0.30, 0.50, 0.5)
        # 0.30 / 0.50 = 0.6, above threshold 0.5, override to 1
        assert contracts == 1
        assert override_applied is True

    def test_compute_contracts_zero_price(self):
        """Test contracts calculation with zero price (safety)."""
        contracts, override_applied = compute_contracts(20.0, 0.0, 0.5)
        assert contracts == 0
        assert override_applied is False

    def test_compute_contracts_negative_price(self):
        """Test contracts calculation with negative price (safety)."""
        contracts, override_applied = compute_contracts(20.0, -0.50, 0.5)
        assert contracts == 0
        assert override_applied is False

    def test_is_trade_valid_within_limit(self):
        """Test trade validation (within risk limit)."""
        assert is_trade_valid(1000.0, 20.0, 0.02) is True  # 2% of 1000 = 20

    def test_is_trade_valid_at_limit(self):
        """Test trade validation (at risk limit)."""
        assert is_trade_valid(1000.0, 20.0, 0.02) is True  # Exactly at limit

    def test_is_trade_valid_exceeds_limit(self):
        """Test trade validation (exceeds risk limit)."""
        assert is_trade_valid(1000.0, 25.0, 0.02) is False  # 2.5% > 2%

    def test_is_trade_valid_zero_bankroll(self):
        """Test trade validation with zero bankroll (safety)."""
        assert is_trade_valid(0.0, 20.0, 0.02) is False

    def test_is_trade_valid_negative_bankroll(self):
        """Test trade validation with negative bankroll (safety)."""
        assert is_trade_valid(-100.0, 20.0, 0.02) is False

    def test_is_trade_valid_epsilon_tolerance(self):
        """Test trade validation with epsilon tolerance for floating point."""
        # 20.00001 / 1000 = 0.02000001, should pass with epsilon
        assert is_trade_valid(1000.0, 20.00001, 0.02) is True


class TestSizingInvariants:
    """Additional invariant checks for sizing helpers (safety guarantees)."""

    def test_compute_max_notional_never_negative(self):
        """Invariant: compute_max_notional should never return negative."""
        # Test with various inputs including edge cases
        test_cases = [
            (1000.0, 0.02, 0.35),
            (10.0, 0.02, 0.35),
            (0.0, 0.02, 0.35),
            (100.0, -0.01, 0.35),  # Negative risk (edge case)
            (100.0, 0.02, -0.10),  # Negative floor (edge case)
        ]
        for bankroll, risk_pct, min_floor in test_cases:
            max_notional, _ = compute_max_notional(bankroll, risk_pct, min_floor)
            assert max_notional >= 0, f"compute_max_notional returned negative: {max_notional} for bankroll={bankroll}, risk_pct={risk_pct}, min_floor={min_floor}"

    def test_compute_contracts_never_negative(self):
        """Invariant: compute_contracts should never return negative contracts."""
        test_cases = [
            (20.0, 0.50, 0.5),
            (0.35, 0.50, 0.5),
            (0.0, 0.50, 0.5),
            (-10.0, 0.50, 0.5),  # Negative notional (edge case)
            (20.0, -0.50, 0.5),  # Negative price (edge case)
        ]
        for max_notional, price, threshold in test_cases:
            contracts, _ = compute_contracts(max_notional, price, threshold)
            assert contracts >= 0, f"compute_contracts returned negative: {contracts} for max_notional={max_notional}, price={price}, threshold={threshold}"

    def test_compute_contracts_zero_implies_no_override(self):
        """Invariant: if contracts == 0, then override_applied must be False."""
        # When contracts is 0, override should never be True (can't override to 0)
        test_cases = [
            (0.20, 0.50, 0.5),  # Below threshold
            (0.0, 0.50, 0.5),   # Zero notional
            (0.10, 0.50, 0.5),  # Very small notional
        ]
        for max_notional, price, threshold in test_cases:
            contracts, override_applied = compute_contracts(max_notional, price, threshold)
            if contracts == 0:
                assert override_applied is False, f"contracts=0 but override_applied=True for max_notional={max_notional}, price={price}, threshold={threshold}"

    def test_is_trade_valid_implies_risk_bound(self):
        """Invariant: if is_trade_valid returns True, effective_risk_pct <= max_risk_pct * (1 + epsilon)."""
        test_cases = [
            (1000.0, 20.0, 0.02),    # At limit
            (1000.0, 19.0, 0.02),    # Below limit
            (1000.0, 20.00001, 0.02), # Slightly above with epsilon
        ]
        epsilon = 1e-6
        for bankroll, notional, max_risk in test_cases:
            is_valid = is_trade_valid(bankroll, notional, max_risk)
            if is_valid:
                effective_risk = notional / bankroll if bankroll > 0 else 0
                assert effective_risk <= max_risk * (1 + epsilon), f"is_trade_valid=True but effective_risk={effective_risk} > max_risk={max_risk} * (1+epsilon)"


class TestProbabilityClamp:
    """Test probability clamping (existing invariant)."""

    def test_clamp_probability_within_range(self):
        """Test probability within valid range."""
        assert clamp_probability(0.50) == 0.50

    def test_clamp_probability_below_min(self):
        """Test probability below minimum (0.05)."""
        assert clamp_probability(0.01) == 0.05

    def test_clamp_probability_above_max(self):
        """Test probability above maximum (0.95)."""
        assert clamp_probability(0.99) == 0.95

    def test_clamp_probability_at_min(self):
        """Test probability at minimum boundary."""
        assert clamp_probability(0.05) == 0.05

    def test_clamp_probability_at_max(self):
        """Test probability at maximum boundary."""
        assert clamp_probability(0.95) == 0.95

    def test_clamp_probability_zero(self):
        """Test probability of zero (clamped to min)."""
        assert clamp_probability(0.0) == 0.05

    def test_clamp_probability_one(self):
        """Test probability of one (clamped to max)."""
        assert clamp_probability(1.0) == 0.95


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
