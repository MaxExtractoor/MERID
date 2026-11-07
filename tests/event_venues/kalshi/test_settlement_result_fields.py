"""Tests for settlement market_outcome vs position_result labeling.

Regression for the misleading `outcome=WIN realized=loss` log that conflated
the contract's resolution with the held position's result.

2026-11 update: ``_settlement_result_fields`` returns a 7-tuple and sources
``held_side`` from ``ledger_residual_yes_cc`` — the local signed-YES
centi-contract residual reconstructed at ``settlement_time`` — not from the
exchange count fields (which are preserved observations that may carry gross
lifetime quantities on closed lifecycles, e.g. KXXRP15M-26OCT171530-30).
"""
from decimal import Decimal
from types import SimpleNamespace

from merid.event_venues.kalshi.settlement_poller import _settlement_result_fields


def _s(price_cents, ledger_residual_yes_cc=None, yes_count=0, no_count=0,
       pnl=None, settlement_time="2026-01-01T00:00:00+00:00",
       yes_count_fp=None, no_count_fp=None):
    return SimpleNamespace(
        settlement_price_cents=price_cents,
        yes_count=yes_count,
        no_count=no_count,
        yes_count_fp=yes_count_fp,
        no_count_fp=no_count_fp,
        ledger_residual_yes_cc=ledger_residual_yes_cc,
        settlement_time=settlement_time,
        realized_pnl_cents=pnl,
    )


def _fields(settlement):
    mo, hs, pr, rz, recon, exch, obs = _settlement_result_fields(settlement)
    assert obs["reconciliation_status"] == recon
    return mo, hs, pr, rz, recon, exch


def test_held_yes_market_yes_is_win():
    # 100 YES contracts held at settlement (10000 centi-contracts), exchange
    # agrees on side and quantity.
    assert _fields(_s(100, ledger_residual_yes_cc=10000, yes_count=100)) == (
        "yes", "yes", "WIN", "unknown", "matched_exposure", "yes",
    )


def test_held_yes_market_no_is_loss():
    assert _fields(_s(0, ledger_residual_yes_cc=10000, yes_count=100, pnl=-45)) == (
        "no", "yes", "LOSS", "loss", "matched_exposure", "yes",
    )


def test_held_no_market_no_is_win():
    # Negative signed-YES residual = NO contracts held.
    assert _fields(_s(0, ledger_residual_yes_cc=-10000, no_count=100, pnl=55)) == (
        "no", "no", "WIN", "profit", "matched_exposure", "no",
    )


def test_held_no_market_yes_is_loss():
    """The exact case that looked like an inversion: market settled YES while
    we held NO — contract won, position lost."""
    assert _fields(_s(100, ledger_residual_yes_cc=-10000, no_count=100, pnl=-46)) == (
        "yes", "no", "LOSS", "loss", "matched_exposure", "no",
    )


def test_no_residual_position_uses_signed_pnl():
    # Exited before settlement: ledger proves zero residual, signed PnL decides.
    flat = dict(ledger_residual_yes_cc=0)
    assert _settlement_result_fields(_s(100, pnl=20, **flat))[2] == "WIN"
    assert _settlement_result_fields(_s(0, pnl=-28, **flat))[2] == "LOSS"
    assert _settlement_result_fields(_s(100, pnl=0, **flat))[2] == "FLAT"


def test_unknown_market_result():
    assert _settlement_result_fields(_s(None))[0] == "unknown"


def test_ledger_residual_overrides_exchange_counts_for_held_side():
    """KXXRP15M-26OCT171530-30 shape: the exchange reports a nonzero count on
    a fully closed lifecycle, but the local residual is flat.  held_side must
    come from the ledger — the exchange count is an observation, not a
    residual calculator."""
    mo, hs, pr, rz, recon, exch = _fields(
        _s(100, ledger_residual_yes_cc=0, yes_count=100, pnl=30)
    )
    assert (mo, hs) == ("yes", "none")
    assert recon == "flat_vs_exchange_held"
    assert exch == "yes"
    # Flat residual: signed cash PnL is the arbiter, not the contract outcome.
    assert (pr, rz) == ("WIN", "profit")


def test_missing_ledger_history_falls_back_to_exchange_side():
    """No local fills for the market -> held_side falls back to the exchange
    count observation and reconciliation reports local_history_incomplete."""
    mo, hs, pr, rz, recon, exch = _fields(
        _s(100, ledger_residual_yes_cc=None, yes_count=100)
    )
    assert (mo, hs, pr) == ("yes", "yes", "WIN")
    assert recon == "local_history_incomplete"
    assert exch == "yes"


def test_fixed_point_counts_preferred_over_legacy_ints():
    """Fractional exchange counts reconcile at quantity level via *_fp."""
    mo, hs, pr, rz, recon, exch = _fields(
        _s(
            100,
            ledger_residual_yes_cc=10000,
            yes_count=100,
            yes_count_fp=Decimal("100.5"),
        )
    )
    assert (mo, hs, pr) == ("yes", "yes", "WIN")
    # Same side, different quantity -> warning, not a silent match.
    assert recon == "quantity_mismatch"
