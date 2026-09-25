"""Tests for settlement market_outcome vs position_result labeling.

Regression for the misleading `outcome=WIN realized=loss` log that conflated
the contract's resolution with the held position's result.
"""
from types import SimpleNamespace

from merid.event_venues.kalshi.settlement_poller import _settlement_result_fields


def _s(price_cents, yes_count=0, no_count=0, pnl=None):
    return SimpleNamespace(
        settlement_price_cents=price_cents,
        yes_count=yes_count,
        no_count=no_count,
        realized_pnl_cents=pnl,
    )


def test_held_yes_market_yes_is_win():
    assert _settlement_result_fields(_s(100, yes_count=100)) == ("yes", "yes", "WIN", "unknown")


def test_held_yes_market_no_is_loss():
    assert _settlement_result_fields(_s(0, yes_count=100, pnl=-45)) == ("no", "yes", "LOSS", "loss")


def test_held_no_market_no_is_win():
    assert _settlement_result_fields(_s(0, no_count=100, pnl=55)) == ("no", "no", "WIN", "profit")


def test_held_no_market_yes_is_loss():
    """The exact case that looked like an inversion: market settled YES while
    we held NO — contract won, position lost."""
    mo, hs, pr, rz = _settlement_result_fields(_s(100, no_count=100, pnl=-46))
    assert (mo, hs, pr, rz) == ("yes", "no", "LOSS", "loss")


def test_no_residual_position_uses_signed_pnl():
    # Exited before settlement: counts zero, signed PnL decides.
    assert _settlement_result_fields(_s(100, pnl=20))[2] == "WIN"
    assert _settlement_result_fields(_s(0, pnl=-28))[2] == "LOSS"
    assert _settlement_result_fields(_s(100, pnl=0))[2] == "FLAT"


def test_unknown_market_result():
    assert _settlement_result_fields(_s(None))[0] == "unknown"
