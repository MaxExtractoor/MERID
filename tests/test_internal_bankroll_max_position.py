"""Tests for InternalBankroll max_position cap semantics.

The 15m crypto stack is intended to use a fixed absolute $2 exposure cap,
not a percentage of equity. These tests pin that contract.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from merid.event_venues.kalshi.types import BalanceState, InternalBankroll


def _make_bankroll(
    *,
    equity: str = "25.90",
    cash: str = "25.90",
    frac: str = "0.02",
    cap: str | None = None,
) -> InternalBankroll:
    return InternalBankroll(
        equity_usd=Decimal(equity),
        available_cash_usd=Decimal(cash),
        max_riskable_frac=Decimal(frac),
        max_position_cap_usd=Decimal(cap) if cap is not None else None,
        as_of=datetime.now(timezone.utc),
        source="test",
        state=BalanceState.FRESH,
    )


def test_absolute_limit_overrides_fraction():
    """Configured $2 cap wins over the legacy 2% of equity fallback."""
    bankroll = _make_bankroll(equity="25.90", cash="25.90", frac="0.02", cap="2.00")
    # 25.90 * 0.02 = 0.518, but cap is $2.00
    assert bankroll.max_position_usd == Decimal("2.00")


def test_absolute_limit_is_not_equity_percentage():
    """Without a cap, the legacy percentage path is still available for tests."""
    bankroll = _make_bankroll(equity="25.90", cash="25.90", frac="0.02", cap=None)
    assert bankroll.max_position_usd == Decimal("0.518")


def test_cash_caps_absolute_limit():
    """Available cash is the hard ceiling regardless of configured cap."""
    bankroll = _make_bankroll(equity="25.90", cash="1.50", frac="0.02", cap="2.00")
    assert bankroll.max_position_usd == Decimal("1.50")


def test_legacy_percentage_fallback():
    """When no absolute cap is configured, percentage fallback still works."""
    bankroll = _make_bankroll(equity="100.00", cash="95.00", frac="0.03", cap=None)
    assert bankroll.max_position_usd == Decimal("95.00") * Decimal("0.03")


def test_with_state_preserves_cap():
    """Stale/error transitions preserve the absolute cap."""
    bankroll = _make_bankroll(cap="2.00")
    stale = bankroll.with_state(BalanceState.ERROR)
    assert stale.max_position_cap_usd == Decimal("2.00")
    assert stale.max_position_usd == Decimal("2.00")
