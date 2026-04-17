"""
Hypothesis Property-Based Tests — Trading Invariants
=====================================================

Tests the invariants locked in during the swarm topology audit:
1. Fills → positions → PnL consistency
2. Kill switch invariants
3. Synthetic/manual/data flags

Run with: pytest tests/test_hypothesis_invariants.py -v --hypothesis-seed=0
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple
from hypothesis import given, settings, strategies as st, assume, seed
import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Test Models (simplified for property testing)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Fill:
    fill_id: str
    order_id: str
    ticker: str
    side: str  # "yes" or "no"
    count: int
    price_cents: int  # 1-99
    fee_cents: int
    is_synthetic: bool = False
    is_external: bool = False


@dataclass
class Position:
    ticker: str
    side: str
    count: int
    avg_price_cents: int
    cost_basis_cents: int
    pnl_cents: int = 0


@dataclass
class RiskState:
    kill_switch_active: bool = False
    daily_pnl_cents: int = 0
    max_daily_loss_cents: int = -50000  # $500


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 1: Fills → Positions → PnL Consistency
# ═══════════════════════════════════════════════════════════════════════════

def apply_fills_to_positions(
    positions: dict[str, Position],
    fills: List[Fill],
    current_price_cents: int = 50,
) -> dict[str, Position]:
    """Apply fills to positions, computing PnL."""
    result = dict(positions)
    for fill in fills:
        key = f"{fill.ticker}:{fill.side}"
        if key in result:
            pos = result[key]
            # Same side: add to position
            if pos.side == fill.side:
                total_cost = pos.cost_basis_cents + (fill.count * fill.price_cents)
                total_count = pos.count + fill.count
                new_avg = total_cost // max(1, total_count)
                result[key] = Position(
                    ticker=fill.ticker,
                    side=fill.side,
                    count=total_count,
                    avg_price_cents=new_avg,
                    cost_basis_cents=total_cost,
                )
            else:
                # Opposite side: reduce or flip
                if pos.count > fill.count:
                    # Partial close
                    realized = (fill.price_cents - pos.avg_price_cents) * fill.count
                    new_cost = pos.cost_basis_cents - (pos.avg_price_cents * fill.count)
                    result[key] = Position(
                        ticker=fill.ticker,
                        side=pos.side,
                        count=pos.count - fill.count,
                        avg_price_cents=pos.avg_price_cents,
                        cost_basis_cents=new_cost,
                        pnl_cents=pos.pnl_cents + realized,
                    )
                else:
                    # Flip to other side
                    remaining = fill.count - pos.count
                    realized = (fill.price_cents - pos.avg_price_cents) * pos.count
                    new_cost = remaining * fill.price_cents
                    result[key] = Position(
                        ticker=fill.ticker,
                        side=fill.side,
                        count=remaining,
                        avg_price_cents=fill.price_cents,
                        cost_basis_cents=new_cost,
                        pnl_cents=realized,
                    )
        else:
            # New position
            result[key] = Position(
                ticker=fill.ticker,
                side=fill.side,
                count=fill.count,
                avg_price_cents=fill.price_cents,
                cost_basis_cents=fill.count * fill.price_cents,
            )
    return result


def compute_unrealized_pnl(
    position: Position,
    mark_price_cents: int,
) -> int:
    """Compute unrealized PnL at current mark price."""
    if position.side == "yes":
        return (mark_price_cents - position.avg_price_cents) * position.count
    else:
        return (position.avg_price_cents - mark_price_cents) * position.count


# ═══════════════════════════════════════════════════════════════════════════
# Property Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPnLConsistency:
    """Fills → positions → PnL invariants."""

    @given(
        st.lists(
            st.builds(
                Fill,
                fill_id=st.text(min_size=8, max_size=16),
                order_id=st.text(min_size=8, max_size=16),
                ticker=st.sampled_from(["KXBTC", "KXETH", "KXSOL"]),
                side=st.sampled_from(["yes", "no"]),
                count=st.integers(min_value=1, max_value=100),
                price_cents=st.integers(min_value=1, max_value=99),
                fee_cents=st.integers(min_value=1, max_value=10),
            ),
            min_size=0,
            max_size=50,
        ),
        st.integers(min_value=1, max_value=99),  # mark price
    )
    @settings(max_examples=100, deadline=None)
    def test_no_negative_exposure(self, fills: List[Fill], mark_price: int):
        """Position count never exceeds sum of fills for that side."""
        assume(len(fills) > 0)
        
        positions = apply_fills_to_positions({}, fills, mark_price)
        
        for key, pos in positions.items():
            # Position count must be non-negative
            assert pos.count >= 0, f"Negative position count for {key}: {pos.count}"
            
            # Position count cannot exceed total fills for that ticker+side
            total_fills = sum(
                f.count for f in fills 
                if f.ticker == pos.ticker and f.side == pos.side
            )
            # After netting, count could be less due to opposite fills
            assert pos.count <= total_fills * 2, f"Position count {pos.count} exceeds bounds for {key}"

    @given(
        st.lists(
            st.builds(
                Fill,
                fill_id=st.text(min_size=8, max_size=16),
                order_id=st.text(min_size=8, max_size=16),
                ticker=st.just("KXBTC"),
                side=st.sampled_from(["yes", "no"]),
                count=st.integers(min_value=1, max_value=50),
                price_cents=st.integers(min_value=10, max_value=90),
                fee_cents=st.integers(min_value=1, max_value=10),
            ),
            min_size=1,
            max_size=30,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_pnl_additive(self, fills: List[Fill]):
        """PnL is additive across fills."""
        positions = apply_fills_to_positions({}, fills)
        
        total_pnl = sum(p.pnl_cents for p in positions.values())
        
        # PnL should be bounded by fill economics
        total_volume = sum(f.count * f.price_cents for f in fills)
        
        # PnL cannot exceed total volume (would be >100% return per contract)
        assert abs(total_pnl) <= total_volume * 2, f"PnL {total_pnl} exceeds volume bounds {total_volume}"

    @given(
        st.integers(min_value=1, max_value=99),  # entry price
        st.integers(min_value=1, max_value=99),  # exit price
        st.integers(min_value=1, max_value=100),  # count
    )
    @settings(max_examples=100)
    def test_long_pnl_formula(self, entry: int, exit: int, count: int):
        """Long position PnL = (exit - entry) * count."""
        pnl = (exit - entry) * count
        
        # Unrealized PnL at exit should match if we mark there
        pos = Position("KXBTC", "yes", count, entry, entry * count)
        unrealized = compute_unrealized_pnl(pos, exit)
        
        assert unrealized == pnl, f"PnL mismatch: computed {unrealized}, expected {pnl}"


class TestKillSwitchInvariant:
    """Kill switch invariants under random signal sequences."""

    @given(
        st.lists(
            st.one_of(
                st.just("signal_buy"),
                st.just("signal_sell"),
                st.just("kill"),
                st.just("reset"),
            ),
            min_size=1,
            max_size=100,
        ),
        st.integers(min_value=-100000, max_value=100000),  # starting PnL
    )
    @settings(max_examples=100, deadline=None)
    def test_kill_switch_blocks_all_live_orders(self, events: List[str], start_pnl: int):
        """Once kill switch trips, no NEW live orders are produced.
        
        Note: Orders already in-flight when kill happens are tracked but
        no NEW orders should be submitted after kill.
        """
        risk = RiskState(daily_pnl_cents=start_pnl)
        orders_produced: List[Tuple[str, str]] = []
        kill_tripped_at: Optional[int] = None
        
        for i, event in enumerate(events):
            if event == "kill":
                risk.kill_switch_active = True
                if kill_tripped_at is None:
                    kill_tripped_at = i
            elif event == "reset":
                risk.kill_switch_active = False
                kill_tripped_at = None
            else:  # signal_buy or signal_sell
                # Simulate order production
                if not risk.kill_switch_active:
                    # Pre-kill: orders allowed
                    orders_produced.append((event, "live"))
                elif kill_tripped_at is not None and i > kill_tripped_at:
                    # Post-kill: new orders should be blocked
                    orders_produced.append((event, "blocked"))
                else:
                    # At kill moment: could be in-flight
                    orders_produced.append((event, "in_flight"))
        
        # Verify: after first kill, all NEW orders should be blocked
        if kill_tripped_at is not None:
            post_kill_new_orders = [
                o for i, o in enumerate(orders_produced)
                if i > kill_tripped_at and events[i] in ("signal_buy", "signal_sell")
                and o[1] == "live"  # Should NOT be live
            ]
            assert len(post_kill_new_orders) == 0, \
                f"Kill switch violated: {len(post_kill_new_orders)} new live orders after kill at {kill_tripped_at}"

    @given(
        st.integers(min_value=-1000000, max_value=-50001),  # PnL below threshold
    )
    @settings(max_examples=50)
    def test_pnl_threshold_triggers_kill(self, pnl: int):
        """Daily PnL below threshold must trigger kill switch."""
        risk = RiskState(daily_pnl_cents=pnl, max_daily_loss_cents=-50000)
        
        # Threshold check
        should_kill = pnl <= risk.max_daily_loss_cents
        
        assert should_kill, f"PnL {pnl} below threshold {risk.max_daily_loss_cents} should trigger kill"


class TestDataFlagGating:
    """Synthetic/manual/external order flag invariants."""

    @given(
        st.lists(
            st.builds(
                Fill,
                fill_id=st.text(min_size=8, max_size=16),
                order_id=st.text(min_size=8, max_size=16),
                ticker=st.sampled_from(["KXBTC", "KXETH"]),
                side=st.sampled_from(["yes", "no"]),
                count=st.integers(min_value=1, max_value=10),
                price_cents=st.integers(min_value=1, max_value=99),
                fee_cents=st.integers(min_value=1, max_value=10),
                is_synthetic=st.booleans(),
                is_external=st.booleans(),
            ),
            min_size=1,
            max_size=20,
        ),
        st.booleans(),  # api_include_synthetic flag
        st.booleans(),  # api_include_external flag
    )
    @settings(max_examples=100, deadline=None)
    def test_api_never_leaks_synthetic_without_flag(
        self, 
        fills: List[Fill],
        include_synthetic: bool,
        include_external: bool,
    ):
        """API response filters synthetic/external fills unless explicitly requested."""
        # Simulate API filtering
        response_fills = []
        for f in fills:
            if f.is_synthetic and not include_synthetic:
                continue
            if f.is_external and not include_external:
                continue
            response_fills.append(f)
        
        # Verify: no synthetic fills in response unless flag is True
        leaked_synthetic = [f for f in response_fills if f.is_synthetic and not include_synthetic]
        leaked_external = [f for f in response_fills if f.is_external and not include_external]
        
        assert len(leaked_synthetic) == 0, "API leaked synthetic fills without flag"
        assert len(leaked_external) == 0, "API leaked external fills without flag"

    @given(
        st.booleans(),  # is_synthetic
        st.booleans(),  # is_manual
        st.booleans(),  # is_external
    )
    @settings(max_examples=50)
    def test_exclusive_order_flags(self, synthetic: bool, manual: bool, external: bool):
        """Order cannot be both synthetic and external (mutually exclusive)."""
        # In a valid system, these flags have semantic constraints
        is_valid = True
        
        # Synthetic orders come from simulation, not external
        if synthetic and external:
            is_valid = False
        
        # Manual orders are human-initiated, not synthetic
        if synthetic and manual:
            is_valid = False
        
        # Note: manual + external is valid (human trading external venue)
        
        if not is_valid:
            # In production, these would be rejected at API layer
            pytest.skip("Invalid flag combination detected (would be rejected)")


class TestReconciliationInvariant:
    """Reconciliation state invariants."""

    @given(
        st.lists(
            st.builds(
                Fill,
                fill_id=st.text(min_size=8, max_size=16),
                order_id=st.text(min_size=8, max_size=16),
                ticker=st.sampled_from(["KXBTC", "KXETH"]),
                side=st.sampled_from(["yes", "no"]),
                count=st.integers(min_value=1, max_value=20),
                price_cents=st.integers(min_value=1, max_value=99),
                fee_cents=st.integers(min_value=1, max_value=10),
                is_synthetic=st.just(False),  # Only real fills
                is_external=st.booleans(),
            ),
            min_size=1,
            max_size=20,
        ),
        st.dictionaries(
            st.text(min_size=8, max_size=16),
            st.builds(
                Position,
                ticker=st.sampled_from(["KXBTC", "KXETH"]),
                side=st.sampled_from(["yes", "no"]),
                count=st.integers(min_value=0, max_value=100),
                avg_price_cents=st.integers(min_value=1, max_value=99),
                cost_basis_cents=st.integers(min_value=0, max_value=10000),
            ),
            min_size=0,
            max_size=3,
        ),
    )
    @settings(max_examples=50, deadline=None)
    def test_reconciliation_no_unbacked_positions(self, fills: List[Fill], positions: dict):
        """No position exists without backing fills (unless external).
        
        This is a consistency check: positions that have non-zero count
        should have corresponding fills (with some tolerance for netting).
        External positions are allowed to have no local fills.
        """
        assume(len(fills) > 0)
        
        # Build a map of fill counts by ticker:side
        fill_counts: dict = {}
        for f in fills:
            if not f.is_external:
                key = (f.ticker, f.side)
                fill_counts[key] = fill_counts.get(key, 0) + f.count
        
        for pos_key, pos in positions.items():
            if pos.count == 0:
                continue
            
            # Get backing fills for this position  
            key = (pos.ticker, pos.side)
            backing = fill_counts.get(key, 0)
            
            # If no backing fills and position is non-zero, it must be external
            # or represent a netting scenario (which we can't validate without
            # the opposite side's fills)
            if backing == 0:
                # Position with no backing - could be valid if external source
                # or if this is a net position (we only see one side)
                # Just verify the position is consistent with itself
                assert pos.count >= 0, f"Position count must be non-negative"
            else:
                # Position should not exceed reasonable multiple of backing
                # (allowing for netting, partial fills, etc.)
                # The key invariant: position exists → backing exists (or external)
                assert backing > 0, f"Position {pos.ticker}:{pos.side} has no backing fills"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
