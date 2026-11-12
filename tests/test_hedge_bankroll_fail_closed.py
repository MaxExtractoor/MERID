"""Behavioral tests for hedge sizing bankroll resolution (fail closed).

The hedge pass sizes real entry orders from bankroll slices.  When equity
is unavailable, stale, or the service errors, the resolved bankroll must be
0 so ``compute_hedge_intents`` produces no orders — never a fabricated
default.  Replaces source-scan assertions with outcome checks.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from merid.loop_15m import _hedge_sizing_bankroll_cents


class _FakeBankrollService:
    def __init__(self, equity):
        self._equity = equity
        self.get_equity_for_risk_calc = AsyncMock(return_value=equity)


@pytest.mark.asyncio
async def test_no_service_yields_zero():
    assert await _hedge_sizing_bankroll_cents(None) == 0


@pytest.mark.asyncio
async def test_unavailable_equity_yields_zero():
    svc = _FakeBankrollService(None)
    assert await _hedge_sizing_bankroll_cents(svc) == 0


@pytest.mark.asyncio
async def test_zero_and_negative_equity_yield_zero():
    for equity in (Decimal("0"), Decimal("-5"), 0.0, -1.0):
        svc = _FakeBankrollService(equity)
        assert await _hedge_sizing_bankroll_cents(svc) == 0


@pytest.mark.asyncio
async def test_service_exception_yields_zero():
    svc = MagicMock()
    svc.get_equity_for_risk_calc = AsyncMock(side_effect=RuntimeError("boom"))
    assert await _hedge_sizing_bankroll_cents(svc) == 0


@pytest.mark.asyncio
async def test_verified_equity_converts_to_cents():
    svc = _FakeBankrollService(Decimal("44.35"))
    assert await _hedge_sizing_bankroll_cents(svc) == 4435


@pytest.mark.asyncio
async def test_zero_bankroll_produces_no_hedge_intents():
    """End-to-end contract: bankroll_cents=0 -> engine emits nothing."""
    from merid.event_venues.kalshi.order_router import compute_hedge_intents

    assert compute_hedge_intents(bankroll_cents=0) == []
