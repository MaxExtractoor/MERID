"""Regression test: /api/v1/kalshi/balance cent-field rounding consistency.

Bug (2026-11-17): ``balance_cents`` was derived as ``int(usd * 100)`` which
truncates sub-cent precision from Kalshi's ``balance_dollars`` string.
With exact cash $16.9183 the endpoint reported ``balance_cents=1691``
($16.91) while ``trading_shard_balance_usd`` kept full precision and the
frontend's ``Math.round(usd * 100)`` rendered shard 2 as $16.92 — a phantom
$0.01 bankroll-vs-shard discrepancy on the dashboard.

The fix rounds to nearest cent (ROUND_HALF_UP), matching both the
codebase's ``dollars_to_cents`` convention and the frontend shard path.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from merid.event_venues.kalshi.bankroll_service_v2 import BankrollSummary
from merid.event_venues.kalshi.types import BalanceState


class _FakeBankrollService:
    def __init__(self, summary: BankrollSummary, portfolio_cents: int = 0):
        self._summary = summary
        self._portfolio_cents = portfolio_cents

    async def get_summary(self, caller_module: str | None = None):
        return self._summary

    async def get_portfolio_value_cents(self) -> int:
        return self._portfolio_cents


def _summary(available: str) -> BankrollSummary:
    return BankrollSummary(
        equity_usd=Decimal(available),
        available_cash_usd=Decimal(available),
        state=BalanceState.FRESH,
        max_position_usd=Decimal("11.0"),
        as_of=datetime.now(timezone.utc),
        source="kalshi",
    )


async def _call_balance(available: str, portfolio_cents: int = 0):
    from web.api import kalshi_api

    service = _FakeBankrollService(_summary(available), portfolio_cents)
    with patch.object(kalshi_api, "get_bankroll_service", new=AsyncMock(return_value=service)):
        return await kalshi_api.get_balance()


@pytest.mark.asyncio
async def test_balance_cents_rounds_half_up_not_floor():
    """$16.9183 must yield balance_cents=1692 ($16.92), not 1691 ($16.91).

    This is the exact live value that produced the reported discrepancy.
    """
    resp = await _call_balance("16.9183")
    assert resp["balance_cents"] == 1692
    assert resp["usd"] == pytest.approx(16.9183)
    # total_value_cents is derived from balance_cents + portfolio_cents.
    assert resp["total_value_cents"] == 1692


@pytest.mark.asyncio
async def test_balance_cents_exact_cent_boundary_unchanged():
    """Whole-cent and exact .005 boundaries keep stable values."""
    resp = await _call_balance("16.9100")
    assert resp["balance_cents"] == 1691

    resp = await _call_balance("16.9150")
    assert resp["balance_cents"] == 1692  # ROUND_HALF_UP: .5 rounds up


@pytest.mark.asyncio
async def test_total_value_cents_includes_portfolio():
    resp = await _call_balance("16.9183", portfolio_cents=250)
    assert resp["balance_cents"] == 1692
    assert resp["portfolio_cents"] == 250
    assert resp["total_value_cents"] == 1942
