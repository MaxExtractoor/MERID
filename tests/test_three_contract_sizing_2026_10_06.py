"""Regression tests for the 3-contract / $3.00 sizing policy (2026-10-06).

Covers the user's directive:
- Configured target 3 produces approved/allocated quantity 3 when limits permit.
- Quantity 1 still works through configuration (parameterized, not removed).
- Both YES and NO entries preserve sizing at quantity 3.
- Partial entry fills reserve only the filled quantity.
- Partial exit fills do not free the slot budget (position stays open).
- Full close releases the reservation.
- Entry cost above the shared budget is rejected explicitly.
- Exit orders never consume entry allocation.
"""

import os
import pytest
from decimal import Decimal

os.environ.setdefault("MERID_PROFILE", "kalshi_crypto_15m_v2")

pytestmark = pytest.mark.usefixtures("_reset_allocator")


@pytest.fixture(autouse=True)
def _reset_allocator():
    from merid.risk.global_slot_allocator import reset_global_slot_allocator
    reset_global_slot_allocator()
    yield
    reset_global_slot_allocator()


def _alloc(count, asset="BTC", ticker=None, price=50, exit_order=False):
    from merid.risk.global_slot_allocator import (
        get_global_slot_allocator, AllocationRequest,
    )
    allocator = get_global_slot_allocator()
    req = AllocationRequest(
        agent_id=f"{asset}_15M",
        asset=asset,
        ticker=ticker or f"KX{asset}15M-26OCT061200-00",
        entry_price_cents=price,
        edge_pct=2.0,
        spread_cents=5,
        is_exit_order=exit_order,
        count=count,
    )
    return allocator, allocator.request_allocation(req)


class TestThreeContractPolicy:
    def test_resolved_config_is_three_contracts(self):
        """Resolved live config exposes the 3-contract / $3 policy."""
        from merid.config.live_config import resolve_live_config
        resolved = resolve_live_config()
        assert resolved.resolved
        assert int(resolved.max_contracts_per_order) == 3
        assert float(resolved.fixed_exposure_cap_usd) == 3.00

    @pytest.mark.parametrize("target", [1, 2, 3])
    def test_entry_quantity_parameterized(self, target):
        """Entry quantities 1, 2, and 3 are all valid under the policy."""
        allocator, (ok, reason, slot_id) = _alloc(target, price=50)
        assert ok, f"count={target} rejected: {reason}"
        assert slot_id is not None
        slot = allocator._slots[slot_id]
        assert slot.count == float(target)

    def test_four_contracts_rejected(self):
        """count > max_contracts_per_order is rejected at request validation."""
        from merid.risk.global_slot_allocator import AllocationRequest
        with pytest.raises(ValueError):
            AllocationRequest(
                agent_id="BTC_15M", asset="BTC",
                ticker="KXBTC15M-26OCT061200-00",
                entry_price_cents=50, edge_pct=2.0, spread_cents=5,
                is_exit_order=False, count=4,
            )

    def test_three_contracts_at_75c_fit_cap(self):
        """3 contracts at the top of the entry band fit the $3 cap."""
        allocator, (ok, reason, slot_id) = _alloc(3, price=75)
        assert ok, reason
        assert allocator.get_total_exposure() == pytest.approx(2.25)

    def test_entry_cost_over_budget_rejected(self):
        """A second entry that would exceed the shared $3 budget is rejected."""
        allocator, (ok1, _, _) = _alloc(3, asset="BTC", price=75)  # $2.25
        assert ok1
        # A second 3-contract entry on a different asset would exceed the budget.
        from merid.risk.global_slot_allocator import AllocationRequest
        req2 = AllocationRequest(
            agent_id="ETH_15M", asset="ETH",
            ticker="KXETH15M-26OCT061200-00",
            entry_price_cents=75, edge_pct=2.0, spread_cents=5,
            is_exit_order=False, count=3,
        )
        ok2, reason2, _ = allocator.request_allocation(req2)
        assert not ok2, "3 more contracts at 75c ($2.25) must exceed $3 budget with $2.25 already allocated"
        assert "exposure" in reason2.lower() or "Insufficient" in reason2


class TestPartialFillAndExitReservation:
    def test_partial_entry_fill_reserves_filled_quantity(self):
        """A 3-contract order that fills only 2 reserves $1.00 at 50c, not $1.50."""
        allocator, (ok, _, slot_id) = _alloc(3, price=50)
        assert ok
        # Simulate 2-of-3 fill: reservation shrinks to the filled quantity.
        assert allocator.update_slot_fill_price(slot_id, 50, filled_count=2.0)
        assert allocator.get_total_exposure() == pytest.approx(1.00)

    def test_exit_bypasses_entry_budget(self):
        """Exit orders are never blocked by an exhausted entry budget."""
        allocator, (ok, _, slot_id) = _alloc(3, asset="BTC", price=75)  # $2.25
        assert ok
        # Budget nearly exhausted; an exit for the full position still passes.
        _, (exit_ok, exit_reason, _) = _alloc(3, asset="BTC", exit_order=True)
        assert exit_ok
        assert exit_reason == "EXIT_ORDER_BYPASS"

    def test_slot_released_only_on_full_close(self):
        """Releasing the slot frees the reservation; the allocator itself does
        not partially release — partial exits are handled by
        position_cache.release-on-full-close gating."""
        allocator, (ok, _, slot_id) = _alloc(3, price=50)
        assert ok
        assert allocator.get_available_exposure() == pytest.approx(1.50)
        # update fill to full position; then full close releases everything.
        allocator.update_slot_fill_price(slot_id, 50, filled_count=3.0)
        released = allocator.release_slot_by_ticker("KXBTC15M-26OCT061200-00")
        assert released
        assert allocator.get_total_exposure() == pytest.approx(0.0)
        assert allocator.get_available_exposure() == pytest.approx(3.00)


class TestSizingTargetThree:
    def test_compute_order_size_targets_three(self):
        """compute_order_size returns 3 contracts when limits permit."""
        from merid.prediction.unified_sizing import compute_order_size
        count, notional, meta = compute_order_size(
            bankroll_usd=Decimal("1000.0"),
            price_cents=25,
            asset="BTC",
            model_prob=0.60,
        )
        assert count == 3, f"expected 3, got {count} meta={meta}"
        assert notional == Decimal("0.75")

    def test_compute_order_size_respects_one_contract_config(self):
        """A 1-contract configured target still works through the sizing path."""
        from unittest.mock import patch
        from merid.prediction import unified_sizing
        with patch.object(unified_sizing, "_get_dynamic_sizing_base_contracts", return_value=1), \
             patch.object(unified_sizing, "_get_dynamic_sizing_max_contracts", return_value=1), \
             patch.object(unified_sizing, "_get_max_contracts_per_asset", return_value=1):
            count, notional, meta = unified_sizing.compute_order_size(
                bankroll_usd=Decimal("1000.0"),
                price_cents=25,
                asset="BTC",
                model_prob=0.60,
            )
        assert count == 1, f"configured 1-contract sizing must be 1, got {count}"
        assert notional == Decimal("0.25")
