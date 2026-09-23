"""Regression tests for the 2026-09-23 signed-proceeds fix.

Kalshi nets complement holdings at fill time.  A ``sell no`` exit order is
reported by the exchange in complement ``buy yes`` form; while the account
holds NO contracts the fill CREDITS ``no_price`` per netted contract, it does
not debit ``yes_price``.  The pre-fix code debited the execution leg price on
every buy-form fill, inverting each such exit's cash by exactly $1.00 per
contract and feeding phantom losses to ``UnifiedRiskManager.record_pnl``.

Verified against live balance deltas on 2026-09-23 (e.g. KXETH15M-230230
exit: exchange cash +$0.97, ledger had recorded -$0.0118).
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi.fills_ledger import (
    KalshiFillsLedger,
    CANONICALIZATION_VERSION,
)


def _ledger_with_prior(prior_signed_yes_cc: int) -> KalshiFillsLedger:
    """Bare ledger instance whose prior signed exposure is stubbed."""
    ledger = KalshiFillsLedger.__new__(KalshiFillsLedger)
    ledger._prior_signed_yes_cc = MagicMock(return_value=prior_signed_yes_cc)
    return ledger


def _proceeds(ledger, *, action, side, yes_price, count, qty_cc=None, fee="0"):
    yes_p = Decimal(str(yes_price))
    no_p = Decimal("1") - yes_p
    proceeds_price = yes_p if side == "yes" else no_p
    opposite_price = no_p if side == "yes" else yes_p
    return ledger._compute_signed_fill_proceeds(
        "KXBTC15M-TEST",
        execution_action=action,
        proceeds_side=side,
        proceeds_price=proceeds_price,
        opposite_price=opposite_price,
        count_fp=Decimal(str(count)),
        quantity_cc=qty_cc if qty_cc is not None else int(Decimal(str(count)) * 100),
        fee=Decimal(str(fee)),
    )


def test_canonicalization_version_bumped():
    """v4 forces re-parse of v3 rows whose proceeds carried the inversion."""
    assert CANONICALIZATION_VERSION >= 4


def test_buy_form_netted_against_held_no_credits_no_leg():
    """buy yes @0.007 while holding 1.00 NO -> +0.993 - fee (live exit fill)."""
    ledger = _ledger_with_prior(-100)
    p = _proceeds(ledger, action="buy", side="yes", yes_price="0.007",
                  count="1.00", fee="0.0005")
    assert p == Decimal("0.9925")


def test_buy_form_flat_book_pays_exec_leg():
    """buy yes @0.35 with no prior position -> -0.35 - fee (plain entry)."""
    ledger = _ledger_with_prior(0)
    p = _proceeds(ledger, action="buy", side="yes", yes_price="0.35",
                  count="1.00", fee="0.0")
    assert p == Decimal("-0.35")


def test_buy_form_partial_coverage():
    """buy yes @0.906 x0.60 while holding 0.60 NO -> +0.094*0.60 - fee."""
    ledger = _ledger_with_prior(-60)
    p = _proceeds(ledger, action="buy", side="yes", yes_price="0.906",
                  count="0.60", qty_cc=60, fee="0.0036")
    assert p == Decimal("0.0528")


def test_buy_form_overshoot_nets_then_buys():
    """buy yes @0.50 x1.00 while holding 0.60 NO -> +0.50*0.60 - 0.50*0.40."""
    ledger = _ledger_with_prior(-60)
    p = _proceeds(ledger, action="buy", side="yes", yes_price="0.50",
                  count="1.00", qty_cc=100)
    assert p == Decimal("0.10")


def test_buy_form_while_long_same_side_pays_leg():
    """buy yes @0.60 while already long YES -> -0.60 (accumulating)."""
    ledger = _ledger_with_prior(100)
    p = _proceeds(ledger, action="buy", side="yes", yes_price="0.60",
                  count="1.00")
    assert p == Decimal("-0.6")


def test_sell_form_covered_credits_leg():
    """sell yes @0.99 x1.00 while holding 1.00 YES -> +0.98 - fee."""
    ledger = _ledger_with_prior(100)
    p = _proceeds(ledger, action="sell", side="yes", yes_price="0.99",
                  count="1.00", fee="0.01")
    assert p == Decimal("0.98")


def test_sell_form_flat_mints_pair_and_pays_complement():
    """sell yes @0.66 with no prior position -> -0.34 (minted pair)."""
    ledger = _ledger_with_prior(0)
    p = _proceeds(ledger, action="sell", side="yes", yes_price="0.66",
                  count="1.00")
    assert p == Decimal("-0.34")


def test_sell_form_while_short_deepens_via_mint():
    """sell yes @0.66 while holding NO -> still minted, pays no_price."""
    ledger = _ledger_with_prior(-100)
    p = _proceeds(ledger, action="sell", side="yes", yes_price="0.66",
                  count="1.00")
    assert p == Decimal("-0.34")


def test_buy_no_form_netted_against_held_yes():
    """Mirror case: buy no @0.09 while holding YES -> credits yes_price."""
    ledger = _ledger_with_prior(60)
    p = _proceeds(ledger, action="buy", side="no", yes_price="0.91",
                  count="0.60", qty_cc=60, fee="0.0036")
    # proceeds_side=no -> proceeds_price=0.09, opposite=yes 0.91
    assert p == Decimal("0.91") * Decimal("0.60") - Decimal("0.0036")
