"""Property-based tests for the canonical Side/BookSide mapping.

These tests fuzz the four Kalshi order forms and the V2 price-space
conversions.  They are the durable guard against the side-inversion bug
identified in the 2026-08-27 playbook.

Invariants under test:
- bid <-> YES, ask <-> NO, always.
- The (action, traded_side) matrix has no ambiguity.
- Every (action, side, price) round-trips through legacy->V2->legacy.
- The new canonical mapping table agrees with the legacy helpers.
- Venue-reported side mismatches raise and can halt routing.
"""

from __future__ import annotations

import pytest
from decimal import Decimal
from hypothesis import given, settings, Phase, example
from hypothesis import strategies as st

from merid.event_venues.kalshi.binary_price_space import (
    Side,
    BookSide,
    OutcomeSide,
    outcome_from_action,
    book_from_outcome,
    book_price,
    book_price_dollars,
    book_price_cents,
    to_v2_order,
    to_kalshi_side,
    parse_kalshi_side,
    legacy_to_v2,
    v2_to_legacy,
    yes_delta,
    held_outcome_from_legacy,
    reconcile_venue_side,
    SideReconciliationError,
    close_outcome_side,
    close_book_side,
)


ACTIONS = ["buy", "sell"]
PRICE_CENTS = st.integers(min_value=1, max_value=99)
PRICE_DOLLARS = st.decimals(min_value="0.01", max_value="0.99", places=2)


# ── Basic cross-vocabulary invariants ──────────────────────────────────────────


@given(st.sampled_from(Side))
@settings(max_examples=100, phases=[Phase.generate])
def test_cross_vocabulary_consistency(side):
    """bid <-> yes, ask <-> no, ALWAYS."""
    book = book_from_outcome(side)
    assert (book is BookSide.BID) == (side is Side.YES)
    assert (book is BookSide.ASK) == (side is Side.NO)


@given(st.sampled_from(ACTIONS), st.sampled_from(Side))
@settings(max_examples=200, phases=[Phase.generate])
def test_action_side_matrix_exhaustive(action, side):
    """Every (action, side) maps to exactly one held outcome, no ambiguity."""
    outcome = outcome_from_action(action, side)
    assert outcome in (Side.YES, Side.NO)
    # Metamorphic: selling X == buying X.flip() (same held exposure)
    assert outcome_from_action("sell", side) == outcome_from_action("buy", side.flip())
    # A sell always produces the opposite held side to a buy of the same side.
    assert outcome_from_action("sell", side) == side.flip()


@given(PRICE_DOLLARS)
@settings(max_examples=100, phases=[Phase.generate])
def test_price_complementarity_dollars(p):
    """YES price p and NO price 1-p are complementary and sum to $1."""
    assert abs((Decimal("1.0") - p) + p - Decimal("1.0")) == Decimal("0")
    yes_part = book_price_dollars(Side.YES, p)
    no_part = book_price_dollars(Side.NO, Decimal("1.0") - p)
    assert (yes_part + no_part) == Decimal("1.0")


@given(PRICE_CENTS)
@settings(max_examples=100, phases=[Phase.generate])
def test_price_complementarity_cents(p_cents):
    """YES and NO prices in cents are complementary and sum to 100c."""
    assert (100 - p_cents) + p_cents == 100
    # A YES order at p_cents and a NO order at (100-p_cents) map to the same
    # YES-space price.
    yes_book_price = book_price_cents(Side.YES, p_cents)
    no_book_price = book_price_cents(Side.NO, 100 - p_cents)
    assert yes_book_price == no_book_price


# ── Roundtrip invariants ───────────────────────────────────────────────────────


@given(st.sampled_from(Side), st.sampled_from(ACTIONS), PRICE_CENTS)
@settings(max_examples=200, phases=[Phase.generate])
def test_v2_order_roundtrip(side, action, price_cents):
    """A (traded_side, action, price) round-trips through V2 encoding."""
    book, yes_price = to_v2_order(side, action, price_cents)
    held = outcome_from_action(action, side)
    parsed_action, parsed_side, parsed_price = v2_to_legacy(
        book.value, yes_price, held.value, action
    )
    assert parsed_action == action
    assert parsed_side == side.value
    assert parsed_price == price_cents


@given(st.sampled_from(Side), st.sampled_from(ACTIONS), PRICE_CENTS)
@settings(max_examples=200, phases=[Phase.generate])
def test_legacy_to_v2_matches_canonical_table(side, action, price_cents):
    """The legacy helper and the new canonical table produce identical V2 orders."""
    book_table, yes_price_table = to_v2_order(side, action, price_cents)
    book_legacy, yes_price_legacy = legacy_to_v2(action, side.value, price_cents)
    assert book_table.value == book_legacy
    assert yes_price_table == yes_price_legacy


@given(st.sampled_from(ACTIONS), st.sampled_from(Side))
@settings(max_examples=100, phases=[Phase.generate])
def test_kalshi_side_roundtrip(action, side):
    """Kalshi-format strings parse back to the same held outcome."""
    kalshi_side = to_kalshi_side(side.value, action)
    parsed_traded, parsed_action = parse_kalshi_side(kalshi_side)
    parsed_held = outcome_from_action(parsed_action, Side(parsed_traded))
    expected_held = outcome_from_action(action, side)
    assert parsed_held == expected_held


# ── Exposure and exit invariants ───────────────────────────────────────────────


@given(st.sampled_from(Side))
@settings(max_examples=100, phases=[Phase.generate])
def test_exit_inverts_entry_held_outcome(entry_side):
    """Selling the same contract side produces the opposite held outcome."""
    entry_held = outcome_from_action("buy", entry_side)
    exit_held = outcome_from_action("sell", entry_side)
    assert exit_held == entry_held.flip()


@given(st.sampled_from(Side))
@settings(max_examples=100, phases=[Phase.generate])
def test_close_side_matches_flip(entry_side):
    """``close_outcome_side`` returns the opposite held side."""
    exit_side = close_outcome_side(entry_side.value)
    assert Side(exit_side) == entry_side.flip()


@given(st.sampled_from(Side))
@settings(max_examples=100, phases=[Phase.generate])
def test_close_book_side_matches_canonical(entry_side):
    """A close order's book side agrees with the canonical table.

    Long YES is closed by SELL_YES -> ask.
    Long NO  is closed by SELL_NO  -> bid.
    """
    expected_book = book_from_outcome(outcome_from_action("sell", entry_side))
    assert close_book_side(entry_side.value) == expected_book.value


@given(st.sampled_from(ACTIONS), st.sampled_from(Side), st.integers(min_value=1, max_value=100))
@settings(max_examples=200, phases=[Phase.generate])
def test_signed_yes_exposure_matches_outcome(action, side, qty):
    """``yes_delta`` has the same sign as the canonical held outcome."""
    delta = yes_delta(action, side.value, qty)
    held = outcome_from_action(action, side)
    if held is Side.YES:
        assert delta == +qty
    else:
        assert delta == -qty
    # The legacy helper must agree.
    assert held_outcome_from_legacy(side.value, action) == held.value


# ── Reconciliation oracle ─────────────────────────────────────────────────────


@given(st.sampled_from(Side))
@settings(max_examples=50, phases=[Phase.generate])
def test_reconcile_venue_side_ok(side):
    """Matching sides reconcile cleanly."""
    assert reconcile_venue_side(side, side, "fill_123", "KXBTC-15M") is True


@given(st.sampled_from(Side), st.sampled_from(Side))
@settings(max_examples=50, phases=[Phase.generate])
def test_reconcile_venue_side_conflict(internal_side, venue_side):
    """A venue/internal mismatch raises ``SideReconciliationError``."""
    if internal_side is venue_side:
        return
    with pytest.raises(SideReconciliationError):
        reconcile_venue_side(internal_side, venue_side, "fill_123", "KXBTC-15M")


# ── Explicit 4x4 matrix as regression anchors ──────────────────────────────────


@pytest.mark.parametrize(
    "traded_side, action, expected_book, expected_yes_price",
    [
        (Side.YES, "buy", "bid", 55),
        (Side.YES, "sell", "ask", 55),
        (Side.NO, "buy", "ask", 45),
        (Side.NO, "sell", "bid", 45),
    ],
)
def test_v2_order_explicit_matrix(traded_side, action, expected_book, expected_yes_price):
    """The four legacy order forms map to V2 exactly as documented."""
    book, yes_price = to_v2_order(traded_side, action, 55)
    assert book.value == expected_book
    assert yes_price == expected_yes_price


@pytest.mark.parametrize(
    "action, traded_side, expected_held",
    [
        ("buy", Side.YES, Side.YES),
        ("sell", Side.NO, Side.YES),
        ("buy", Side.NO, Side.NO),
        ("sell", Side.YES, Side.NO),
    ],
)
def test_outcome_from_action_explicit_matrix(action, traded_side, expected_held):
    """The held-outcome matrix is locked."""
    assert outcome_from_action(action, traded_side) is expected_held


@pytest.mark.parametrize(
    "held, expected_book",
    [
        (Side.YES, "bid"),
        (Side.NO, "ask"),
    ],
)
def test_book_from_outcome_explicit(held, expected_book):
    """bid <-> YES, ask <-> NO."""
    assert book_from_outcome(held).value == expected_book
