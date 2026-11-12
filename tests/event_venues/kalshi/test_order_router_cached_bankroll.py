"""
Tests for order router cached bankroll fix.

These tests verify that the order router uses cached bankroll values
instead of blocking on get_summary_sync() calls.
"""

import pytest
from unittest.mock import Mock, patch
from decimal import Decimal


def test_apply_risk_based_order_sizing_uses_provided_bankroll():
    """Test that _apply_risk_based_order_sizing uses provided bankroll when available."""
    from merid.event_venues.kalshi.order_router import _apply_risk_based_order_sizing, OrderIntent
    
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
    )
    
    # Provide explicit bankroll
    bankroll_usd = Decimal("50.0")
    count = _apply_risk_based_order_sizing(intent, bankroll_usd=bankroll_usd)

    # Should use provided bankroll and return adjusted count.
    # The per-order cap (MERID_MAX_CONTRACTS_PER_ORDER) binds before
    # bankroll — reference the live constant, not a hardcoded value.
    from merid.risk.global_slot_allocator import MAX_CONTRACTS_PER_ORDER
    assert count is not None
    assert isinstance(count, (int, Decimal))
    assert count == MAX_CONTRACTS_PER_ORDER


def test_apply_risk_based_order_sizing_rejects_when_bankroll_unavailable():
    """No trustworthy bankroll snapshot -> fail closed (reject), never pass
    the requested quantity through."""
    from merid.event_venues.kalshi.order_router import _apply_risk_based_order_sizing, OrderIntent
    
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
    )
    
    with patch(
        "merid.event_venues.kalshi.bankroll_service_v2._BANKROLL_SERVICE_V2",
        None,
    ):
        count = _apply_risk_based_order_sizing(intent, bankroll_usd=None)

    # Fail-closed: sizing returns 0 so the caller rejects the order.
    assert count == Decimal("0") or count <= 0


def test_apply_risk_based_order_sizing_fail_closed_on_exception():
    """A sizing exception must reject the entry, not return requested size."""
    from merid.event_venues.kalshi.order_router import _apply_risk_based_order_sizing, OrderIntent

    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
    )

    with patch(
        "merid.prediction.unified_sizing.compute_order_size",
        side_effect=RuntimeError("boom"),
    ):
        # compute_order_size is imported lazily inside the function, so patch
        # the source module attribute.
        count = _apply_risk_based_order_sizing(intent, bankroll_usd=Decimal("50.0"))

    assert count == Decimal("0") or count <= 0


def test_apply_risk_based_order_sizing_uses_freshness_bounded_bankroll():
    """When no explicit bankroll is passed, the router must use the
    freshness-bounded cached equity — not raw _current.equity_usd."""
    from merid.event_venues.kalshi.order_router import _apply_risk_based_order_sizing, OrderIntent

    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
    )

    svc = Mock()
    svc.get_equity_for_risk_calc_sync_cached.return_value = 50.0
    with patch(
        "merid.event_venues.kalshi.bankroll_service_v2._BANKROLL_SERVICE_V2",
        svc,
    ):
        count = _apply_risk_based_order_sizing(intent, bankroll_usd=None)

    svc.get_equity_for_risk_calc_sync_cached.assert_called_once()
    from merid.risk.global_slot_allocator import MAX_CONTRACTS_PER_ORDER
    assert count == MAX_CONTRACTS_PER_ORDER


def test_apply_risk_based_order_sizing_passes_fee_aware_basis():
    """The router's Kelly gate must receive the same fee-aware cost basis as
    the loop: consider_fee_impact=True with a role-resolved fee estimate."""
    from merid.event_venues.kalshi.order_router import _apply_risk_based_order_sizing, OrderIntent

    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
        model_prob=0.60,
        execution_mode="taker",
    )

    captured = {}

    def _fake_compute_order_size(**kwargs):
        captured.update(kwargs)
        from decimal import Decimal as _D
        return 1.0, _D("0.5"), {"reason": "ok"}

    with patch(
        "merid.prediction.unified_sizing.compute_order_size",
        side_effect=_fake_compute_order_size,
    ):
        _apply_risk_based_order_sizing(intent, bankroll_usd=Decimal("50.0"))

    assert captured.get("consider_fee_impact") is True
    assert captured.get("estimated_fee_cents") is not None
    assert float(captured["estimated_fee_cents"]) > 0.0  # taker fee at 50c
