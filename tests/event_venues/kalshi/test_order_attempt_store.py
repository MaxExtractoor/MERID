"""Tests for the durable exit-order attempt lifecycle store."""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.order_attempt_store import (
    ExitOrderAttemptConflict,
    ExitOrderAttemptState,
    OrderAttemptStore,
)


def test_exit_attempt_lifecycle_and_concurrency(tmp_path):
    db_path = tmp_path / "test_exit_attempts.db"
    store = OrderAttemptStore(str(db_path))

    attempt = store.create_exit_attempt(
        exit_intent_id="intent-1",
        position_key="pos-1",
        ticker="KXBTC15M",
        reason="TAKE_PROFIT",
        client_order_id="co-1",
        requested_quantity=100,
        requested_limit_cents=75,
        attempt_id="attempt-1",
    )
    assert attempt is not None
    assert attempt.state == ExitOrderAttemptState.INTENT_PERSISTED.value
    assert attempt.state_version == 1
    assert store.is_terminal_state(attempt.state) is False

    active = store.get_active_exit_attempt_for_position("pos-1")
    assert active is not None
    assert active.attempt_id == attempt.attempt_id

    nonterminal = store.list_nonterminal_exit_attempts()
    assert len(nonterminal) == 1
    assert nonterminal[0].attempt_id == attempt.attempt_id

    by_coid = store.get_exit_attempt_by_client_order_id("co-1")
    assert by_coid is not None
    assert by_coid.attempt_id == attempt.attempt_id

    # Active conflict: a second attempt for the same position should raise.
    with pytest.raises(ExitOrderAttemptConflict):
        store.create_exit_attempt(
            exit_intent_id="intent-2",
            position_key="pos-1",
            ticker="KXBTC15M",
            reason="STOP_LOSS",
            client_order_id="co-2",
            requested_quantity=50,
            attempt_id="attempt-2",
        )

    # Valid FSM transitions.
    updated = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.SUBMITTING.value,
        actor="router",
        reason="submitting",
        expected_state_version=1,
    )
    assert updated is not None
    assert updated.state == ExitOrderAttemptState.SUBMITTING.value
    assert updated.state_version == 2

    updated = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.SUBMISSION_UNKNOWN.value,
        actor="router",
        reason="ack_lost",
        expected_state_version=2,
    )
    assert updated is not None
    assert updated.state == ExitOrderAttemptState.SUBMISSION_UNKNOWN.value
    assert updated.state_version == 3

    updated = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.NOT_ACCEPTED_CONFIRMED.value,
        actor="reconciler",
        reason="lookup_found_no_order",
        expected_state_version=3,
    )
    assert updated is not None
    assert updated.state == ExitOrderAttemptState.NOT_ACCEPTED_CONFIRMED.value
    assert updated.state_version == 4
    assert store.is_terminal_state(updated.state) is True

    # Once terminal, no active attempt remains.
    active = store.get_active_exit_attempt_for_position("pos-1")
    assert active is None

    # Optimistic concurrency failure: stale state version.
    stale = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.SUPERSEDED_AFTER_CONFIRMED_TERMINAL.value,
        actor="reconciler",
        reason="stale_superseded",
        expected_state_version=3,
    )
    assert stale is None

    # An invalid FSM transition should return None.
    invalid = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.FILLED.value,
        actor="reconciler",
        reason="should_fail",
        expected_state_version=4,
    )
    assert invalid is None
