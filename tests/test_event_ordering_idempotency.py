"""Exchange-event ordering and reconciliation idempotency tests.

The 15m stack ingests the same fill from multiple sources (WebSocket, HTTP
poller, backfill).  These tests verify that the order state machine and fill
handling paths are deterministic and idempotent.
"""

import pytest

from merid.event_venues.kalshi.order_state_machine import (
    OrderState,
    OrderStateMachine,
    TransitionResult,
)


def test_duplicate_fill_transition_is_idempotent():
    """Applying the same fill transition twice returns DUPLICATE and does not regress state."""
    sm = OrderStateMachine()
    sm.initialize_order("order-1", OrderState.SUBMITTED)

    # First a partial fill, then a full fill.
    r1 = sm.attempt_transition(
        "order-1", OrderState.PARTIALLY_FILLED, filled_qty=50, context={"fill_id": "f1"}
    )
    assert r1 == TransitionResult.ALLOWED

    r2 = sm.attempt_transition(
        "order-1", OrderState.FILLED, filled_qty=100, context={"fill_id": "f2"}
    )
    assert r2 == TransitionResult.ALLOWED

    # Repeating the same terminal transition is a DUPLICATE.
    r3 = sm.attempt_transition(
        "order-1", OrderState.FILLED, filled_qty=100, context={"fill_id": "f2"}
    )
    assert r3 == TransitionResult.DUPLICATE
    assert sm.get_current_state("order-1") == OrderState.FILLED


def test_late_fill_after_terminal_is_flagged_not_reopened():
    """A fill arriving after the order is terminal is LATE_FILL and leaves state unchanged."""
    sm = OrderStateMachine()
    sm.initialize_order("order-2", OrderState.SUBMITTED)
    sm.attempt_transition("order-2", OrderState.PARTIALLY_FILLED, filled_qty=50, context={"fill_id": "f1"})
    sm.attempt_transition("order-2", OrderState.FILLED, filled_qty=100, context={"fill_id": "f2"})

    r = sm.attempt_transition(
        "order-2", OrderState.PARTIALLY_FILLED, filled_qty=50, context={"fill_id": "f3"}
    )
    assert r == TransitionResult.LATE_FILL
    assert sm.get_current_state("order-2") == OrderState.FILLED
    assert sm.get_late_fills("order-2")


def test_fill_quantity_monotonicity():
    """A transition that reports a lower cumulative filled quantity is still allowed but logged."""
    sm = OrderStateMachine()
    sm.initialize_order("order-3", OrderState.SUBMITTED)
    sm.attempt_transition("order-3", OrderState.PARTIALLY_FILLED, filled_qty=75, context={"fill_id": "f1"})

    # The final fill reports 50 even though we already saw 75.  The state machine
    # logs a critical monotonicity violation but still transitions to FILLED because
    # the (PARTIALLY_FILLED, FILLED) pair is in the allowed table.
    r = sm.attempt_transition(
        "order-3", OrderState.FILLED, filled_qty=50, context={"fill_id": "f2"}
    )
    assert r == TransitionResult.ALLOWED
    assert sm.get_current_state("order-3") == OrderState.FILLED
    assert sm._order_filled_qty.get("order-3") == 50


def test_order_intent_add_fill_is_terminal_idempotent():
    """fills_ledger.OrderIntent.add_fill must not regress a filled intent."""
    from merid.event_venues.kalshi.fills_ledger import OrderIntent

    intent = OrderIntent(
        intent_id="intent-1",
        ticker="KXBTC15M-TEST",
        action="buy",
        side="yes",
        price_cents=50,
        count=1,
    )
    intent.status = "submitted"
    intent.add_fill("f1", 1)
    assert intent.status == "filled"

    # A duplicate/late fill is rejected to prevent terminal-state regression.
    intent.add_fill("f2", 1)
    assert intent.status == "filled"
    assert "f1" in intent.fill_ids
    assert "f2" not in intent.fill_ids
