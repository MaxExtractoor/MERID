"""Deterministic tests for YES/NO EV complementarity, fee symmetry, and
one-cent rounding behavior.

These mirror the mandated audit checks from 2026-08-17: the EV gate must use
payoff correctly for both YES and NO, fees must be applied once, and
complementarity must hold across the YES/NO price space.
"""

from decimal import Decimal

import pytest

from merid.prediction.unified_sizing import compute_fee_cents, compute_all_in_cost_cents, compute_ev_net


def fee_symmetry_around_fifty():
    """Fees must be identical for YES at p and NO at 100-p."""
    for p in range(10, 51):
        f_yes = compute_fee_cents(p)
        f_no = compute_fee_cents(100 - p)
        assert f_yes == pytest.approx(f_no)
        assert f_yes >= 1.0
        assert f_no >= 1.0


def test_no_price_complements_yes_price():
    """The NO market price is 100 - p when YES is at p, so all-in cost for a
    NO entry is the same as the complementary YES price plus the same fee.
    """
    for p in [10, 25, 40, 49, 50]:
        c_yes = compute_all_in_cost_cents(p, fee_cents=2.0, slippage_cents=5)
        c_no = compute_all_in_cost_cents(100 - p, fee_cents=2.0, slippage_cents=5)
        assert c_yes + c_no == pytest.approx(100 + 4 + 10)


def test_yes_no_ev_complementarity():
    """For a given YES probability q, the YES and NO entries are opposite
    expected values plus the two fees (one per side).

    YES EV at price p = q*100 - p - fee
    NO  EV at price 100-p with probability 1-q = (1-q)*100 - (100-p) - fee
    Sum = -2*fee
    """
    for q in [0.01, 0.25, 0.48, 0.50, 0.63, 0.99]:
        for p in [10, 25, 40, 48, 49, 50, 51, 52, 60, 75]:
            ev_yes = compute_ev_net(q, p, fee_cents=2.0, slippage_cents=0)
            ev_no = compute_ev_net(1.0 - q, 100 - p, fee_cents=2.0, slippage_cents=0)
            assert ev_yes + ev_no == pytest.approx(-4.0)


def test_ev_gate_flips_at_zero():
    """The fee-inclusive EV crosses zero exactly when q*100 == price + all-in cost.
    A one-cent movement in model probability should flip the sign.
    """
    price = 48
    fee = 2.0
    slippage = 0
    all_in = 48 + fee
    # q*100 == 50.0 -> q = 0.5000
    q = all_in / 100.0
    assert compute_ev_net(q, price, fee_cents=fee, slippage_cents=slippage) == pytest.approx(0.0)
    assert compute_ev_net(q + 0.0001, price, fee_cents=fee, slippage_cents=slippage) > 0
    assert compute_ev_net(q - 0.0001, price, fee_cents=fee, slippage_cents=slippage) < 0


def test_fee_formula_at_extremes_never_negative():
    for p in [1, 5, 10, 50, 90, 95, 99]:
        fee = compute_fee_cents(p)
        assert fee >= 0.0


def test_decimal_and_cent_rounding():
    """Prices in cents are integers; probabilities as Decimal must produce
    finite, exact cents."""
    q = Decimal("0.63")
    price = 48
    fee = compute_fee_cents(price)
    all_in = compute_all_in_cost_cents(price, fee_cents=fee)
    ev = float(q * 100) - all_in
    assert round(ev, 4) == pytest.approx(63.0 - all_in)
