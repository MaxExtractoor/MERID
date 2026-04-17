"""
Property-Based Tests for Kalshi Trading Invariants
===================================================

Uses Hypothesis to stress-test pure mathematical functions:
1. Fee computation bounds
2. Kelly sizing constraints
3. Bankroll invariant preservation
4. Edge/Kelly relationship

Run with: pytest tests/test_kalshi_properties.py -v
"""

import pytest
from decimal import Decimal
from dataclasses import dataclass
from typing import Tuple

# Import invariant checkers from audit harness
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from audit_kalshi_values import (
    BankrollState,
    FeeParams,
    KellySizing,
)

# Hypothesis imports
hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st, settings, assume
from hypothesis.strategies import decimals


# ═══════════════════════════════════════════════════════════════════════════
# §1 — Fee Schedule Property Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFeeScheduleProperties:
    """Property-based tests for Kalshi fee schedule."""
    
    @settings(max_examples=200, deadline=None)
    @given(
        price_cents=st.integers(min_value=1, max_value=99),
        size=st.integers(min_value=1, max_value=1000)
    )
    def test_fee_bounds(self, price_cents: int, size: int):
        """
        Fee must be within Kalshi bounds:
        - Minimum 1¢ per order
        - Maximum 7¢ per contract (Kalshi cap)
        - Monotonic with size (more contracts = higher fee)
        """
        params = FeeParams(price_cents=price_cents, size_contracts=size)
        fee = params.compute_fee()
        
        # Bound 1: Minimum fee
        assert fee >= 1, f"Fee {fee}¢ below minimum 1¢ for P={price_cents}, size={size}"
        
        # Bound 2: Maximum fee per contract
        max_fee = size * 7
        assert fee <= max_fee, f"Fee {fee}¢ exceeds max {max_fee}¢ for size={size}"
    
    @settings(max_examples=100, deadline=None)
    @given(
        price_cents=st.integers(min_value=1, max_value=99)
    )
    def test_fee_midcurve_maximum(self, price_cents: int):
        """
        Fee is maximized near mid-curve (P=50¢) where P*(1-P) is largest.
        """
        params_low = FeeParams(price_cents=10, size_contracts=10)   # 10¢
        params_mid = FeeParams(price_cents=50, size_contracts=10)     # 50¢
        params_high = FeeParams(price_cents=90, size_contracts=10)    # 90¢
        
        fee_low = params_low.compute_fee()
        fee_mid = params_mid.compute_fee()
        fee_high = params_high.compute_fee()
        
        # Mid-curve should be highest (or equal)
        assert fee_mid >= fee_low, f"Mid-curve fee {fee_mid}¢ < edge fee {fee_low}¢"
        assert fee_mid >= fee_high, f"Mid-curve fee {fee_mid}¢ < edge fee {fee_high}¢"
    
    @settings(max_examples=100, deadline=None)
    @given(
        price_cents=st.integers(min_value=1, max_value=99),
        size1=st.integers(min_value=1, max_value=100),
        size2=st.integers(min_value=1, max_value=100)
    )
    def test_fee_linearity(self, price_cents: int, size1: int, size2: int):
        """
        Fee should be approximately linear in size (sublinear due to per-contract cap).
        """
        params1 = FeeParams(price_cents=price_cents, size_contracts=size1)
        params2 = FeeParams(price_cents=price_cents, size_contracts=size2)
        params_sum = FeeParams(price_cents=price_cents, size_contracts=size1 + size2)
        
        fee1 = params1.compute_fee()
        fee2 = params2.compute_fee()
        fee_sum = params_sum.compute_fee()
        
        # Combined order should cost about the same as separate orders
        # (within rounding tolerance)
        assert abs(fee_sum - (fee1 + fee2)) <= 2, \
            f"Fee non-linearity: {fee_sum} vs {fee1 + fee2} for sizes {size1}, {size2}"
    
    @settings(max_examples=100, deadline=None)
    @given(
        price_cents=st.integers(min_value=1, max_value=99),
        size=st.integers(min_value=1, max_value=100),
        logged_fee=st.integers(min_value=0, max_value=1000)
    )
    def test_fee_check_tolerance(self, price_cents: int, size: int, logged_fee: int):
        """
        Fee check should pass when logged fee matches computed fee.
        """
        params = FeeParams(price_cents=price_cents, size_contracts=size)
        expected = params.compute_fee()
        
        # Exact match should pass
        passed, details = params.check_fee(logged_fee=expected, tolerance_cents=0)
        assert passed, f"Exact fee match should pass"
        assert details["delta_cents"] == 0
        
        # Within tolerance should pass
        passed, _ = params.check_fee(logged_fee=expected + 1, tolerance_cents=2)
        assert passed, f"Fee within tolerance should pass"
        
        # Outside tolerance should fail
        passed, _ = params.check_fee(logged_fee=expected + 10, tolerance_cents=1)
        assert not passed, f"Fee outside tolerance should fail"


# ═══════════════════════════════════════════════════════════════════════════
# §2 — Kelly Sizing Property Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestKellySizingProperties:
    """Property-based tests for Kelly position sizing."""
    
    @settings(max_examples=200, deadline=None)
    @given(
        edge=decimals(min_value="-0.5", max_value="0.5", places=4),
        win_prob=decimals(min_value="0.01", max_value="0.99", places=4),
        payout=decimals(min_value="0.1", max_value="10.0", places=4),
        bankroll=st.integers(min_value=1000, max_value=1000000)
    )
    def test_kelly_bounds(self, edge: Decimal, win_prob: Decimal, payout: Decimal, bankroll: int):
        """
        Kelly sizing must respect key bounds:
        1. Never negative position
        2. Zero when edge <= 0
        3. Never exceeds max_contracts_cap
        4. Kelly fraction always within [-1, 1] for valid inputs
        """
        # Skip impossible combinations
        assume(payout > 0)
        assume(win_prob > 0 and win_prob < 1)
        
        kelly = KellySizing(
            edge=edge,
            win_prob=win_prob,
            payout_ratio=payout,
            kelly_fraction=0.25,
            bankroll_cents=bankroll,
            max_contracts_cap=100
        )
        
        kelly_raw, contracts = kelly.compute_kelly()
        
        # Property 1: Never negative
        assert contracts >= 0, f"Negative contracts {contracts}"
        
        # Property 2: Zero when edge <= 0
        if edge <= 0:
            assert contracts == 0, f"Non-zero contracts {contracts} with edge {edge}"
        
        # Property 3: Never exceeds cap
        assert contracts <= 100, f"Contracts {contracts} exceeds cap 100"
        
        # Property 4: Kelly raw bounded
        assert -1 <= kelly_raw <= 1, f"Kelly raw {kelly_raw} out of [-1, 1]"
    
    @settings(max_examples=100, deadline=None)
    @given(
        win_prob=decimals(min_value="0.3", max_value="0.7", places=4),
        payout=decimals(min_value="1.0", max_value="3.0", places=4)
    )
    def test_kelly_monotonicity(self, win_prob: Decimal, payout: Decimal):
        """
        Kelly sizing should be monotonic in edge (higher edge = more size).
        """
        assume(payout > 0)
        
        kelly_low = KellySizing(
            edge=Decimal("0.01"),
            win_prob=win_prob,
            payout_ratio=payout,
            kelly_fraction=0.25,
            bankroll_cents=10000,
            max_contracts_cap=100
        )
        kelly_high = KellySizing(
            edge=Decimal("0.10"),
            win_prob=win_prob,
            payout_ratio=payout,
            kelly_fraction=0.25,
            bankroll_cents=10000,
            max_contracts_cap=100
        )
        
        _, contracts_low = kelly_low.compute_kelly()
        _, contracts_high = kelly_high.compute_kelly()
        
        assert contracts_high >= contracts_low, \
            f"Kelly not monotonic: {contracts_high} < {contracts_low}"
    
    @settings(max_examples=100, deadline=None)
    @given(
        edge=decimals(min_value="0.01", max_value="0.3", places=4),
        win_prob=decimals(min_value="0.01", max_value="0.99", places=4),
        kelly_frac=st.floats(min_value=0.1, max_value=1.0)
    )
    def test_kelly_fraction_scaling(self, edge: Decimal, win_prob: Decimal, kelly_frac: float):
        """
        Lower Kelly fraction should result in proportionally smaller position.
        """
        assume(edge > 0)
        assume(kelly_frac > 0)
        
        kelly_full = KellySizing(
            edge=edge,
            win_prob=win_prob,
            payout_ratio=Decimal("2.0"),
            kelly_fraction=1.0,
            bankroll_cents=10000,
            max_contracts_cap=1000
        )
        kelly_partial = KellySizing(
            edge=edge,
            win_prob=win_prob,
            payout_ratio=Decimal("2.0"),
            kelly_fraction=kelly_frac,
            bankroll_cents=10000,
            max_contracts_cap=1000
        )
        
        # Position scales with kelly_fraction via kelly_effective; compare contract counts
        _, contracts_full = kelly_full.compute_kelly()
        _, contracts_partial = kelly_partial.compute_kelly()

        # Edge case: with extreme inputs, full Kelly may compute to 0 due to rounding.
        # Skip ratio check in this case - scaling is still technically correct (0 = 0 * kelly_frac).
        assume(contracts_full > 0)

        ratio = contracts_partial / contracts_full
        # Tolerance of 0.20 accounts for integer contract rounding and floor effects
        # in Kelly sizing. With small contract counts (< 10), rounding can cause
        # significant relative deviations (e.g., 1 contract vs 3 expected is 67% difference).
        # The property still holds: partial Kelly produces fewer contracts than full Kelly.
        assert abs(ratio - kelly_frac) < 0.20, \
            f"Kelly fraction scaling off: {ratio} vs {kelly_frac} (contracts: {contracts_partial}/{contracts_full})"


# ═══════════════════════════════════════════════════════════════════════════
# §3 — Bankroll Invariant Property Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestBankrollInvariantProperties:
    """Property-based tests for bankroll accounting invariant."""
    
    @settings(max_examples=300, deadline=None)
    @given(
        cash=st.integers(min_value=0, max_value=100000),
        exposure=st.integers(min_value=0, max_value=50000),
        pnl=st.integers(min_value=-50000, max_value=50000)
    )
    def test_invariant_holds_for_valid_state(self, cash: int, exposure: int, pnl: int):
        """
        Invariant cash + pnl = bankroll - exposure must hold for internally consistent state.
        """
        # Construct bankroll from the invariant equation
        bankroll = cash + pnl + exposure
        
        state = BankrollState(
            cash_cents=cash,
            exposure_cents=exposure,
            realized_pnl_cents=pnl,
            bankroll_cents=bankroll
        )
        
        passed, delta = state.check_invariant(tolerance_cents=0)
        
        assert passed, f"Invariant failed for valid state: delta={delta}¢"
        assert delta == 0, f"Non-zero delta for valid state: {delta}"
    
    @settings(max_examples=200, deadline=None)
    @given(
        cash=st.integers(min_value=0, max_value=100000),
        exposure=st.integers(min_value=0, max_value=50000),
        pnl=st.integers(min_value=-50000, max_value=50000),
        noise=st.integers(min_value=1, max_value=1000)
    )
    def test_invariant_fails_with_noise(self, cash: int, exposure: int, pnl: int, noise: int):
        """
        Invariant must detect inconsistencies (noise injection).
        """
        # Construct inconsistent bankroll by adding noise
        bankroll = cash + pnl + exposure + noise
        
        state = BankrollState(
            cash_cents=cash,
            exposure_cents=exposure,
            realized_pnl_cents=pnl,
            bankroll_cents=bankroll
        )
        
        # Cents-only tolerance: default % band would absorb small noise on large bankrolls
        passed, delta = state.check_invariant(
            tolerance_cents=max(0, noise - 1),
            tolerance_pct=0.0,
        )
        
        # Should fail with tolerance smaller than noise
        assert not passed, f"Invariant should fail with {noise}¢ noise"
        assert delta == noise, f"Delta should equal noise: {delta} vs {noise}"
    
    @settings(max_examples=100, deadline=None)
    @given(
        cash1=st.integers(min_value=0, max_value=50000),
        exposure1=st.integers(min_value=0, max_value=25000),
        pnl1=st.integers(min_value=-25000, max_value=25000),
        delta_cash=st.integers(min_value=-10000, max_value=10000),
        delta_exposure=st.integers(min_value=-10000, max_value=10000),
    )
    def test_invariant_preserved_across_transitions(
        self, cash1: int, exposure1: int, pnl1: int,
        delta_cash: int, delta_exposure: int
    ):
        """
        State transitions (trades, settlements) should preserve invariant.
        """
        # Initial state
        bankroll1 = cash1 + pnl1 + exposure1
        state1 = BankrollState(
            cash_cents=cash1,
            exposure_cents=exposure1,
            realized_pnl_cents=pnl1,
            bankroll_cents=bankroll1
        )
        
        # Verify initial
        passed, _ = state1.check_invariant(tolerance_cents=0)
        assert passed, "Initial state should satisfy invariant"
        
        # Simulate trade: cash decreases, exposure increases by same amount
        cash2 = max(0, cash1 + delta_cash)
        exposure2 = max(0, exposure1 + delta_exposure)
        pnl2 = pnl1  # No realized PnL yet
        bankroll2 = cash2 + pnl2 + exposure2
        
        state2 = BankrollState(
            cash_cents=cash2,
            exposure_cents=exposure2,
            realized_pnl_cents=pnl2,
            bankroll_cents=bankroll2
        )
        
        # After valid transition, invariant still holds
        passed, _ = state2.check_invariant(tolerance_cents=0)
        assert passed, f"Invariant failed after transition: cash {cash1}->{cash2}, exp {exposure1}->{exposure2}"


# ═══════════════════════════════════════════════════════════════════════════
# §4 — Edge-Probability Relationship Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeProbabilityProperties:
    """Property-based tests for edge computation relationships."""
    
    @settings(max_examples=200, deadline=None)
    @given(
        model_prob=decimals(min_value="0.01", max_value="0.99", places=4),
        implied_prob=decimals(min_value="0.01", max_value="0.99", places=4)
    )
    def test_edge_definition(self, model_prob: Decimal, implied_prob: Decimal):
        """
        Edge = model_prob - implied_prob (ignoring fees/slippage for now).
        Positive edge means model > market.
        """
        edge = model_prob - implied_prob
        
        # Positive model > implied
        if model_prob > implied_prob:
            assert edge > 0, f"Positive edge expected when {model_prob} > {implied_prob}"
        
        # Negative model < implied
        if model_prob < implied_prob:
            assert edge < 0, f"Negative edge expected when {model_prob} < {implied_prob}"
        
        # Zero at equality
        if model_prob == implied_prob:
            assert edge == 0, f"Zero edge expected at equality"
    
    @settings(max_examples=100, deadline=None)
    @given(
        price_cents=st.integers(min_value=1, max_value=99)
    )
    def test_implied_probability_from_price(self, price_cents: int):
        """
        Implied probability from Kalshi price should be price/100.
        """
        implied = Decimal(price_cents) / Decimal("100")
        
        # Sanity checks
        assert 0 < implied < 1, f"Implied {implied} out of (0,1)"
        
        # At 50¢, implied = 50%
        if price_cents == 50:
            assert implied == Decimal("0.5"), f"50¢ should imply 50%"
    
    @settings(max_examples=100, deadline=None)
    @given(
        win_prob=decimals(min_value="0.51", max_value="0.99", places=4),
        price_cents=st.integers(min_value=1, max_value=49)  # Below 50¢ = underpriced
    )
    def test_positive_edge_opportunity(self, win_prob: Decimal, price_cents: int):
        """
        When model says >50% but price <50¢, edge is strongly positive.
        """
        implied = Decimal(price_cents) / Decimal("100")
        edge = win_prob - implied
        
        assert edge > Decimal("0.01"), f"Strong positive edge expected: {edge}"


# ═══════════════════════════════════════════════════════════════════════════
# §5 — Integration Smoke Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestIntegrationSmoke:
    """Smoke tests for integration of multiple components."""
    
    def test_full_cycle_consistency(self):
        """
        Simulate a full trade cycle and verify all invariants hold.
        """
        # Initial state
        cash = 10000  # $100
        exposure = 0
        pnl = 0
        bankroll = cash + pnl + exposure
        
        state = BankrollState(
            cash_cents=cash,
            exposure_cents=exposure,
            realized_pnl_cents=pnl,
            bankroll_cents=bankroll
        )
        
        # Verify initial
        passed, _ = state.check_invariant()
        assert passed
        
        # Simulate trade: buy 10 contracts at 30¢
        price_cents = 30
        size = 10
        cost = price_cents * size  # 300¢
        
        # Compute expected fee
        fee_params = FeeParams(price_cents=price_cents, size_contracts=size)
        fee = fee_params.compute_fee()
        
        # Verify fee bounds
        assert 1 <= fee <= size * 7
        
        # Update state
        cash2 = cash - cost - fee
        exposure2 = cost
        pnl2 = pnl
        bankroll2 = cash2 + pnl2 + exposure2
        
        # Verify trade preserves bankroll (excluding fees)
        assert bankroll2 == bankroll - fee, "Bankroll should decrease by fee only"
        
        # Check invariant
        state2 = BankrollState(
            cash_cents=cash2,
            exposure_cents=exposure2,
            realized_pnl_cents=pnl2,
            bankroll_cents=bankroll2
        )
        passed, delta = state2.check_invariant()
        assert passed, f"Invariant failed after trade: delta={delta}"
    
    def test_kelly_with_fee_adjustment(self):
        """
        Kelly sizing should account for fees in edge calculation.
        """
        # Model says 60% win, market says 50%
        model_prob = Decimal("0.60")
        implied = Decimal("0.50")
        
        # Gross edge
        gross_edge = model_prob - implied  # 0.10
        
        # Fee adjustment for mid-curve (approx 7% of notional)
        fee_pct = Decimal("0.07") * Decimal("0.25")  # ~1.75% effective at 50¢
        net_edge = gross_edge - fee_pct
        
        # Kelly sizing
        kelly = KellySizing(
            edge=net_edge,
            win_prob=model_prob,
            payout_ratio=Decimal("2.0"),  # 50¢ -> $1
            kelly_fraction=0.25,
            bankroll_cents=10000,
            max_contracts_cap=50
        )
        
        kelly_raw, contracts = kelly.compute_kelly()
        
        # Should have positive position
        assert contracts > 0, "Should have positive Kelly position"
        assert kelly_raw > 0, "Should have positive Kelly fraction"
        
        # Should be bounded
        assert contracts <= 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
